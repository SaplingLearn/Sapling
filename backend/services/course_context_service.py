"""
services/course_context_service.py

Builds and caches shared class-level context from real DB data.
Aggregates graph_nodes mastery data and quiz_context across the students in an
offering (a course taught in a term) who share class context (#72 — the
persisted user_settings.share_class_context opt-out is enforced here, at the
write chokepoint). The graph is keyed on the abstract course; analytics are
keyed on the offering.

Stores data in:
- offering_concept_stats: per-concept aggregated metrics (per offering)
- offering_summary: class-wide summary with Gemini-generated text (per offering)

The prose in offering_summary.summary_text has no reader on any request path.
Two regimes, switched by the process-wide LEARNING_LOOP_ENABLED (a class mixes
students on and off the loop, so a per-user gate cannot pick):
- loop off (the pre-series product, unchanged): `update_course_context`
  regenerates the prose synchronously whenever the per-concept stats hash moves.
- loop on (spec §13 A35): `update_course_context` writes the same numbers and
  no prose (NULL text and hash), and nothing else writes it. The loop moves
  mastery on every graded answer, so the old regime put a course_summary call
  on the answer path for each of the student's offerings, for text nothing reads.
"""

import copy
import json
import hashlib
import logging
import random
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone

import config
from db.connection import table
from db.scope import runs_as_service
from agents._run import run_agent_sync
from agents.course_summary import course_summary_agent
from agents.usage import record_agent_usage
from services import jobs
from services.encryption import bind, decrypt_json_column
from services.feature_flags import flag_on

logger = logging.getLogger(__name__)

#: The job that runs update_course_context on the queue (#116).
COURSE_CONTEXT_JOB = "course_context.refresh"

#: M8: an aggregated mistake (or weak area) reaches classmates' quiz prompts
#: only when at least this many DISTINCT students' quiz notes contain it. With
#: n=1 allowed, one student's written quiz answers could write the "common
#: class mistakes" every classmate's quiz agent reads. Stamped on each stats
#: row as `min_mistake_contributors` (migration
#: 20261116162354_offering_stats_min_contributors.sql); the reader
#: (agents/tools/graph_read.py) serves only rows stamped at or above it, so
#: rows aggregated before this rule are never served.
MIN_MISTAKE_CONTRIBUTORS = 3


def _mistake_key(text: str) -> str:
    """How two students' notes are judged to name the same mistake: case,
    whitespace and trailing punctuation folded."""
    return " ".join((text or "").split()).casefold().rstrip(" .;:!?")


def _generate_data_hash(stats_rows: list) -> str:
    """Generate a hash of the stats data to detect changes."""
    data_str = json.dumps(stats_rows, sort_keys=True, default=str)
    return hashlib.sha256(data_str.encode()).hexdigest()


def _filter_shared_context_users(user_ids: list) -> list:
    """#72: keep only users who share class context.

    The Class Intel toggle used to gate only the READ path (a per-request
    flag); the persisted ``user_settings.share_class_context`` column (0037)
    makes the opt-out durable, and this filter enforces it here — the single
    write chokepoint every class-aggregate refresh funnels through. A user
    with no settings row (or a row predating 0037) is opted IN, matching the
    column default: only an explicit ``false`` excludes them.
    """
    if not user_ids:
        return []
    id_filter = ",".join(user_ids)
    settings_rows = table("user_settings").select(
        "user_id,share_class_context",
        filters={"user_id": f"in.({id_filter})"},
    )
    opted_out = {
        r["user_id"]
        for r in (settings_rows or [])
        if r.get("share_class_context") is False
    }
    if not opted_out:
        return user_ids
    return [uid for uid in user_ids if uid not in opted_out]


