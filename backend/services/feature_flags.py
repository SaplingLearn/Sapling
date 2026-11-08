"""Feature flags (#620, ADR 0029): declared in code, configured in the DB.

A flag is a registry entry here (key, variants, description, client_visible).
Its CONFIGURATION — default, percentage rollout, user/role rules — lives in
`feature_flags` / `feature_flag_targets` and is edited from /admin.

Resolution, first match wins (see `explain`): env override → fail-closed →
user rule → role rule (highest roles.display_priority, then lowest role id)
→ percentage rollout (stable sha256 bucket) → default. Anything unreadable or
invalid resolves to variants[0] ("off"). Reads come from a per-process
snapshot (30 s, `FEATURE_FLAGS_SNAPSHOT_TTL_S`); admin writes call
`clear_feature_flags_cache()` (#98). A user's roles are cached 60 s
(`FEATURE_FLAGS_ROLES_TTL_S`). Both TTLs are read at call time; 0 means
"always read fresh" (the E2E stack exports 0 so a per-test DB reset is seen
immediately).
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import threading
import time
from dataclasses import dataclass

import httpx
from fastapi import HTTPException, Request

from db.connection import page_all, table

logger = logging.getLogger("sapling.feature_flags")


@dataclass(frozen=True)
class FlagDef:
    key: str
    variants: tuple[str, ...]  # variants[0] is the OFF variant (fail-closed answer)
    description: str
    client_visible: bool


#: Main-nav features an admin can hide (sidebar + top nav, and the route
#: redirects to /dashboard). "on" HIDES, so the fail-closed "off" leaves the
#: feature visible. Frontend twin: frontend/src/lib/navFeatures.ts. The API
#: side is NAV_FEATURE_API at the bottom of this module (#771).
NAV_FEATURES: tuple[tuple[str, str], ...] = (
    ("tutor", "Tutor"), ("quiz", "Quiz"), ("tree", "Tree"), ("study", "Study"),
    ("library", "Library"), ("calendar", "Calendar"),
    ("social", "Social"), ("achievements", "Achievements"),
    ("grades", "Grades"), ("notetaker", "Notetaker"),
    ("course_planner", "Course Planner"),
)

#: Features that are no longer their own nav row but keep a hide flag: Quiz
#: is a tab under Study since #753 (frontend twin: NESTED_NAV_FEATURES).
_NESTED_NAV_DESCRIPTIONS: dict[str, str] = {
    "quiz": "Hide Quiz (a tab under Study); its pages redirect to /dashboard.",
}

REGISTRY: dict[str, FlagDef] = {f.key: f for f in (
    *(FlagDef(f"hide_{slug}", ("off", "on"),
              _NESTED_NAV_DESCRIPTIONS.get(
                  slug, f"Hide {label} from the nav; its pages redirect to /dashboard."),
              True)
      for slug, label in NAV_FEATURES),
    # #672 (ADR 0027): which decision-seam backends the observe-only tutor
    # router runs for a student. Server-only: the router acts on nothing, so
    # the client has no use for it. SAPLING_FLAG_DECISION_ROUTER is its env
    # kill switch like any flag's; under SAPLING_MODEL_MODE=function an on
    # variant runs the scripted backend (`decisions.router_backends`).
    FlagDef("decision_router", ("off", "jev", "jev_shadow"),
            "Tutor turn router on the Jev decision seam (ADR 0027). jev_shadow "
            "also runs flash-lite to measure agreement.", False),
    # #677 (ADR 0028): PostHog product analytics, end to end — the backend
    # worker drops every capture for a student it resolves "off" for, and the
    # frontend (#675) never starts posthog-js. The #620 migration seeds it
    # "on", so analytics stays on wherever it already was.
    FlagDef("product_analytics", ("off", "on"),
            "PostHog product analytics, frontend + backend (ADR 0028).", True),
    # #695 (learning-loop spec §13 A113): "Report this question" on the loop's
    # check card and Study's review queue, and POST /api/learn/loop/report.
    # Client-visible: the frontend renders the control only when "on". Reports
    # already made keep excluding their items whatever the flag says. Since
    # A123 reports quarantine an item (a reversible hold); only staff retire.
    FlagDef("item_reports", ("off", "on"),
            "Students can report a learning-loop check question (wrong answer / "
            "unclear / not from my course); two reporters hold it from every "
            "student in the course until staff approve or retire it.",
            True),
    # Learning loop spec §13 A126: the "retention check due" badge on the Study
    # nav entry and the Dashboard, and GET /api/learn/loop/posttest/due (404
    # while off). Client-visible: the frontend fetches nothing while it is off.
    # It turns the delayed post-test from pull to push, a change to the
    # measurement protocol, so it is switched on deliberately (at a trial
    # boundary), never by a deploy.
    FlagDef("retention_due_badge", ("off", "on"),
            "Show students a 'retention check due' badge on Study and the Dashboard "
            "when a delayed post-test window is open with an item to pose (A126).",
            True),
    # Learning loop spec §13 A130: the matched pretest probe start
    # (checks.pretest_form, read by routes/learn_loop.py::probe_next). Server-
    # only: the probe route picks the item. It changes the measurement
    # protocol — which item is each new concept's pretest — so, like
    # retention_due_badge, it is switched on deliberately at a trial boundary,
    # never by a deploy.
    FlagDef("probe_matched_pretest", ("off", "on"),
            "The probe asks a concept's first question, when the student has no graded "
            "answer on it yet, in a form parallel to its delayed post-test items (same "
            "format and difficulty, else the same difficulty; A130), so pre/post pairs "
            "are matched. Changes the measurement protocol: switch it on at a trial "
            "boundary. Off: the probe's choice is unchanged.", False),
    # Learning loop spec §13 A118: upload prerequisite edges
    # (services/concept_prereqs.py). Resolved ONCE per upload, for the
    # uploading student, by upload_prereqs_on; that one answer picks the
    # concept-extraction variant AND gates the edge write. Server-only: both
    # happen inside the upload routes.
    FlagDef("upload_prereq_edges", ("off", "on"),
            "Uploads ask concept extraction for prerequisite relations (with the "
            "course's existing concepts as context) and write them, validated in "
            "code, as prerequisite edges (A118). On changes learning dynamics for "
            "upload-built graphs: one-hop evidence propagation, prerequisite bands "
            "and wheelspin repair, the novice exit and the planner's outer fringe "
            "start acting on them, so plan order follows prerequisites. Off: the "
            "upload is byte-identical to before A118 (same extraction prompt, "
            "schema and message; no course-concepts read) and writes concept "
            "nodes only.", False),
    # Learning loop spec §13 A121: the tutor's v2 variant
    # (agents/loop_tutor.py::variant_run_args) — every loop tutor prompt change
    # that needs a live eval re-record. Resolved ONCE per turn, for the
    # student, by routes/learn_loop.py::_tutor_v2_on; that one answer picks the
    # prompt and schema variant, the per-turn prompt lines and the served
    # framing. Server-only: the turn's text arrives already framed.
    FlagDef("loop_tutor_v2", ("off", "on"),
            "Loop tutor v2 (A121): a student's reply to the tutor's own question "
            "opens the next turn with a plain verdict (right / partly right / not "
            "quite), feedback turns open with the grader's verdict, 'Key idea:' "
            "marks only new content, a turn that poses a check is asked for no "
            "question, and every teach turn names the plan's current concept and "
            "why the plan is on it. On sends a changed tutor prompt and output "
            "schema, so turn it on only after the loop_tutor and "
            "misconception_confront datasets are re-recorded live under "
            "LOOP_EVAL_VARIANT=v2 (their own cassettes) and pass. "
            "Off: the tutor request is byte-identical to before A121.", False),
    # Learning loop spec §13 A134: the strict genuine-attempt rule for hint
    # unlocking (learning/gates.py::strict_genuine_attempt). Resolved per
    # request, for the student, by routes/learn_loop.py::_help_gate_strict_on
    # (POST /step/attempt counts an attempt by it; POST /hint words its
    # time-alone denial by it). Server-only: the client renders the denial
    # reason it is sent. Turning it on is the owner's pedagogy decision, judged
    # by the A133 help-abuse report (GET /api/admin/analytics/learning-loop,
    # `help_abuse.by_gate`). Off: both routes behave exactly as before A134.
    FlagDef("help_gate_strict", ("off", "on"),
            "Strict genuine-attempt gate for loop hints (A134): an attempt "
            "unlocks the next hint rung only after the band's independent time "
            "(45 s; 90 s for a novice) alone with the latest hint, and only when "
            "it says something none of the student's counted attempts on the item "
            "said and is not a paste of the question. Off: an attempt counts after "
            "that time since the question was posed, so later rungs need only the "
            "8 s dwell. Judge it by the help-abuse report on the admin learning-"
            "loop page (by gate).", False),
    # Learning loop spec §13 A138: the segment prequestion — one ungraded guess
    # at the start of a teaching segment, its answer and explanation right
    # after. Resolved ONCE per request, for the student, by
    # routes/learn_loop.py::_prequestion_on. Server-only: the card is posed by
    # the server's responses. Off: nothing is posed or read, and every tutor
    # request is byte-identical to before A138.
    FlagDef("segment_prequestion", ("off", "on"),
            "Segment prequestion (A138): when the plan reaches a new concept, the "
            "student first takes an ungraded guess at one vetted question on it "
            "(multiple choice or short answer, difficulty 1-2, never a post-test "
            "item; 'No idea' allowed); the answer and an explanation that starts "
            "from the guess follow at once. No grade, no evidence, no mastery "
            "change; the item is revealed for that student. Skipped for due "
            "reviews, concepts already proficient, exam mode, and when the "
            "question would leave the concept's checks short. On sends a changed "
            "tutor prompt on the explaining turn, so turn it on only after that "
            "path is recorded live in the loop_tutor evals. Off: byte-identical "
            "to before A138.", False),
    # Learning loop spec §13 A139: self-explanation prompts — one interrogative
    # "why does this follow?" as a turn's question at a code-decided juncture.
    # Resolved ONCE per request, for the student, by
    # routes/learn_loop.py::_self_explain_on. Server-only. The reply is stored
    # (encrypted) for diagnosis only: never evidence, mastery or a misconception.
    FlagDef("self_explanation_prompts", ("off", "on"),
            "Self-explanation prompts (A139): after a worked example, after a "
            "shown solution, or after a first unaided correct answer, the turn's "
            "question becomes a 'why does this follow?' prompt (at most once per "
            "concept per session) with its own reply box; the reply is stored for "
            "staff analysis and is never graded or used as evidence. The next "
            "tutor turn acknowledges a reply briefly, a changed prompt: turn it on "
            "only after that path is recorded live in the loop_tutor evals. Off: "
            "byte-identical to before A139.", False),
    # Learning loop spec §13 A140: surface-varied isomorphs. Resolved ONCE per
    # drafting run for the uploader (services/check_item_service.py::
    # drafting_flags: the varied drafter and its structured surface
    # descriptor) and per pick for the student being served (the cue-
    # familiarity tie-break in-session, on the isomorph re-ask and in review,
    # and the review interleave's definitional-item rule). Server-only.
    FlagDef("varied_isomorphs", ("off", "on"),
            "Surface-varied isomorphs (A140): this uploader's check items are drafted "
            "so each concept's items vary their scenario and representation, each "
            "with a stored surface descriptor; for this student, every check, "
            "isomorph re-ask and review pick prefers, among items its own rules "
            "leave equal, one whose surface they have not met on the concept, and "
            "the review interleave never pairs recall-or-definition items. On sends "
            "a changed drafting prompt and output schema, so turn it on only after "
            "the varied check_items eval dataset is recorded live and passes. Off: "
            "drafting and every pick are byte-identical to before A140.", False),
    # Learning loop spec §13 A141: multi-concept items. Resolved ONCE per
    # drafting run for the uploader (the combination drafter, from the
    # uploader's prerequisite edges) and per activation for the student (the
    # ideas-combined dial in routes/learn_loop.py). Server-only.
    FlagDef("multi_concept_items", ("off", "on"),
            "Multi-concept items (A141): this uploader's uploads also draft items "
            "that combine a concept with one or two of its direct prerequisites, "
            "every component verified; this student is served one, once a session, "
            "on a concept whose every component they are proficient in (p >= 0.95 "
            "with a strong unassisted answer behind it) while its difficulty is at "
            "the top, and the answer is a half-weight observation on that concept. "
            "On sends new drafting prompts, so turn it on only after the multi-"
            "concept eval dataset is recorded live and passes. Off: drafting and "
            "every pick are byte-identical to before A141.", False),
    # Learning loop spec §13 A143-A147: the quiz in the learning system. Five
    # flags because each part rolls out on its own condition; all ship off and,
    # off, the quiz is byte-identical to before them
    # (tests/test_quiz_learning_flags_off.py).
    #
    # A143: the quiz home's proposals and its "due" queue come from the learner
    # model (GET /api/quiz/plan, 404 while off). Client-visible: the home asks
    # for the plan only when it is on. Reads only, no model call.
    FlagDef("quiz_concept_plan", ("off", "on"),
            "Quiz concept plan (A143): the quiz home proposes concepts from the "
            "learner model — reviews due by their FSRS date first, then concepts "
            "with an open misconception, then concepts whose prerequisites are "
            "proficient but which are not yet — and 'Review everything due' means "
            "due by FSRS. Reads only. Off: the home ranks by the graph's mastery "
            "tier as before.", True),
    # A144: code chooses each question's difficulty (the band's loop check
    # level when the student asked for adaptive) and the misconception one
    # distractor must embody; a separate prompt (agents/quiz_planned.py) is
    # told only that, and tags its distractors with the named keys. Resolved
    # once per /generate for the student. Server-only.
    FlagDef("quiz_planned_questions", ("off", "on"),
            "Quiz planned questions (A144): the learner model chooses each "
            "question's difficulty and the misconception a distractor targets; "
            "the model only writes them, with options alike in length, and tags "
            "its distractors with the named misconception keys. On sends a new "
            "quiz prompt and schema, so turn it on only after the "
            "quiz_generation_planned eval dataset is recorded live and passes. "
            "Off: the quiz request is byte-identical to before A144.", False),
    # A145: every generated question passes the A119 concept check and the
    # A124 blind key solve (slot `quiz_check`, a different model from the
    # quiz writer) before it is served; only a verified one is evidence.
    # Resolved once per /generate for the student. Server-only.
    FlagDef("quiz_item_gates", ("off", "on"),
            "Quiz item gates (A145): each generated question is checked before it "
            "is served — does it test this concept (the A119 check) and does an "
            "independent blind solve reach its key (A124) — on the quiz_check "
            "slot. A question testing another concept, or whose key the solve "
            "disputes, is never served; only a verified one moves mastery. Adds "
            "two to three model calls per quiz: turn it on after a live smoke of "
            "the checks on quiz questions and a measured cost. Off: unchanged.",
            False),
    # A146: a verified question's tagged distractor chosen with "Sure" records
    # the misconception; a correct, unassisted, first answer to a verified
    # question listing an open key closes it (A127). Resolved once per /submit.
    # Needs quiz_planned_questions (the tags) and quiz_item_gates (verified
    # items) on when the quiz was generated. Server-only.
    FlagDef("quiz_misconceptions", ("off", "on"),
            "Quiz misconceptions (A146): a wrong answer stated 'Sure' on a verified "
            "quiz question whose chosen option embodies a known misconception "
            "records that misconception for the student (the Learn tutor and the "
            "review queue then see it), and a correct, unassisted first answer to a "
            "verified question listing an open misconception closes it. Acts only "
            "on questions generated with quiz_planned_questions and "
            "quiz_item_gates on. Off: the quiz records and closes nothing.",
            False),
    # A147: the submit response's `learning` block — each concept's skill-meter
    # change, what is due for review, and the next step. Resolved once per
    # /submit for the student. Server-only: the results screen renders the
    # block whenever the response carries one.
    FlagDef("quiz_results_routing", ("off", "on"),
            "Quiz results routing (A147): the quiz results show, in plain words, "
            "how each concept's skill meter moved, what is due for review, and the "
            "next step — review what is due, or practise the weakest concept in "
            "Learn. Reads only. Off: the results are unchanged.", False),
    # docs/safety/crisis-support.md: the crisis-support path. On: a student
    # message that states suicidal ideation, self-harm or acute danger gets
    # the fixed resources card INSTEAD of a model turn, on every surface
    # services/crisis_support.py lists. Server-only: the client renders the
    # card whenever a response carries one. SHIPS OFF until the owner has
    # reviewed the copy (services/crisis_support_copy.py).
    FlagDef("crisis_support", ("off", "on"),
            "Crisis-support path: a student message stating suicidal ideation, "
            "self-harm or acute danger gets a fixed card with crisis resources "
            "(988, Crisis Text Line, campus counseling, 911) instead of a model "
            "turn, on every tutor, learning-loop and notes AI surface. Keep OFF "
            "until the owner has reviewed the copy in "
            "services/crisis_support_copy.py (checklist: "
            "docs/safety/crisis-support.md).", False),
)}

STEPS = ("env_override", "fail_closed", "user", "role", "rollout", "default")


@dataclass(frozen=True)
class Resolution:
    variant: str
    step: str
    detail: str = ""


@dataclass(frozen=True)
class Snapshot:
    flags: dict[str, dict]           # key -> feature_flags row
    targets: dict[str, list[dict]]   # key -> feature_flag_targets rows


#: Every resolver read of the flag store (the snapshot, a user's roles) is
#: bounded by this — not the connection's 30 s default — and a failed
#: SNAPSHOT read marks the store unreadable for STORE_UNREADABLE_TTL_S, during
#: which resolution fails closed WITHOUT another read (a failed roles read
#: fails only that user's resolution). An outage therefore costs
#: each process one bounded wait per window, not one hung read per call (the
#: tutor router and the PostHog worker resolve per item).
STORE_TIMEOUT_S = 2.5
STORE_UNREADABLE_TTL_S = 30.0
#: Resolution.detail when the store could not be read — the one signal a
#: caller may key on to tell "unreadable" from a real or invalid answer.
STORE_UNREADABLE = "flag store unreadable"


class StoreUnreadable(RuntimeError):
    """The flag store is (still) unreadable; raised by the snapshot/roles
    reads inside the negative-cache window."""


#: What counts as "the store did not answer": the negative-cache marker, and
#: any httpx error (transport, timeout, or a PostgREST error status). Any
#: other exception is a data/config bug and is reported as one.
_STORE_ERRORS: tuple[type[BaseException], ...] = (StoreUnreadable, httpx.HTTPError)


SNAPSHOT_TTL_ENV = "FEATURE_FLAGS_SNAPSHOT_TTL_S"
ROLES_TTL_ENV = "FEATURE_FLAGS_ROLES_TTL_S"
DEFAULT_SNAPSHOT_TTL_S = 30.0
DEFAULT_ROLES_TTL_S = 60.0

_lock = threading.Lock()
_snapshot: tuple[float, Snapshot] | None = None
#: Bumped by every clear. A snapshot read that began before a clear must not
#: store its (pre-write) result after it, or the write stays invisible for a
#: whole TTL.
_generation = 0
_roles: dict[str, tuple[float, tuple[tuple[str, int], ...]]] = {}
_warned: set[str] = set()
#: Bounds on the two per-process maps keyed by caller input (#771): one entry
#: per student ever resolved (roles) and one per distinct warning. Past the
#: cap the oldest role entry goes (a re-read costs one bounded query); the
#: warned set is reset (a warning may then repeat once).
ROLES_CACHE_MAX = 10_000
WARNED_MAX = 1_000


class _Flight:
    """One in-flight snapshot read that concurrent cold callers wait on
    instead of each reading the store (#771: single-flight)."""

    __slots__ = ("done", "generation", "result", "error")

    def __init__(self, generation: int) -> None:
        self.done = threading.Event()
        self.generation = generation
        self.result: Snapshot | None = None
        self.error: BaseException | None = None


_flight: _Flight | None = None
#: monotonic time until which the store counts as unreadable (0 = readable).
_store_down_until = 0.0


def _ttl(env: str, default: float) -> float:
    try:
        value = float(os.getenv(env) or default)
    except ValueError:
        return default
    return value if math.isfinite(value) and value >= 0 else default


def snapshot_ttl_s() -> float:
    return _ttl(SNAPSHOT_TTL_ENV, DEFAULT_SNAPSHOT_TTL_S)


def roles_ttl_s() -> float:
    return _ttl(ROLES_TTL_ENV, DEFAULT_ROLES_TTL_S)


def _warn_once(key: str, msg: str, *args, **kwargs) -> None:
    if key not in _warned:
        if len(_warned) >= WARNED_MAX:
            _warned.clear()
        _warned.add(key)
        logger.warning(msg, *args, **kwargs)


def clear_feature_flags_cache() -> None:
    global _snapshot, _generation, _store_down_until
    with _lock:
        _snapshot = None
        _generation += 1
        _store_down_until = 0.0  # a write just went through: read again


def clear_user_roles_cache(user_id: str | None = None) -> None:
    with _lock:
        if user_id is None:
            _roles.clear()
        else:
            _roles.pop(user_id, None)


def read_config(*, timeout: float | None = None) -> Snapshot:
    """Uncached read of every flag row and rule (admin API + cache fill).
    Paged in a total order: offset paging over an unordered select can skip
    or repeat a row at a page boundary. ``timeout`` bounds each page read
    (the resolver passes STORE_TIMEOUT_S; the admin API keeps the default)."""
    flags = list(page_all(
        table("feature_flags"),
        "key,default_variant,rollout_percent,rollout_variant,updated_at,updated_by",
        order="key", timeout=timeout,
    ))
    targets = list(page_all(
        table("feature_flag_targets"),
        "flag_key,target_type,target_id,variant,created_at,created_by",
        order="flag_key,target_type,target_id", timeout=timeout,
    ))
    by_key: dict[str, list[dict]] = {}
    for t in targets:
        by_key.setdefault(t["flag_key"], []).append(t)
    return Snapshot(flags={f["key"]: f for f in flags}, targets=by_key)


def _get_snapshot(fresh: bool = False) -> Snapshot:
    global _snapshot, _flight
    ttl = snapshot_ttl_s()
    global _store_down_until
    if fresh:
        with _lock:
            generation = _generation
        # The admin path (ADR 0029): the connection's normal timeout, and an
        # admin read never marks the store down — it only clears the mark
        # when it succeeds.
        snap = read_config()
        return _store_snapshot(snap, generation)
    with _lock:
        generation = _generation
        if _snapshot and time.monotonic() - _snapshot[0] < ttl:
            return _snapshot[1]
        if time.monotonic() < _store_down_until:
            raise StoreUnreadable("flag store unreadable (cached)")
        # Single-flight (#771): a cold cache used to send every concurrent
        # caller to the store. Join a read already in flight for this
        # generation (one begun before a clear would serve a pre-write view);
        # otherwise lead one.
        flight = _flight
        leader = flight is None or flight.generation != generation
        if leader:
            flight = _flight = _Flight(generation)
    if not leader:
        # The leader's read is bounded per page by STORE_TIMEOUT_S; wait a
        # little longer than a two-page read, then fail closed.
        if not flight.done.wait(STORE_TIMEOUT_S * 3):
            raise StoreUnreadable("flag store read still in flight")
        if flight.error is not None:
            raise flight.error
        assert flight.result is not None
        return flight.result
    try:
        try:
            snap = read_config(timeout=STORE_TIMEOUT_S)
        except _STORE_ERRORS:
            _mark_store_down()  # callers fail closed; nothing re-reads for a while
            raise
        flight.result = snap
        return _store_snapshot(snap, generation)
    except BaseException as exc:
        flight.error = exc
        raise
    finally:
        with _lock:
            if _flight is flight:
                _flight = None
        flight.done.set()


def _store_snapshot(snap: Snapshot, generation: int) -> Snapshot:
    global _snapshot, _store_down_until
    with _lock:
        _store_down_until = 0.0  # the store answered
        if generation == _generation:  # no clear landed while we were reading
            _snapshot = (time.monotonic(), snap)
    # The store answered: a later outage is news again, so let it warn.
    for key in REGISTRY:
        _warned.discard(f"store:{key}")
    return snap


def _mark_store_down() -> None:
    global _store_down_until
    with _lock:
        _store_down_until = time.monotonic() + STORE_UNREADABLE_TTL_S


def _roles_peek(user_id: str) -> tuple[tuple[str, int], ...] | None:
    """This user's cached roles if still fresh, else None. Never reads."""
    with _lock:
        hit = _roles.get(user_id)
        return hit[1] if hit and time.monotonic() - hit[0] < roles_ttl_s() else None


def _user_roles(user_id: str) -> tuple[tuple[str, int], ...]:
    now = time.monotonic()
    with _lock:
        hit = _roles.get(user_id)
        if hit and now - hit[0] < roles_ttl_s():
            return hit[1]
        if now < _store_down_until:
            raise StoreUnreadable("flag store unreadable (cached)")
    # A failed read raises into explain(), which fails closed for THIS
    # user's resolution only: one user's roles read does not mark the whole
    # store down (only a snapshot read does).
    rows = table("user_roles").select(
        "role_id,roles!inner(display_priority)", filters={"user_id": f"eq.{user_id}"},
        timeout=STORE_TIMEOUT_S,
    ) or []
    out = tuple(
        (str(r["role_id"]), int(((r.get("roles") or {}).get("display_priority")) or 0))
        for r in rows
    )
    with _lock:
        _roles.pop(user_id, None)  # re-inserted last: insertion order = age
        _roles[user_id] = (time.monotonic(), out)
        while len(_roles) > ROLES_CACHE_MAX:
            _roles.pop(next(iter(_roles)))
    return out


def rollout_bucket(key: str, user_id: str) -> float:
    """Stable 0.00–99.99 bucket per (flag, user). Raising the percentage only
    ever adds users: membership at p is a subset of membership at any p' > p."""
    digest = hashlib.sha256(f"{key}:{user_id}".encode()).hexdigest()
    return int(digest[:8], 16) % 10000 / 100


def explain(key: str, user_id: str | None, *, fresh: bool = False,
            _snapshot: Snapshot | Exception | None = None,
            _roles_known: tuple[tuple[str, int], ...] | None = None) -> Resolution:
    """`_snapshot`: a snapshot (or the error reading it) already taken by a
    caller resolving many flags at once, so one outage costs one store read,
    not one per flag. The env override still wins over it. `_roles_known`:
    the user's roles, already resolved by a caller that must not do I/O
    (:func:`cached_explain`)."""
    fd = REGISTRY.get(key)
    if fd is None:
        _warn_once(f"unregistered:{key}", "feature flag %r is not registered; off", key)
        return Resolution("off", "fail_closed", "unregistered flag")
    off = fd.variants[0]

    env = (os.getenv(f"SAPLING_FLAG_{key.upper()}") or "").strip().lower()
    if env:
        if env in fd.variants:
            return Resolution(env, "env_override", f"SAPLING_FLAG_{key.upper()}")
        _warn_once(f"env:{key}:{env}", "SAPLING_FLAG_%s=%r is not a variant of %s; ignored",
                   key.upper(), env, fd.variants)

    def valid(v, step: str, detail: str) -> Resolution:
        if v in fd.variants:
            return Resolution(v, step, detail)
        return Resolution(off, "fail_closed", f"invalid stored variant {v!r} ({step})")

    try:
        if isinstance(_snapshot, Exception):
            raise _snapshot
        snap = _snapshot if _snapshot is not None else _get_snapshot(fresh)
        row = snap.flags.get(key)
        if user_id:
            rules = snap.targets.get(key, [])
            for t in rules:
                if t["target_type"] == "user" and t["target_id"] == user_id:
                    return valid(t["variant"], "user", user_id)
            role_rules = {t["target_id"]: t for t in rules if t["target_type"] == "role"}
            if role_rules:
                roles = _roles_known if _roles_known is not None else _user_roles(user_id)
                held = [(p, rid) for rid, p in roles if rid in role_rules]
                if held:
                    held.sort(key=lambda pr: (-pr[0], pr[1]))
                    rid = held[0][1]
                    return valid(role_rules[rid]["variant"], "role", rid)
            if row and (row.get("rollout_percent") or 0) > 0 and row.get("rollout_variant"):
                if rollout_bucket(key, user_id) < row["rollout_percent"]:
                    return valid(row["rollout_variant"], "rollout", f"{row['rollout_percent']}%")
        if row:
            return valid(row["default_variant"], "default", "stored default")
        return Resolution(off, "default", "no stored configuration")
    except _STORE_ERRORS:
        _warn_once(f"store:{key}", "feature flag store unreadable; %r fails closed", key,
                   exc_info=True)
        return Resolution(off, "fail_closed", STORE_UNREADABLE)
    except Exception as exc:
        # A data/config bug (a malformed target row, ...), not an outage:
        # say what it is, and fail closed for this flag only.
        logger.error("feature flag %r failed to resolve (%s: %s); fails closed",
                     key, type(exc).__name__, exc)
        return Resolution(off, "fail_closed", f"resolution error: {type(exc).__name__}")


def cached_explain(key: str, user_id: str | None) -> Resolution | None:
    """:func:`explain` without any I/O, or None when answering would need a
    store read (a cold snapshot, or a role lookup this user has no fresh
    cache entry for). Safe on an event loop. Inside the unreadable window it
    answers — fail closed — without a read."""
    fd = REGISTRY.get(key)
    if fd is None:
        return explain(key, user_id)  # unregistered: answered without I/O
    env = (os.getenv(f"SAPLING_FLAG_{key.upper()}") or "").strip().lower()
    if env in fd.variants:
        return explain(key, user_id)  # the env override wins before any read
    with _lock:
        cached = _snapshot
        down = time.monotonic() < _store_down_until
    if cached is not None and time.monotonic() - cached[0] < snapshot_ttl_s():
        snap = cached[1]
        roles = None
        if user_id and any(t["target_type"] == "role" for t in snap.targets.get(key, [])):
            # Resolved ONCE here and handed to explain(), so a roles entry
            # that expires between the check and the use cannot turn this
            # into a blocking read.
            roles = _roles_peek(user_id)
            if roles is None:
                return None  # would need this user's roles
        return explain(key, user_id, _snapshot=snap, _roles_known=roles)
    if down:
        return Resolution(fd.variants[0], "fail_closed", STORE_UNREADABLE)
    return None


def flag_variant(key: str, user_id: str | None) -> str:
    return explain(key, user_id).variant


def flag_on(key: str, user_id: str | None) -> bool:
    fd = REGISTRY.get(key)
    return fd is not None and flag_variant(key, user_id) != fd.variants[0]


def resolved_client_flags(user_id: str | None) -> dict[str, str]:
    """Every client-visible flag from ONE snapshot read. Resolving them one by
    one would retry the store per flag during an outage — 11 timeouts in a
    row on GET /api/flags, while NavFeatureGate keeps flagged pages veiled."""
    try:
        snap: Snapshot | Exception = _get_snapshot()
    except Exception as exc:
        snap = exc
    return {k: explain(k, user_id, _snapshot=snap).variant
            for k, fd in REGISTRY.items() if fd.client_visible}


def store_unreadable() -> bool:
    """Whether the flag store is inside its unreadable window right now — so
    a fail-closed answer just given was an outage, not configuration. GET
    /api/flags reports it (``degraded``) so the client keeps its last-known
    nav flags instead of un-hiding every hidden feature (#771)."""
    with _lock:
        return time.monotonic() < _store_down_until


def require_flag(key: str):
    """Route dependency: 404 when `key` is off for the session user."""
    def _dependency(request: Request) -> None:
        from services.auth_guard import get_session_user_id
        try:
            uid = get_session_user_id(request)
        except HTTPException:
            uid = None
        if not flag_on(key, uid):
            raise HTTPException(status_code=404, detail="Not found")
    return _dependency


#: The backend half of the ``hide_<feature>`` flags (#771): the API routers a
#: hidden feature's pages use, mounted in main.py with
#: ``require_feature_visible``. A hidden feature used to stay fully callable —
#: the flags were enforced only by the frontend nav. Each router is listed
#: under the ONE flag that hides it; ``exempt`` names the (method, path regex)
#: pairs another visible surface still calls, so hiding one feature never
#: breaks another. A ``hide_*`` flag absent here is deliberately not enforced
#: on the API (``NAV_FEATURES_NOT_ENFORCED`` says why).
NAV_FEATURE_API: dict[str, dict[str, tuple[tuple[str, str], ...]]] = {
    "hide_quiz": {
        # Tree shows the student's recent attempts.
        "/api/quiz": (("GET", r"/attempts"),),
    },
    "hide_study": {"/api/flashcards": (), "/api/study-guide": ()},
    "hide_calendar": {
        # The dashboard's upcoming-deadlines card.
        "/api/calendar": (("GET", r"/upcoming/[^/]+"),),
    },
    "hide_social": {
        # Friends are on every profile page (ProfileView), not just Social.
        "/api/social": (("*", r"/friends(/.*)?"),),
    },
    "hide_achievements": {
        # The quiz results screen shows the XP/streak delta.
        "/api/gamification": (("GET", r"/me"),),
    },
    # /api/gradescope stays: Settings > Connected accounts manages it.
    "hide_grades": {"/api/gradebook": ()},
    "hide_notetaker": {"/api/notes": ()},
}

NAV_FEATURES_NOT_ENFORCED: dict[str, str] = {
    "hide_tutor": "the quiz Ask panel streams through the tutor's chat/session "
                  "endpoints and the dashboard/tree list sessions; the learning "
                  "loop's /api/learn/loop also serves quiz-ask sessions, Study's "
                  "daily review and the delayed post-test",
    "hide_tree": "/api/graph backs the course list every page loads",
    "hide_library": "/api/documents backs the shared upload modal (Calendar) and "
                    "Study's document list",
    "hide_course_planner": "the page is static; it calls no API",
}


def require_feature_visible(flag: str, prefix: str):
    """Router dependency for a ``hide_<feature>`` flag: 404 when the flag hides
    the feature for the session user, except on the ``NAV_FEATURE_API``
    exemptions for ``prefix``. Fail-closed "off" (an unreadable store) means
    visible, exactly as the nav reads it."""
    exempt = tuple(
        (method, re.compile(re.escape(prefix) + pattern + r"/?$"))
        for method, pattern in NAV_FEATURE_API[flag][prefix]
    )

    def _dependency(request: Request) -> None:
        path = request.url.path
        if any((m == "*" or m == request.method) and rx.match(path) for m, rx in exempt):
            return
        from services.auth_guard import get_session_user_id
        try:
            uid = get_session_user_id(request)
        except HTTPException:
            uid = None
        if flag_variant(flag, uid) == "on":
            raise HTTPException(status_code=404, detail="Not found")
    return _dependency


def nav_feature_gate(prefix: str) -> list:
    """``include_router(dependencies=...)`` for the router mounted at
    ``prefix``: the ``require_feature_visible`` gate of the ``hide_*`` flag
    that lists it in NAV_FEATURE_API."""
    from fastapi import Depends

    flag = next(f for f, routers in NAV_FEATURE_API.items() if prefix in routers)
    return [Depends(require_feature_visible(flag, prefix))]