def _generate_summary_with_gemini(
    course_code: str,
    course_name: str,
    avg_class_mastery: float,
    top_struggling: list,
    top_mastered: list,
    student_count: int,
) -> str:
    """Generate a natural-language class summary via the course_summary agent.

    The agent owns the analyst persona; the aggregated metrics go in the user
    message. On any agent failure we degrade to a deterministic template string
    (no second LLM call), so a summary is always produced."""
    # M10 audit: concept names are students' graph text, so the two lists go
    # in the untrusted envelope; the course code/name are neutralized scalars.
    from services.prompt_safety import neutralize_delimiters, wrap_untrusted

    def _concepts(names: list, source: str) -> str:
        return wrap_untrusted("\n".join(f"- {c}" for c in names), source=source) or "None identified"

    user_message = (
        f"Course: {neutralize_delimiters(course_code or '')} - "
        f"{neutralize_delimiters(course_name or '')}\n"
        f"Students enrolled: {student_count}\n"
        f"Average class mastery: {avg_class_mastery:.1%}\n\n"
        "Top struggling concepts (needs attention):\n"
        f"{_concepts(top_struggling or [], 'struggling concept names from students graphs')}\n\n"
        "Top mastered concepts (students doing well):\n"
        f"{_concepts(top_mastered or [], 'mastered concept names from students graphs')}"
    )

    try:
        result = record_agent_usage(
            run_agent_sync(course_summary_agent.run(user_message)),
            feature="course_summary", task="course_summary",
        )
        return result.output.summary
    except Exception:
        # Fallback summary if the agent fails
        return (
            f"Class average mastery: {avg_class_mastery:.1%}. "
            f"Students are struggling with: {', '.join(top_struggling[:3]) if top_struggling else 'No major areas identified'}. "
            f"Students have mastered: {', '.join(top_mastered[:3]) if top_mastered else 'No areas identified yet'}."
        )


#: Upper bound on how stale a cached course context can be (#771). The clear
#: hook below only reaches THIS process: another worker's
#: `update_course_context` used to leave this one serving its old copy for
#: as long as the process lived. Each entry expires on its own clock, at a
#: jittered 90-100% of this TTL from when it was read, so every worker
#: converges within one TTL without all offerings refetching at the same
#: instant; a same-process update still clears at once.
COURSE_CONTEXT_TTL_S = 60.0
_TTL_JITTER = 0.1
#: Entries kept per process; expired entries go first, then least recently used.
COURSE_CONTEXT_CACHE_MAX = 512

# offering_id -> (expires_at monotonic, context). LRU order, newest last.
_cache: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()
_cache_lock = threading.Lock()
#: Bumped by every clear: a read that began before a clear must not store its
#: (pre-update) result after it.
_cache_generation = 0


@runs_as_service  # #115: a class aggregate shared through a per-process cache: the fill must not depend on which student asked first
def _read_course_context(offering_id: str) -> dict:
    """Uncached read. Raises on a store error (the caller answers {} and
    caches nothing, so a transient failure never pins an empty context)."""
    summary_rows = table("offering_summary").select(
        "*",
        filters={"offering_id": f"eq.{offering_id}"},
    )
    if not summary_rows:
        return {}

    summary = summary_rows[0]

    # Get concept stats for this offering
    stats_rows = table("offering_concept_stats").select(
        "*",
        filters={"offering_id": f"eq.{offering_id}"},
    )

    return {
        "course_summary": {
            "offering_id": summary["offering_id"],
            "student_count": summary["student_count"],
            "avg_class_mastery": summary["avg_class_mastery"],
            "top_struggling_concepts": summary.get("top_struggling_concepts", []),
            "top_mastered_concepts": summary.get("top_mastered_concepts", []),
            "summary_text": summary.get("summary_text", ""),
            "updated_at": summary["updated_at"],
        },
        "concept_stats": stats_rows or [],
    }


def get_course_context(offering_id: str) -> dict:
    """
    Return the cached class context for an offering: summary + concept stats.
    Offering-scoped (one class instance in one term). Returns {} if not found.

    Cached per-process (#98), invalidated by ``update_course_context`` (which
    runs after graph updates) in this process and by COURSE_CONTEXT_TTL_S in
    every other (#771). Returns a deep copy so callers can't mutate the shared
    cached value. A failed read returns {} and is not cached.
    """
    if not offering_id:
        return {}
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(offering_id)
        if hit is not None and hit[0] > now:
            _cache.move_to_end(offering_id)
            return copy.deepcopy(hit[1])
        generation = _cache_generation
    try:
        value = _read_course_context(offering_id)
    except Exception:
        return {}
    ttl = COURSE_CONTEXT_TTL_S * (1.0 - random.uniform(0.0, _TTL_JITTER))
    with _cache_lock:
        if generation == _cache_generation:
            _cache[offering_id] = (time.monotonic() + ttl, value)
            _cache.move_to_end(offering_id)
            _evict_locked()
    return copy.deepcopy(value)


def _evict_locked() -> None:
    """Hold the size bound: drop expired entries, then the least recently
    used. Caller holds _cache_lock."""
    if len(_cache) <= COURSE_CONTEXT_CACHE_MAX:
        return
    now = time.monotonic()
    for key in [k for k, (exp, _) in _cache.items() if exp <= now]:
        del _cache[key]
    while len(_cache) > COURSE_CONTEXT_CACHE_MAX:
        _cache.popitem(last=False)


def clear_course_context_cache() -> None:
    """Drop the per-process course-context cache. Called whenever the underlying
    aggregates change (``update_course_context``) and from test setup."""
    global _cache_generation
    with _cache_lock:
        _cache.clear()
        _cache_generation += 1


def _concept_metrics(node_rows: list) -> tuple[dict, list, dict]:
    """Steps 4-5 of `update_course_context`: per-concept metrics over the
    class's graph nodes, every score, and node id -> owning student (M8)."""
    # ── 4. Group by concept_name, track per-user scores ───────────────────────
    concept_data: dict = {}

    #: graph node id -> the student who owns it, so a quiz-context row (keyed
    #: on its node) can be counted per distinct student (M8).
    node_owner: dict = {}
    for n in node_rows:
        name = n["concept_name"]
        if name not in concept_data:
            concept_data[name] = {"scores": [], "tiers": [], "node_ids": []}
        concept_data[name]["scores"].append(float(n["mastery_score"] or 0.0))
        concept_data[name]["tiers"].append(n["mastery_tier"] or "unexplored")
        concept_data[name]["node_ids"].append(n["id"])
        node_owner[n["id"]] = n.get("user_id")

    # ── 5. Compute per-concept metrics ────────────────────────────────────────
    concept_metrics: dict = {}
    all_scores: list = []

    for name, data in concept_data.items():
        scores = data["scores"]
        tiers = data["tiers"]
        n_s = len(scores)

        if n_s == 0:
            continue

        avg_mastery = sum(scores) / n_s
        all_scores.extend(scores)

        struggling_count = sum(1 for t in tiers if t == "struggling")
        mastered_count = sum(1 for t in tiers if t == "mastered")
        unexplored_count = sum(1 for t in tiers if t == "unexplored")

        concept_metrics[name] = {
            "avg_mastery_score": round(avg_mastery, 4),
            "pct_struggling": round(struggling_count / n_s, 4),
            "pct_mastered": round(mastered_count / n_s, 4),
            "pct_unexplored": round(unexplored_count / n_s, 4),
            "student_count": n_s,
            "node_ids": data["node_ids"],
        }
    return concept_metrics, all_scores, node_owner


@runs_as_service  # #115: reads every classmate's graph + quiz context; under a user scope it would silently compute class stats from one student
def update_course_context(offering_id: str) -> None:
    """
    Aggregate mastery + quiz data for the students enrolled in an **offering**
    (a course taught in a term) and upsert into offering_concept_stats and
    offering_summary. Offering-scoped. Called automatically after any graph update.
    With the loop on it writes no prose (§13 A35; see the module docstring).
    Students who opted out of sharing (user_settings.share_class_context = false,
    #72) are excluded before any of their graph data is read.

    The knowledge graph is keyed on the *abstract* course id, so we resolve the
    offering → its abstract course to read graph_nodes.
    """
    if not offering_id:
        return

    # ── 1. Get all students enrolled in this offering via enrollments ─────────
    enrollment_rows = table("enrollments").select(
        "user_id",
        filters={"offering_id": f"eq.{offering_id}"},
    )
    if not enrollment_rows:
        # No students enrolled — purge any stale aggregates
        table("offering_concept_stats").delete({"offering_id": f"eq.{offering_id}"})
        table("offering_summary").delete({"offering_id": f"eq.{offering_id}"})
        clear_course_context_cache()  # #98: aggregates changed → drop cached read
        return

    user_ids = [r["user_id"] for r in enrollment_rows]

    # ── 1b. Respect the persisted Class Intel opt-out (#72) ───────────────────
    user_ids = _filter_shared_context_users(user_ids)
    if not user_ids:
        # Every enrolled student opted out — same treatment as "no students":
        # purge any stale aggregates so previously shared data stops being
        # served, rather than crashing or publishing stats nobody consented to.
        table("offering_concept_stats").delete({"offering_id": f"eq.{offering_id}"})
        table("offering_summary").delete({"offering_id": f"eq.{offering_id}"})
        clear_course_context_cache()  # #98: aggregates changed → drop cached read
        return

    student_count = len(user_ids)

    # ── 2. Resolve the offering → abstract course (graph key) + term label ────
    from services.academics import offering_course_id
    abstract_course_id = offering_course_id(offering_id)
    if not abstract_course_id:
        return
    course_rows = table("courses").select(
        "course_code,course_name",
        filters={"id": f"eq.{abstract_course_id}"},
    )
    course_info = course_rows[0] if course_rows else {"course_code": "", "course_name": ""}

    # ── 3. All graph nodes for this (abstract) course across enrolled students ─
    # Build user_id filter for PostgREST
    user_filter = ",".join(user_ids)
    node_rows = table("graph_nodes").select(
        "id,concept_name,mastery_score,mastery_tier,user_id",
        filters={"course_id": f"eq.{abstract_course_id}", "user_id": f"in.({user_filter})"},
    )
    if not node_rows:
        return  # No graph data yet for this course

    concept_metrics, all_scores, node_owner = _concept_metrics(node_rows)

    # ── 6. Helpers: quiz_context rows for a set of graph node ids ────────────
    def _fetch_quiz_context_rows(node_ids: list) -> list:
        if not node_ids:
            return []
        chunk_size = 80
        out = []
        for i in range(0, len(node_ids), chunk_size):
            chunk = node_ids[i : i + chunk_size]
            node_filter = ",".join(chunk)
            try:
                rows = table("quiz_context").select(
                    # user_id: half of the context_json binding (AAD).
                    "user_id,concept_node_id,context_json",
                    filters={"concept_node_id": f"in.({node_filter})"},
                )
            except Exception:
                rows = []
            out.extend(rows or [])
        return out

    def _parse_quiz_context_to_arrays(ctx_rows: list) -> tuple[list, list]:
        # #572 (canonical telling — other mentions of this drop point back
        # here): `quiz_context.context_json` never carries an
        # `effective_explanations` key — `agents/quiz_context.py::QuizContext`
        # writes exactly `weak_areas`/`common_mistakes`/`questions_seen_summary`/
        # `recommended_difficulty`/`notes` (every stored row also carries a
        # server-stamped `schema_version`, added by
        # `services/quiz_context_service.py::save_quiz_context`, not by the
        # model). A prior version of this function read `effective_explanations`
        # here too, which meant `offering_concept_stats.effective_explanations`
        # always persisted an empty array — indistinguishable from "this class
        # produced no effective explanations". Only the dead read is gone; the
        # column itself stays. Its DB default (`'{}'`) covers a fresh INSERT,
        # but the upsert below runs `on_conflict="offering_id,concept_name"` —
        # a merge-duplicates UPDATE on an existing row — and never mentions
        # this column in its payload, so an existing row's value (including
        # anything written out-of-band) is left untouched, not reset.
        # M8: each entry is counted once per DISTINCT student (a student's
        # notes on one concept can vouch for a mistake only once), and only
        # entries at least MIN_MISTAKE_CONTRIBUTORS students share are kept.
        # A row whose owner cannot be told is not counted at all.
        mistakes: dict = {}  # key -> {"text": first spelling, "students": set}
        weak: dict = {}

        def _count(bucket: dict, value, student) -> None:
            text = value.strip() if isinstance(value, str) else ""
            key = _mistake_key(text)
            if not key:
                return
            entry = bucket.setdefault(key, {"text": text, "students": set()})
            entry["students"].add(student)

        for ctx in ctx_rows:
            student = node_owner.get(ctx.get("concept_node_id"))
            if not student:
                continue
            cj = ctx.get("context_json") or {}
            # Outside the try: a row without its key is a select bug, not a
            # corrupt value to skip quietly.
            where = bind("quiz_context", "context_json", ctx)
            try:
                cj = decrypt_json_column(cj, bind=where) or {}
            except Exception:
                cj = {}

            for m in cj.get("common_mistakes", []) or []:
                _count(mistakes, m, student)
            for w in cj.get("weak_areas", []) or []:
                _count(weak, w, student)

        def _shared(bucket: dict) -> list:
            kept = [e for e in bucket.values() if len(e["students"]) >= MIN_MISTAKE_CONTRIBUTORS]
            kept.sort(key=lambda e: -len(e["students"]))  # most widely shared first
            return [e["text"] for e in kept]

        return _shared(mistakes)[:20], _shared(weak)[:20]

    # ── 7. Upsert into course_concept_stats (quiz arrays per concept) ─────────
    for name, metrics in concept_metrics.items():
        node_ids_for_concept = metrics.get("node_ids", [])
        ctx_rows = _fetch_quiz_context_rows(node_ids_for_concept)
        cm, pg = _parse_quiz_context_to_arrays(ctx_rows)

        table("offering_concept_stats").upsert(
            {
                "offering_id": offering_id,
                "concept_name": name,
                "student_count": metrics["student_count"],
                "avg_mastery_score": metrics["avg_mastery_score"],
                "pct_mastered": metrics["pct_mastered"],
                "pct_struggling": metrics["pct_struggling"],
                "pct_unexplored": metrics["pct_unexplored"],
                "common_misconceptions": cm,
                "prerequisite_gaps": pg,
                # M8: the distinct-student floor these arrays were built under.
                "min_mistake_contributors": MIN_MISTAKE_CONTRIBUTORS,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="offering_id,concept_name",
        )

    # ── 8. Compute course-wide summary metrics ────────────────────────────────
    avg_class_mastery = round(sum(all_scores) / len(all_scores), 4) if all_scores else 0.0
    
    # Sort for top struggling (highest pct_struggling) and top mastered, excluding zeros
    sorted_by_struggling = sorted(
        [(name, m) for name, m in concept_metrics.items() if m["pct_struggling"] > 0.0],
        key=lambda x: x[1]["pct_struggling"],
        reverse=True,
    )
    top_struggling_concepts = [name for name, _ in sorted_by_struggling[:5]]

    sorted_by_mastered = sorted(
        [(name, m) for name, m in concept_metrics.items() if m["pct_mastered"] > 0.0],
        key=lambda x: x[1]["pct_mastered"],
        reverse=True,
    )
    top_mastered_concepts = [name for name, _ in sorted_by_mastered[:5]]

    if config.LEARNING_LOOP_ENABLED:
        # §13 A35: the numbers, and no prose. This runs after every evidence
        # flush for each of the student's offerings of the course, and the
        # prose has no reader. The text and its hash are cleared: prose from
        # before the loop turned on would contradict the numbers the loop
        # keeps moving, and a NULL hash makes the pre-series regime below
        # rewrite it once if the kill switch turns the loop off.
        table("offering_summary").upsert(
            {
                "offering_id": offering_id,
                "student_count": student_count,
                "avg_class_mastery": avg_class_mastery,
                "top_struggling_concepts": top_struggling_concepts,
                "top_mastered_concepts": top_mastered_concepts,
                "summary_text": None,
                "summary_hash": None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="offering_id",
        )
        clear_course_context_cache()  # #98: aggregates changed → drop cached read
        return

    # Generate data hash to detect changes
    stats_for_hash = [
        {
            "concept": name,
            "avg_mastery": m["avg_mastery_score"],
            "pct_struggling": m["pct_struggling"],
            "pct_mastered": m["pct_mastered"],
        }
        for name, m in concept_metrics.items()
    ]
    current_hash = _generate_data_hash(stats_for_hash)

    # ── 9. Check if summary needs regeneration ─────────────────────────────────
    existing_summary_rows = table("offering_summary").select(
        "summary_hash,summary_text",
        filters={"offering_id": f"eq.{offering_id}"},
    )
    
    existing_hash = existing_summary_rows[0]["summary_hash"] if existing_summary_rows else None
    
    # Regenerate summary only if data changed or no existing summary
    if current_hash != existing_hash or not existing_summary_rows:
        summary_text = _generate_summary_with_gemini(
            course_info.get("course_code", ""),
            course_info.get("course_name", ""),
            avg_class_mastery,
            top_struggling_concepts,
            top_mastered_concepts,
            student_count,
        )
    else:
        summary_text = existing_summary_rows[0].get("summary_text", "")

    # ── 10. Upsert into offering_summary ──────────────────────────────────────
    table("offering_summary").upsert(
        {
            "offering_id": offering_id,
            "student_count": student_count,
            "avg_class_mastery": avg_class_mastery,
            "top_struggling_concepts": top_struggling_concepts,
            "top_mastered_concepts": top_mastered_concepts,
            "summary_text": summary_text,
            "summary_hash": current_hash,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="offering_id",
    )

    # #98: the aggregates this offering's context reads from just changed.
    clear_course_context_cache()


def refresh_course_context(offering_id: str, *, user_id: str | None = None) -> None:
    """Refresh an offering's class aggregates: the one trigger every caller uses.

    `jobs_queue` flag off (the default) for `user_id`, the student whose action
    triggered the refresh: runs ``update_course_context`` right here, exactly
    as every caller did before (#116). Callers keep their own placement (a
    BackgroundTask, the upload post-roll, or inline) and their own error
    handling, because this raises whatever ``update_course_context`` raises.

    Flag on: enqueues a ``course_context.refresh`` job and returns at once.
    The dedupe key is per offering, so a burst of triggers while one refresh
    waits collapses into that one (the aggregation recomputes from scratch and
    is safe to re-run). The worker (`python -m worker`) runs the same
    ``update_course_context``; with no worker running the job waits in
    ``jobs`` and the aggregates go stale until one starts. If the enqueue
    itself fails (the jobs migration not applied yet, PostgREST down) the
    refresh runs inline instead, so turning the flag on never loses one.

    The cache: ``update_course_context`` clears THIS process's course-context
    cache. On the queue it runs in the worker, so API processes pick the new
    aggregates up within COURSE_CONTEXT_TTL_S (#771) instead of at once.
    """
    if not offering_id:
        return
    if flag_on(jobs.JOBS_QUEUE_FLAG, user_id):
        try:
            jobs.enqueue(
                COURSE_CONTEXT_JOB,
                {"offering_id": offering_id},
                dedupe_key=f"{COURSE_CONTEXT_JOB}:{offering_id}",
            )
            return
        except Exception:
            logger.warning(
                "course context: enqueue failed for offering %s; refreshing inline",
                offering_id, exc_info=True,
            )
    update_course_context(offering_id)


@jobs.job_handler(COURSE_CONTEXT_JOB)
def _run_course_context_job(payload: dict) -> None:
    """Worker side of ``refresh_course_context``."""
    offering_id = (payload or {}).get("offering_id")
    if not isinstance(offering_id, str) or not offering_id:
        raise jobs.PermanentJobError("course_context.refresh: payload has no offering_id")
    update_course_context(offering_id)
