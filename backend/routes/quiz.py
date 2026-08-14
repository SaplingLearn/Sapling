import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from pydantic_ai.exceptions import UsageLimitExceeded, UnexpectedModelBehavior

import config
from agents import ORCHESTRATOR_LIMITS, TOPUP_LIMITS
from agents._providers import UnregisteredHandlerError
from agents.quiz import quiz_agent, Quiz, QuizQuestion, PROMPT_VERSION
from agents.deps import SaplingDeps
from agents._run import run_agent_sync
from agents.quiz_context import quiz_context_agent
from agents.usage import record_agent_usage, served_model_name
from db.connection import table
from models import AnswerQuestionBody, GenerateQuizBody, SubmitQuizBody
from routes.learn import _get_catalog_chunk
from services import events_service
from services.auth_guard import require_self
from services.quiz_config import (
    CONCRETE_DIFFICULTIES,
    QUIZ_ATTEMPT_ABANDON_TTL_HOURS,
    QUIZ_DAILY_SPEND_CAP_USD,
    QUIZ_GENERATE_RATE_LIMIT,
    QUIZ_GENERATE_RATE_WINDOW_SEC,
    QUIZ_GENERATION_TIMEOUT_SEC,
    QUIZ_TOPUP_DROP_RATIO,
    QUIZ_TOPUP_MAX_RETRIES,
    REQUESTED_DIFFICULTIES,
    mastery_after,
    quiz_config_payload,
)
from services.request_limits import check_rate_limit, refund_rate_limit
from services.quiz_errors import QuizAPIError, QuizErrorCode
from services.profiles import get_display_name
from services.encryption import encrypt_json, decrypt_json_column
from services.graph_service import apply_graph_update
from services.quiz_context_service import get_quiz_context, save_quiz_context
from services.fingerprint import fingerprint
from services.quiz_identity import question_hash, normalize_text
from services.quiz_repetition import RecentQuestion, recent_question_identities
from services import prompt_dimensions
from services.rag_service import retrieve_chunks, format_rag_context
from services.xp_service import award_xp_safe
from services.request_context import current_request_id

logger = logging.getLogger(__name__)

router = APIRouter()

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")

# Request-side difficulties live in services/quiz_config.py (#540 A2):
# the concrete trio matches the quiz_attempts.difficulty CHECK (0025,
# extended with 'adaptive' by the #540 migration); 'adaptive' hands the
# per-question mix decision to the agent (A1).


def _load_prompt(name: str) -> str:
    with open(os.path.join(PROMPTS_DIR, name)) as f:
        return f.read()


# ── Wire-format helpers (legacy + agent paths share this shape) ──────────────
#
# `submit_quiz` expects each question dict to look like:
#   {
#     "id": int,
#     "question": str,
#     "options": [{"label": "A"|"B"|..., "text": str, "correct": bool}, ...],
#     "explanation": str,
#     "concept_tested": str,
#     "difficulty": "easy"|"medium"|"hard",
#   }
# This is the format the original quiz_generation.txt prompt produced.
# The agent's QuizQuestion has a flatter shape — we map it back here so the
# stored `questions_json` and the response payload don't change. Frontend
# `submitQuiz`/`scoreQuiz` flows are unaffected.

_OPTION_LABELS = ["A", "B", "C", "D", "E", "F"]

# Rank order for tie-breaking the overall difficulty report — derived from
# the config tuple so a difficulty added there can't be silently dropped by
# _resolved_difficulty's counting.
_DIFFICULTY_RANK = {d: i for i, d in enumerate(CONCRETE_DIFFICULTIES)}


# PostgREST passes `offset` to Postgres as a bigint; anything past this is
# a client bug, and an empty page is a better answer than a 500.
_MAX_HISTORY_OFFSET = 1_000_000


# supabase/config.toml sets PostgREST's max_rows = 1000, and an over-cap
# response is 206 Partial Content — a 2xx, so raise_for_status never fires
# and the truncation is silent. Same constant and same reasoning as
# achievement_service._daily_totals; page to completion or the sum is a lie.
_USAGE_PAGE = 1000


def _daily_spend_exceeded(user_id: str) -> bool:
    """True if this user is past the daily LLM spend ceiling (#544 F1).

    Reads the llm_usage ledger agents/usage.py already writes, PAGED: an
    unpaged read stops at max_rows, so a heavy user's sum plateaus below
    the cap and the guard never trips for exactly the runaway it targets.
    Stops early once the ceiling is crossed — the common case is a couple
    of rows, and a user past the cap doesn't need an exact total.

    Fails OPEN on any error: this is a cost control, not a correctness
    gate, and denying every student because a usage read blipped is worse
    than the spend it would save.
    """
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        spent = 0.0
        offset = 0
        while True:
            rows = table("llm_usage").select(
                "cost_usd",
                filters={"user_id": f"eq.{user_id}", "created_at": f"gte.{since}"},
                limit=_USAGE_PAGE,
                offset=offset,
            ) or []
            spent += sum(float(r.get("cost_usd") or 0.0) for r in rows)
            if spent >= QUIZ_DAILY_SPEND_CAP_USD:
                return True
            if len(rows) < _USAGE_PAGE:
                return False
            offset += _USAGE_PAGE
    except Exception:
        logger.exception("quiz: daily spend check failed user=%s; allowing", user_id)
        return False


def _refund_generate_slot(user_id: str) -> None:
    """Hand back the rate-limit slot a failed generation consumed (#544 F1).

    The slot is claimed BEFORE the model runs (so a burst can't get past
    the gate concurrently), which means a backend failure would otherwise
    spend the student's quota: eight 502s in two minutes would lock them
    out for five with a message saying they'd generated too many quizzes,
    having received none. A failure the student didn't cause shouldn't
    cost them anything, and the 502 explicitly invites a retry.
    """
    try:
        refund_rate_limit(f"quiz_generate:{user_id}")
    except Exception:
        logger.exception("quiz: rate-limit refund failed user=%s", user_id)


def _log_generation_failed(body, request_id: str | None, reason: str) -> None:
    """#544 F3: make a 502 the student saw a 502 an admin can count."""
    events_service.log_event(
        "quiz.generation_failed",
        category="error",
        user_id=body.user_id,
        request_id=request_id,
        payload={
            "concept_node_id": body.concept_node_id,
            "difficulty": body.difficulty,
            "num_questions": body.num_questions,
            "reason": reason,
            # F6: whatever the prompt had managed to assemble before it
            # failed. An ungrounded timeout and a grounded one are different
            # diagnoses, and the failure path is where that matters most.
            **prompt_dimensions.snapshot(),
        },
    )


def _abandon_cutoff() -> datetime:
    return datetime.now(timezone.utc) - timedelta(
        hours=QUIZ_ATTEMPT_ABANDON_TTL_HOURS
    )


def _parse_ts(value) -> datetime | None:
    """Parse a stored timestamp to an AWARE datetime, or None.

    Naive values (an out-of-band write, a hand-edited row) are assumed UTC
    rather than left naive: comparing a naive datetime against an aware one
    raises TypeError, which `except ValueError` around the parse does not
    catch — it would 500 both read endpoints.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _attempt_status(attempt: dict, last_activity_at=None) -> str:
    """#542 D2: status is DERIVED from the timestamps, never stored, so it
    can't drift. An in-progress row past the TTL reads as abandoned even
    before the lazy sweep has stamped abandoned_at.

    `last_activity_at` is the newest recorded answer (quiz_responses):
    a quiz generated days ago but answered minutes ago is being WORKED ON,
    not abandoned — keying the TTL on created_at alone would strand the
    responses already recorded against it.
    """
    if attempt.get("completed_at"):
        return "completed"
    if attempt.get("abandoned_at"):
        return "abandoned"
    cutoff = _abandon_cutoff()
    latest = max(
        (t for t in (_parse_ts(attempt.get("created_at")),
                     _parse_ts(last_activity_at)) if t is not None),
        default=None,
    )
    if latest is not None and latest < cutoff:
        return "abandoned"
    return "in_progress"


def _refuse_if_abandoned(attempt: dict) -> None:
    """409 on an attempt that's been swept as abandoned (#542 D2).

    Checks the STAMP, not the derived TTL: a student mid-quiz whose
    attempt merely crossed the age cutoff keeps working (their answers
    refresh the activity clock — see _attempt_status), but once the sweep
    has actually marked it, the attempt is closed.
    """
    if attempt.get("abandoned_at"):
        raise QuizAPIError(
            status_code=409,
            code=QuizErrorCode.QUIZ_ATTEMPT_ABANDONED,
            message="This quiz expired. Start a new one when you're ready.",
        )


def _sweep_abandoned(user_id: str, *, active_attempt_ids: set[str] | None = None) -> None:
    """Stamp abandoned_at on this user's stale in-progress attempts (#542
    D2). Conditional-update filters arbitrate — same idiom as the submit
    claim — and it runs lazily on the read paths, so no scheduler is
    needed. Best-effort: a failure never breaks the read.

    `active_attempt_ids` are attempts with recent recorded answers, which
    must survive the sweep even though they were created before the
    cutoff — the student is mid-quiz.
    """
    filters = {
        "user_id": f"eq.{user_id}",
        "completed_at": "is.null",
        "abandoned_at": "is.null",
        "created_at": f"lt.{_abandon_cutoff().isoformat()}",
    }
    if active_attempt_ids:
        filters["id"] = f"not.in.({','.join(sorted(active_attempt_ids))})"
    try:
        table("quiz_attempts").update(
            {"abandoned_at": datetime.now(timezone.utc).isoformat()},
            filters=filters,
            # The sweep is a side effect of a READ; without this PostgREST's
            # global Prefer: return=representation drags every swept row
            # back in full — including the encrypted questions_json /
            # answers_json blobs — on each history page load.
            prefer_return_minimal=True,
        )
    except Exception:
        logger.exception("quiz: abandon sweep failed user=%s", user_id)


# The keys a keyless (student-facing) question may carry. An ALLOWLIST,
# not a denylist: `explanation` states the correct answer in prose, and a
# stored row from an older shape can hold the answer under any key at all
# (the rich seed has {"q":..., "a":...}). Anything not listed here never
# reaches a client that hasn't answered yet.
_KEYLESS_QUESTION_KEYS = ("id", "question", "concept_tested", "difficulty")
_KEYLESS_OPTION_KEYS = ("label", "text")


def _is_wire_question(q) -> bool:
    """True if this stored question is in the current wire shape, so
    _strip_answer_key can be trusted to remove everything sensitive."""
    return (
        isinstance(q, dict)
        and isinstance(q.get("options"), list)
        and bool(q.get("options"))
        and all(isinstance(o, dict) and "label" in o for o in q["options"])
    )


def _strip_answer_key(wire_questions: list[dict]) -> list[dict]:
    """The student-facing view of a question: no per-option `correct`
    booleans and no `explanation` (#541 C3, tightened in #542 review).

    Built by allowlist, so a question shape this function doesn't
    recognise can't leak an answer through an unexpected key. Callers must
    gate on _is_wire_question first — an unrecognised shape has no safe
    keyless projection at all.
    """
    stripped = []
    for q in wire_questions:
        q2 = {k: q[k] for k in _KEYLESS_QUESTION_KEYS if k in q}
        q2["options"] = [
            {k: o[k] for k in _KEYLESS_OPTION_KEYS if k in o}
            for o in q.get("options", [])
        ]
        stripped.append(q2)
    return stripped


def _resolved_difficulty(wire_questions: list[dict]) -> str:
    """The overall difficulty generation actually produced (#540 A1).

    Mode of the per-question difficulties; ties break to the harder value
    so the report never understates what the student is about to face.
    Defaults to 'medium' when nothing usable is present (can't happen for
    agent output — QuizQuestion.difficulty is a concrete Literal — but
    this also runs on stored legacy rows).
    """
    counts: dict[str, int] = {}
    for q in wire_questions:
        d = q.get("difficulty")
        if d in _DIFFICULTY_RANK:
            counts[d] = counts.get(d, 0) + 1
    if not counts:
        return "medium"
    return max(counts, key=lambda d: (counts[d], _DIFFICULTY_RANK[d]))


# The wire contract every emitted question must satisfy (#543 E3). The
# agent schema already pins 4 options, but the route is the boundary the
# stored questions_json and every grading path trust, so it validates
# rather than assuming.
_MIN_OPTIONS = 2


def _validate_wire_question(wire: dict) -> bool:
    """True if this wire question is answerable and gradable.

    Rejects: fewer than two options, duplicate option text (the student
    can pick "the same" answer and be wrong), and anything other than
    exactly one correct option (zero = ungradable free point per #129,
    two = the grader's first-match wins silently).
    """
    options = wire.get("options") or []
    qid = wire.get("id")
    if len(options) < _MIN_OPTIONS:
        logger.warning(
            "quiz: dropping question id=%s — only %d option(s)", qid, len(options)
        )
        return False
    # Compare exactly as GRADING does (_agent_question_to_wire matches
    # correct_answer with `text.strip() == canonical`): case-sensitively.
    # Casefolding here would reject items whose options differ only by
    # case — `list` vs `List` is a real question, and one this route
    # graded correctly before the check existed.
    texts = [str(o.get("text", "")).strip() for o in options]
    if len(set(texts)) != len(texts):
        logger.warning("quiz: dropping question id=%s — duplicate option text", qid)
        return False
    n_correct = sum(1 for o in options if o.get("correct"))
    if n_correct != 1:
        logger.warning(
            "quiz: dropping question id=%s — %d correct options (need exactly 1)",
            qid, n_correct,
        )
        return False
    return True


def _agent_question_to_wire(q: QuizQuestion, qid: int) -> dict | None:
    """Map an agent QuizQuestion to the legacy wire-format dict, or
    return None if the question violates the contract.

    The agent must produce `correct_answer` as one of the strings in
    `q.options` verbatim. If that invariant is broken (LLM drift), we
    DROP the question rather than silently mark an arbitrary option
    correct — emitting an unverifiable question to the user is worse
    than a slightly shorter quiz.

    Returning None lets the caller filter questions out cleanly.
    """
    options: list[dict] = []
    matched = False
    canonical = q.correct_answer.strip()
    for i, text in enumerate(q.options[: len(_OPTION_LABELS)]):
        is_correct = (not matched) and (text.strip() == canonical)
        if is_correct:
            matched = True
        options.append({
            "label": _OPTION_LABELS[i],
            "text": text,
            "correct": is_correct,
        })
    if not matched:
        # Generation drift: agent's correct_answer doesn't match any
        # option verbatim. Surface in logs (Logfire span carries the
        # question_id correlation) and drop. Caller filters None.
        #
        # Don't log the raw text — student-content concept names and
        # quiz answers don't belong in stdout/Railway logs. The
        # fingerprint is stable enough to correlate with the same
        # generation drift if it recurs; the full content is still in
        # Logfire spans (where the scrubber from PR #67 controls egress).
        # services.fingerprint.fingerprint joins parts with the ASCII
        # unit-separator (\x1f), so option text containing pipes or
        # other punctuation can't accidentally collide.
        canonical_only = q.correct_answer.strip()
        fp = fingerprint(canonical_only, q.options)
        logger.warning(
            "quiz: dropping question id=%d — correct_answer not found in "
            "options (n_options=%d, canonical_len=%d, fp=%s)",
            qid, len(q.options), len(canonical_only), fp,
        )
        return None
    if not _validate_wire_question({"id": qid, "options": options}):
        return None
    return {
        "id": qid,
        "question": q.question,
        "options": options,
        "explanation": q.explanation,
        "concept_tested": q.concept,
        "difficulty": q.difficulty,
        # E5: stable identity, computed from the same normalized stem +
        # option set every future reader will derive it from. `id` is only
        # unique WITHIN an attempt; this is what survives across attempts
        # (E6's repetition guard) and, later, across students (item stats).
        "question_hash": question_hash(q.question, q.options),
    }


# Keys that exist for the server's benefit and are never part of the client
# contract. `_strip_answer_key`'s allowlist already excludes them on the
# keyless path; this is the same exclusion for the still-default keyed path,
# so provenance can't leak into a browser payload just because #546 hasn't
# flipped `include_answer_key` yet.
#
# `question_hash` sits here too — not because it is sensitive (it is the
# student's own question) but because nothing client-side consumes it yet.
# Per-question feedback (#26) is the change that should surface it, and it
# should do so by adding it to the keyless allowlist, deliberately.
_INTERNAL_QUESTION_KEYS = ("provenance", "question_hash")


def _client_questions(wire_questions: list[dict], include_answer_key: bool) -> list[dict]:
    """The questions as the client may see them."""
    if not include_answer_key:
        return _strip_answer_key(wire_questions)
    return [
        {k: v for k, v in q.items() if k not in _INTERNAL_QUESTION_KEYS}
        for q in wire_questions
    ]


# Per-request model override map. Mirrors the chat tutor's
# fast/smart toggle so quiz body's `model_pref` resolves to the same
# model strings as Learn. None falls through to the agent's
# task-default model from agents/_providers.py::model_for("quiz").
_PREF_MODEL_NAMES: dict[str, str] = {
    "fast": "gemini-2.5-flash-lite",
    "smart": "gemini-2.5-pro",
}


def _resolve_model_pref(model_pref: str | None):
    """Build a GoogleModel override for the per-request fast/smart
    preference, or return None to use the agent's default.

    `google_model` is imported lazily so that constructing a
    GoogleProvider (which reads GEMINI_API_KEY at call time) only
    happens when an override is actually requested — not at module
    import. agents.quiz is already in this route's import graph, so
    this isn't about import-path isolation; it's about deferring the
    one runtime side-effect (the provider build) to the request that
    needs it.
    """
    if not model_pref:
        return None
    from agents._providers import _model_mode, google_model
    if _model_mode() != "real":
        # #391 seam: the per-request fast/smart override must not bypass
        # SAPLING_MODEL_MODE by constructing a live GoogleModel. Same fix as
        # routes/learn.py (#392) — there the browser always sends a pref;
        # the quiz UI does not send one today, but any client that did would
        # silently put live Gemini back in the function-mode path. Fall
        # through to the agent's default model, which model_for("quiz")
        # already built for the active mode.
        return None
    name = _PREF_MODEL_NAMES.get(model_pref)
    if not name:
        return None
    return google_model(name)


def _resolve_bu_code(course_id: str | None) -> str | None:
    """Resolve a Sapling course UUID to its BU course_code (course_chunks
    partition key). None if unresolvable OR if the lookup fails — grounding
    must never break quiz generation."""
    if not course_id:
        return None
    try:
        rows = table("courses").select(
            "course_code", filters={"id": f"eq.{course_id}"}, limit=1
        )
    except Exception:
        return None
    return (rows[0].get("course_code") if rows else None) or None


class CourseMaterial(NamedTuple):
    """What grounding produced for one generation (E5 + E8).

    Before E5 this was a bare string: the chunk ids that grounded a question
    were resolved, formatted into the prompt, and dropped on the floor. That
    made two things impossible — saying which source a stored question came
    from, and telling an ungrounded generation apart from a grounded one.
    """

    #: The assembled prompt text ("" when there is nothing to ground on).
    block: str = ""
    #: Ids of the `course_chunks` rows in `block`, in rank order.
    chunk_ids: tuple[str, ...] = ()
    #: How many chunks are IN the prompt. Tracked separately from
    #: len(chunk_ids) because groundedness is a property of the text the
    #: model saw, not of our ability to name its sources: a row missing an
    #: id still grounded the question, and reporting that generation as
    #: ungrounded would be a lie in the direction that matters.
    k_chunks: int = 0
    #: Whether the official catalog chunk was included.
    has_catalog: bool = False
    #: Total chunks indexed for this course. Resolved ONLY when retrieval
    #: came back empty — it is the difference between "this course has no
    #: material at all" and "it has material, none of it matched this
    #: concept", which are different problems with different fixes. None
    #: means not asked, or the count read failed.
    course_chunks: int | None = None
    #: The BU course_code partition key, or None when unresolvable.
    bu_code: str | None = None

    @property
    def chunk_count(self) -> int:
        """Chunks in the prompt.

        Falls back to the id count so a partially-specified instance can
        never read as ungrounded while visibly carrying sources — the two
        fields disagreeing should be impossible, not merely unlikely.
        """
        return max(self.k_chunks, len(self.chunk_ids))

    @property
    def rag_grounded(self) -> bool:
        """Whether retrieved DOCUMENT chunks are in the prompt.

        Deliberately not named `grounded`: the catalog block is course
        material too, and a course with catalog data but nothing indexed
        does put real material in front of the model. Calling that
        "ungrounded" would write a false record into every stored
        question's provenance — the same class of lie `chunk_count` exists
        to prevent. `has_catalog` carries the other half, and both are
        stamped separately.
        """
        return self.chunk_count > 0


_EMPTY_MATERIAL = CourseMaterial()

# k for concept-scoped retrieval. Named because E8 reports it and the audit's
# proposed budget wants to trim it from 5 to 4 once the numbers are measured
# (F6) rather than estimated.
_RAG_K = 5


def _course_chunk_coverage(bu_code: str) -> int | None:
    """How many chunks are indexed for this course, or None if unknown.

    Cheap: PostgREST's exact count with a one-row window — never pulls the
    table. Only called when retrieval returned nothing, so the common
    (grounded) path pays for no extra query at all.

    A count of 0 is only reported when it is TRUSTWORTHY.
    `select_with_count` returns `total = 0` both for a genuinely empty table
    and for a missing or unparseable `Content-Range` header
    (db/connection.py) — and those two mean opposite things here. Reporting a
    degraded count as 0 would have E8 assert "this course has nothing
    indexed" about a course that may be fully indexed, destroying the exact
    distinction the reason taxonomy exists to draw. So a zero count with rows
    actually returned is treated as unknown.
    """
    try:
        rows, total = table("course_chunks").select_with_count(
            "id", filters={"course_id": f"eq.{bu_code}"}, limit=1,
        )
        if total == 0 and rows:
            logger.warning(
                "quiz: course-chunk count came back 0 while rows exist for "
                "course_code=%s — treating coverage as unknown", bu_code,
            )
            return None
        return total
    except Exception:
        logger.warning(
            "quiz: course-chunk coverage read failed for course_code=%s", bu_code,
        )
        return None


def _course_material(course_id: str | None, concept_name: str) -> CourseMaterial:
    """Best-effort catalog + document-chunk context for a concept.

    Returns an empty CourseMaterial if nothing is available (no course, no
    bu_code, no chunks) or if retrieval raises — grounding must never break
    quiz generation.
    """
    bu_code = _resolve_bu_code(course_id)
    if not bu_code:
        return _EMPTY_MATERIAL
    blocks: list[str] = []
    try:
        catalog = _get_catalog_chunk(bu_code)
    except Exception:
        catalog = ""
    if catalog:
        blocks.append("COURSE CATALOG (official BU course data):\n\n" + catalog)
    try:
        chunks = retrieve_chunks(concept_name, course_id=bu_code, k=_RAG_K)
    except Exception:
        chunks = []
    # Drop any retrieved chunk that merely repeats the catalog block already
    # injected above — catalog chunks share the course_chunks store and can
    # rank into the semantic results, which would send the same
    # course-description text to the model twice (wasted prompt tokens).
    if catalog:
        catalog_norm = catalog.strip()
        chunks = [c for c in chunks if (c.get("chunk_text") or "").strip() != catalog_norm]
    rag_block = format_rag_context(chunks)
    if rag_block:
        blocks.append(rag_block)
    # Ids are what make a stored question traceable back to its source. Rows
    # without one are still usable as prompt text, so they are kept in the
    # block and simply absent from the provenance list.
    chunk_ids = tuple(
        str(c.get("id")) for c in chunks if isinstance(c, dict) and c.get("id")
    )
    return CourseMaterial(
        block="\n\n".join(blocks),
        chunk_ids=chunk_ids,
        k_chunks=len(chunks),
        has_catalog=bool(catalog),
        course_chunks=None if chunks else _course_chunk_coverage(bu_code),
        bu_code=bu_code,
    )


def _log_rag_uncovered(
    material: CourseMaterial,
    *,
    user_id: str,
    concept_node_id: str,
    request_id: str | None,
) -> None:
    """E8: make an ungrounded generation a decision, not an accident.

    Generation is NOT blocked on this — a course with nothing indexed is a
    legitimate mode, and refusing to quiz a student because their class
    hasn't uploaded slides would be worse than a general-knowledge quiz.
    But it stops being invisible: the three reasons below are three
    different problems, and telling them apart is the whole point.
    """
    if material.rag_grounded:
        return
    if material.bu_code is None:
        reason = "course_unresolved"
    elif material.course_chunks is None:
        reason = "coverage_unknown"
    elif material.course_chunks == 0:
        reason = "no_chunks_for_course"
    else:
        reason = "no_match_for_concept"
    # INFO, not WARNING: in function mode the embedding seam is disabled by
    # design (#439), so every E2E generation lands here. A warning per run
    # would train readers to ignore the one that matters.
    logger.info(
        "quiz: generating without course grounding (reason=%s course_chunks=%s "
        "request_id=%s)", reason, material.course_chunks, request_id,
    )
    events_service.log_event(
        "quiz.rag_uncovered",
        # category="usage", NOT "error". Ungrounded generation is a
        # legitimate mode — this event exists to make it countable, not to
        # report a failure — and /api/admin/analytics/errors scans
        # `category = error` newest-first (B re-keyed it off the error.*
        # name prefix precisely so non-HTTP failures would surface). Since
        # this fires on EVERY generation for any unindexed course, and on
        # every function-mode run, filing it as an error would bury
        # quiz.context_write_failed and rag.retrieval_failed under routine
        # traffic and inflate the error series — degrading the surface that
        # workstream B just repaired. `rag.retrieval_failed` stays an error
        # because retrieval FAILING is one; nothing failed here.
        category="usage",
        user_id=user_id,
        request_id=request_id,
        payload={
            "concept_node_id": concept_node_id,
            "reason": reason,
            "course_chunks": material.course_chunks,
            "k_chunks": material.chunk_count,
        },
    )


def _do_not_repeat_block(recent: list[RecentQuestion]) -> str:
    """E6: name the questions this student has already been served.

    Stems, not hashes — "do not repeat 9f3a2c…" is unactionable for a model.
    Neutralized at this boundary because a stem is LLM-written text derived
    from student-uploaded course material, so it re-enters a prompt as
    untrusted content (#150), exactly like the top-up's already-asked list.
    """
    if not recent:
        return ""
    from services.prompt_safety import neutralize_delimiters

    lines = "\n".join(f"- {neutralize_delimiters(r.stem)}" for r in recent)
    return (
        "\n\n[RECENTLY ASKED] This student has already been served the "
        "questions below on this concept. Do NOT repeat them or trivially "
        "reword them — write new questions, on the same concept, that probe "
        "it differently:\n" + lines
    )


async def _quiz_via_agent(
    *,
    user_id: str,
    course_id: str | None,
    concept_node_id: str,
    concept_name: str,
    num_questions: int,
    difficulty: str,
    use_shared_context: bool,
    request_id: str,
    model_pref: str | None = None,
) -> list[dict]:
    """Run quiz_agent and return questions in the legacy wire shape.

    The agent's tools (read_concepts_for_user, read_misconceptions_for_course)
    pull weak-area + class misconception data themselves, replacing the
    manual prompt-string augmentation that used to live in generate_quiz.

    `model_pref` ("fast" or "smart") overrides the agent's default model
    on this single run. Anything else (None, unknown string) falls
    through to model_for("quiz") at agent-construction time.
    """
    deps = SaplingDeps(
        user_id=user_id,
        course_id=course_id,
        supabase=None,
        request_id=request_id,
        feature="quiz",
    )
    # Keep this message routing-only; the workflow + adaptive rules
    # live in the system prompt. We just hand the agent the inputs it
    # needs and trust the prompt to drive tool calls.
    if difficulty == "adaptive":
        # #540 A1: no target difficulty — the agent picks the whole mix
        # from mastery + recent accuracy (ADAPTIVE MODE in the system
        # prompt). Every emitted question still carries a concrete
        # easy|medium|hard; the route reports the overall pick back to
        # the client as `resolved_difficulty`.
        difficulty_clause = (
            f"Generate {num_questions} questions in ADAPTIVE MODE: you "
            f"choose each question's difficulty (easy, medium, or hard) "
            f"from the student's mastery and recent accuracy, per the "
            f"adaptive-mode rules in your system prompt."
        )
    else:
        difficulty_clause = (
            f"Generate {num_questions} {difficulty} questions for the student."
        )
    routing_msg = (
        f"{difficulty_clause} "
        f"The target concept is '{concept_name}' "
        f"(concept_node_id={concept_node_id}). Follow the workflow in your "
        f"system prompt; pass concept_node_id='{concept_node_id}' to "
        f"read_recent_quiz_attempts."
    )
    if use_shared_context:
        routing_msg += (
            " Also call read_misconceptions_for_course and use those misconceptions "
            "as distractors and probes."
        )

    # Course-material grounding does blocking network I/O (a Gemini
    # embedding call, bounded at 60s) plus sync Supabase reads. Run it in a
    # worker thread so a slow/stalled retrieval can't freeze this worker's
    # event loop for every other in-flight request. Matches the
    # asyncio.to_thread pattern used by the agent read tools.
    #
    # E6's recently-asked read is an independent Supabase read + decrypt, so
    # it runs CONCURRENTLY with grounding rather than after it — the two have
    # nothing to say to each other and serializing them would add the slower
    # one's latency to every generation.
    #
    # return_exceptions=True because BOTH are best-effort context, and a bare
    # gather propagates the first failure straight out of generation: an
    # unreadable past attempt would 502 a quiz that needed no history at all.
    # Each helper already degrades internally; this is the backstop for the
    # failure they cannot catch (an unexpected raise on the way in or out).
    material, recent = await asyncio.gather(
        asyncio.to_thread(_course_material, course_id, concept_name),
        asyncio.to_thread(
            recent_question_identities, user_id, concept_node_id
        ),
        return_exceptions=True,
    )
    if isinstance(material, BaseException):
        logger.warning(
            "quiz: course-material assembly failed (%s); generating ungrounded",
            type(material).__name__, exc_info=material,
        )
        material = _EMPTY_MATERIAL
    if isinstance(recent, BaseException):
        logger.warning(
            "quiz: recently-asked read failed (%s); generating without a "
            "do-not-repeat list", type(recent).__name__, exc_info=recent,
        )
        recent = []
    _log_rag_uncovered(
        material,
        user_id=user_id,
        concept_node_id=concept_node_id,
        request_id=request_id,
    )
    routing_msg += _do_not_repeat_block(recent)

    if material.block:
        user_message = (
            "COURSE MATERIAL for '" + concept_name + "':\n\n" + material.block
            + "\n\n[GENERATE QUIZ]\n" + routing_msg
        )
    else:
        user_message = routing_msg

    # F6: what this prompt is made of, so `llm_usage.prompt_tokens` (same
    # request_id) becomes attributable to sections instead of estimated.
    # Recorded BEFORE the run so a failed generation still reports its
    # composition — an ungrounded timeout is a different diagnosis from a
    # grounded one.
    prompt_dimensions.record(
        blocks=sorted(
            b for b, present in (
                ("catalog", material.has_catalog),
                ("rag", material.rag_grounded),
                ("recently_asked", bool(recent)),
                ("misconceptions_requested", use_shared_context),
            ) if present
        ),
        k_chunks=material.chunk_count,
        material_chars=len(material.block),
        recent_asked=len(recent),
        routing_chars=len(routing_msg),
        adaptive=difficulty == "adaptive",
    )

    model_override = _resolve_model_pref(model_pref)
    run_kwargs: dict = {"deps": deps}
    if model_override is not None:
        run_kwargs["model"] = model_override

    async def _run(message: str, limits) -> tuple[Quiz, str]:
        # #544 F2: bound EACH agent run rather than the whole function.
        # Wrapping the outer coroutine cancelled it mid-flight, and
        # CancelledError is a BaseException — it flew straight past the
        # top-up's serve-what-we-have handler and threw away questions the
        # student had already paid for. Timing out one run raises an
        # ordinary TimeoutError the existing handlers can reason about.
        result = record_agent_usage(
            await asyncio.wait_for(
                quiz_agent.run(message, usage_limits=limits, **run_kwargs),
                timeout=QUIZ_GENERATION_TIMEOUT_SEC,
            ),
            feature="quiz", task="quiz", user_id=deps.user_id,
        )
        # Returned per-run, not resolved once for the function: a top-up is
        # a SEPARATE model call and can be served by a different model than
        # the first run (a provider-side reroute, or a future retry that
        # escalates tiers). Stamping one model over all of them would make
        # provenance quietly wrong in exactly the case it exists to record.
        return result.output, served_model_name(result, "quiz")

    # Filter out questions the agent got wrong (correct_answer not among
    # the options, duplicate/insufficient options, no single correct
    # answer) and duplicate stems within this attempt —
    # _agent_question_to_wire returns None for the former,
    # _validate_wire_question backs it. Survivors are re-numbered so
    # question ids stay 1-based and contiguous.
    #
    # `dropped` counts questions we REJECTED, which is a different thing
    # from "fewer than requested": the Quiz schema lets a run return any
    # count, and the E2E seam always returns 3 no matter what was asked.
    # Keying the top-up on under-delivery therefore fired a second full
    # generation on perfectly good responses.
    wire_questions: list[dict] = []
    seen_stems: set[str] = set()
    seen_hashes: set[str] = set()
    dropped = 0

    # E5 provenance shared by every question this generation produces. The
    # chunk ids are attempt-level, not per-item: they are the sources that
    # were in the prompt when the question was written, which is the honest
    # claim — the model never tells us which chunk it drew any single
    # question from.
    provenance_base = {
        "prompt_version": PROMPT_VERSION,
        "chunk_ids": list(material.chunk_ids),
        # Two separate facts, not one fuzzy one: whether retrieved document
        # chunks grounded the question, and whether the official catalog
        # block was present. Collapsing them into a single `grounded` made
        # a catalog-only course record every question as ungrounded.
        "rag_grounded": material.rag_grounded,
        "catalog": material.has_catalog,
    }

    def _absorb(quiz: Quiz, model: str) -> None:
        nonlocal dropped
        for q in quiz.questions:
            # E5: identity is the dedupe key now. The stem check is kept
            # alongside it and is the COARSER of the two — a hash covers the
            # stem AND the options, so a model re-emitting one stem with
            # reworded options passes the hash check and is caught here.
            # Dropping it would have narrowed #543's duplicate-question
            # guard, which is not a trade E5 needs to make.
            stem = normalize_text(q.question)
            qhash = question_hash(q.question, q.options)
            if qhash in seen_hashes or stem in seen_stems:
                logger.warning(
                    "quiz: dropping duplicate question (hash=%s, stem_len=%d)",
                    qhash, len(stem),
                )
                dropped += 1
                continue
            mapped = _agent_question_to_wire(q, len(wire_questions) + 1)
            if mapped is None:
                dropped += 1
                continue
            mapped["provenance"] = {**provenance_base, "model": model}
            seen_stems.add(stem)
            seen_hashes.add(qhash)
            wire_questions.append(mapped)

    _absorb(*await _run(user_message, ORCHESTRATOR_LIMITS))

    # #543 E2: one bounded top-up when DRIFT cost us a big share of the
    # quiz. Gated on questions actually dropped (never on a clean short
    # response), and it runs for total drift too — that's the case a
    # retry most obviously helps, and the old `wire_questions and` guard
    # made it the only case that never retried. Bounded because a retry
    # loop against a drifting model burns tokens without converging.
    if dropped and dropped >= num_questions * QUIZ_TOPUP_DROP_RATIO:
        for _ in range(QUIZ_TOPUP_MAX_RETRIES):
            missing = max(1, num_questions - len(wire_questions))
            logger.info(
                "quiz: topping up after drift (have=%d, dropped=%d, requested=%d)",
                len(wire_questions), dropped, num_questions,
            )
            # Name the stems to avoid: "different from the ones already
            # asked" is unactionable otherwise, and a deterministic model
            # re-emits the same questions, which the dedupe above then
            # discards — a full generation for nothing.
            already = "\n".join(f"- {q['question']}" for q in wire_questions)
            topup_msg = (
                f"{user_message}\n\n[TOP-UP] Some questions were rejected for "
                f"format errors. Generate {missing} MORE questions on the same "
                f"concept. Remember: correct_answer must appear VERBATIM in "
                f"options."
            )
            if already:
                topup_msg += (
                    f"\n\nDo NOT repeat any of these questions, which are "
                    f"already in the quiz:\n{already}"
                )
            try:
                _absorb(*await _run(topup_msg, TOPUP_LIMITS))
            except (Exception, asyncio.TimeoutError) as e:
                # The request deliberately SUCCEEDS from here — serve the
                # short quiz with an honest count. No traceback: the E2E
                # logscan oracle reports those as findings, and this path
                # is a handled degradation, not a bug (same rule the
                # quiz_context seam skip follows).
                logger.warning(
                    "quiz: top-up run failed (%s: %s); serving what we have",
                    type(e).__name__, e,
                )
                break
            if len(wire_questions) >= num_questions:
                break

    if not wire_questions:
        # All questions dropped — raise so generate_quiz's bare-Exception
        # catch degrades to HTTP 502 (the raw-Gemini legacy fallback was
        # retired in #145) rather than serving an empty quiz.
        raise RuntimeError(
            "quiz_agent produced no valid questions after wire-format validation"
        )
    # Never serve more than asked for (a generous top-up run can overshoot).
    return wire_questions[:num_questions]

@router.get("/config")
def quiz_config():
    """Selector options for the quiz UI (#540 A2). Single source of truth:
    the same constants bound the Pydantic request model, so a client that
    builds its selects from this payload can never send a value the route
    rejects. No user data, no auth needed."""
    return quiz_config_payload()


@router.post("/generate")
async def generate_quiz(body: GenerateQuizBody, request: Request):
    require_self(body.user_id, request)
    # The concrete trio is CHECK-constrained on quiz_attempts (0025 +
    # the #540 'adaptive' extension); reject drift before we run the
    # agent or write an attempt row.
    if body.difficulty not in REQUESTED_DIFFICULTIES:
        raise QuizAPIError(
            status_code=400,
            code=QuizErrorCode.QUIZ_DIFFICULTY_INVALID,
            message=(
                "That difficulty isn't available. Choose easy, medium, "
                "hard, or adaptive."
            ),
        )
    node_rows = table("graph_nodes").select(
        "*",
        filters={"id": f"eq.{body.concept_node_id}", "user_id": f"eq.{body.user_id}"},
    )
    if not node_rows:
        raise QuizAPIError(
            status_code=404,
            code=QuizErrorCode.QUIZ_CONCEPT_NOT_FOUND,
            message="We couldn't find that concept in your knowledge graph.",
        )
    node = node_rows[0]
    course_id = node.get("course_id") or None
    concept_name = node.get("concept_name") or ""

    # Unify with the middleware-stamped request ID so agent traces and any
    # downstream error payloads share the same correlation key.
    request_id = (
        getattr(request.state, "request_id", None)
        or current_request_id()
        or str(uuid.uuid4())
    )

    # #544 F1: cost guards run AFTER ownership (a stranger's node 404s
    # first, so probing can't consume a victim's quota) and BEFORE the
    # model call. Neither rejection is a backend failure, so neither emits
    # quiz.generation_failed.
    retry_after = check_rate_limit(
        f"quiz_generate:{body.user_id}",
        limit=QUIZ_GENERATE_RATE_LIMIT,
        window_sec=QUIZ_GENERATE_RATE_WINDOW_SEC,
    )
    if retry_after is not None:
        raise QuizAPIError(
            status_code=429,
            code=QuizErrorCode.QUIZ_RATE_LIMITED,
            message=(
                "You've generated a lot of quizzes just now — "
                "take a moment and try again shortly."
            ),
            headers={"Retry-After": str(retry_after)},
        )
    if _daily_spend_exceeded(body.user_id):
        logger.warning(
            "quiz: daily spend cap reached user=%s request_id=%s",
            body.user_id, request_id,
        )
        raise QuizAPIError(
            status_code=429,
            code=QuizErrorCode.QUIZ_DAILY_LIMIT_REACHED,
            message=(
                "You've reached today's limit for AI-generated study "
                "material. It resets tomorrow."
            ),
        )

    # F6: open the prompt-composition capture for this request. Both the
    # route and the agent's read tools contribute; the snapshot rides into
    # quiz.started, which shares this request_id with the llm_usage row.
    prompt_dimensions.start_capture()

    try:
        # Each agent run inside is individually bounded by
        # QUIZ_GENERATION_TIMEOUT_SEC (see _run) — cancelling the whole
        # coroutine here would discard a partial quiz the top-up handler
        # is designed to serve.
        questions = await _quiz_via_agent(
            user_id=body.user_id,
            course_id=course_id,
            concept_node_id=body.concept_node_id,
            concept_name=concept_name,
            num_questions=body.num_questions,
            difficulty=body.difficulty,
            use_shared_context=body.use_shared_context,
            request_id=request_id,
            model_pref=body.model_pref,
        )
    except HTTPException:
        # The 404 for an unknown concept node is raised before the agent call;
        # never swallow a known HTTP state.
        _refund_generate_slot(body.user_id)
        raise
    except asyncio.TimeoutError as e:
        # #544 F2: distinct from a generic failure — the client can say
        # "that took too long" and offering a retry obviously makes sense.
        # NB: only asyncio.TimeoutError. The builtin TimeoutError is in the
        # OSError family, so catching it too would relabel a transport
        # socket timeout as a wall-clock generation timeout.
        logger.warning(
            "quiz: generation timed out after %ss request_id=%s",
            QUIZ_GENERATION_TIMEOUT_SEC, request_id,
        )
        _refund_generate_slot(body.user_id)
        _log_generation_failed(body, request_id, "timeout")
        raise QuizAPIError(
            status_code=502,
            code=QuizErrorCode.QUIZ_GENERATION_TIMEOUT,
            message="Quiz generation took too long. Please try again.",
        ) from e
    except (UsageLimitExceeded, UnexpectedModelBehavior) as e:
        # The raw-Gemini legacy fallback was retired in #145; degrade to 502
        # rather than serving a quiz from a second LLM path.
        logger.warning("Quiz agent guardrails tripped; returning 502", exc_info=e)
        _refund_generate_slot(body.user_id)
        _log_generation_failed(body, request_id, "agent_guardrail")
        raise QuizAPIError(
            status_code=502,
            code=QuizErrorCode.QUIZ_GENERATION_FAILED,
            message="Quiz generation is temporarily unavailable. Please try again.",
        ) from e
    except Exception as e:
        logger.exception("Unexpected quiz-agent failure; returning 502")
        _refund_generate_slot(body.user_id)
        _log_generation_failed(body, request_id, "agent_error")
        raise QuizAPIError(
            status_code=502,
            code=QuizErrorCode.QUIZ_GENERATION_FAILED,
            message="Quiz generation is temporarily unavailable. Please try again.",
        ) from e

    quiz_id = str(uuid.uuid4())
    table("quiz_attempts").insert({
        "id": quiz_id,
        "user_id": body.user_id,
        "concept_node_id": body.concept_node_id,
        "difficulty": body.difficulty,
        "questions_json": encrypt_json(questions),
    })
    # #117: quiz.started once the attempt row exists. num_questions is the
    # actual generated count (the agent may return fewer than requested).
    events_service.log_event(
        "quiz.started",
        category="usage",
        user_id=body.user_id,
        request_id=request_id,
        payload={
            "quiz_id": quiz_id,
            "concept_node_id": body.concept_node_id,
            "num_questions": len(questions),
            "difficulty": body.difficulty,
            # F6: the prompt's composition, carried on the event that
            # already shares a request_id with this generation's llm_usage
            # row — so prompt_tokens becomes attributable to sections
            # rather than estimated. Ids/counts/enums only, per the #117
            # payload rule; no prompt text goes anywhere near this.
            **prompt_dimensions.snapshot(),
        },
    )
    prompt_dimensions.clear()
    # #541 C3: the answer key (per-option `correct` booleans) ships to the
    # client only behind the deprecated include_answer_key flag — default
    # true for the current QuizPanel, removed with #546 once the #537
    # client grades via /attempts/{id}/answer. Log every keyed response so
    # zero-usage is observable before the default flips.
    if body.include_answer_key:
        logger.info(
            "quiz: generate served the client-side answer key "
            "(include_answer_key=true, deprecated — #546) quiz_id=%s", quiz_id,
        )
    response_questions = _client_questions(questions, body.include_answer_key)

    # #540 A1: echo what generation actually chose. requested_difficulty
    # is what the student asked for (may be 'adaptive');
    # resolved_difficulty is the overall mix the agent produced (always
    # concrete) — so the client can say "we picked hard for you" instead
    # of repeating the request back.
    return {
        "quiz_id": quiz_id,
        "questions": response_questions,
        "requested_difficulty": body.difficulty,
        "resolved_difficulty": _resolved_difficulty(questions),
        # #543 E2: never silently short-change a quiz. Drift (and the
        # bounded top-up) can leave fewer questions than asked for; the
        # client can now say so instead of pretending this is what was
        # requested.
        "requested_count": body.num_questions,
        "delivered_count": len(questions),
    }


@router.get("/attempts")
def list_attempts(
    request: Request,
    user_id: str,
    limit: int = 20,
    offset: int = 0,
):
    """#542 D4: paginated attempt history for the signed-in user — the
    plaintext scalars (#521/#527) finally get their reader. No question
    payloads here (and therefore no answer keys)."""
    require_self(user_id, request)
    limit = max(1, min(limit, 100))
    # Clamp BOTH ends: an unbounded offset is stringified into PostgREST's
    # offset param and Postgres rejects it as bigint-out-of-range — a 500
    # where an empty page is the honest answer.
    offset = max(0, min(offset, _MAX_HISTORY_OFFSET))
    # Lazy lifecycle sweep (#542 D2) — the read paths keep statuses honest.
    _sweep_abandoned(user_id)

    rows, total = table("quiz_attempts").select_with_count(
        "id,concept_node_id,difficulty,score,total,mastery_before,"
        "mastery_after,completed_at,abandoned_at,created_at",
        filters={"user_id": f"eq.{user_id}"},
        # `id` is the unique tiebreaker: without it two attempts sharing a
        # created_at have undefined relative order across the separate
        # queries serving page N and N+1, so a row can repeat or vanish.
        # Same idiom as routes/gamification.py's xp_events paging.
        order="created_at.desc,id.desc",
        limit=limit,
        offset=offset,
    )
    rows = rows or []

    node_ids = sorted({r["concept_node_id"] for r in rows if r.get("concept_node_id")})
    nodes: dict[str, dict] = {}
    if node_ids:
        node_rows = table("graph_nodes").select(
            "id,concept_name,course_id",
            filters={"id": f"in.({','.join(node_ids)})", "user_id": f"eq.{user_id}"},
        ) or []
        nodes = {n["id"]: n for n in node_rows}

    attempts = []
    for r in rows:
        node = nodes.get(r.get("concept_node_id")) or {}
        before, after = r.get("mastery_before"), r.get("mastery_after")
        delta = round(after - before, 4) if before is not None and after is not None else None
        attempts.append({
            "quiz_id": r["id"],
            "status": _attempt_status(r),
            "concept_node_id": r.get("concept_node_id"),
            "concept_name": node.get("concept_name"),
            "course_id": node.get("course_id"),
            "score": r.get("score"),
            "total": r.get("total"),
            "difficulty": r.get("difficulty"),
            "mastery_before": before,
            "mastery_after": after,
            "mastery_delta": delta,
            "created_at": r.get("created_at"),
            "completed_at": r.get("completed_at"),
        })
    return {"total": total, "attempts": attempts, "limit": limit, "offset": offset}


@router.get("/attempts/{attempt_id}")
def get_attempt(attempt_id: str, request: Request):
    """#542 D2: resume state for one attempt — enough to rebuild an
    in-progress quiz client-side: questions WITHOUT the answer key, plus
    the responses already recorded through /answer."""
    attempt_rows = table("quiz_attempts").select(
        "*", filters={"id": f"eq.{attempt_id}"}
    )
    if not attempt_rows:
        raise QuizAPIError(
            status_code=404,
            code=QuizErrorCode.QUIZ_ATTEMPT_NOT_FOUND,
            message="We couldn't find that quiz.",
        )
    attempt = attempt_rows[0]
    require_self(attempt["user_id"], request)

    responses = table("quiz_responses").select(
        "question_index,selected_index,is_correct,time_ms,confidence,answered_at",
        filters={"attempt_id": f"eq.{attempt_id}"},
        order="question_index.asc",
    ) or []
    last_activity = max(
        (r.get("answered_at") for r in responses if r.get("answered_at")),
        default=None,
    )
    status = _attempt_status(attempt, last_activity_at=last_activity)
    # Answering keeps an attempt alive, so exempt it from the sweep.
    _sweep_abandoned(
        attempt["user_id"],
        active_attempt_ids={attempt_id} if status == "in_progress" else None,
    )

    questions = decrypt_json_column(attempt["questions_json"]) or []
    if questions and not all(_is_wire_question(q) for q in questions):
        # A stored shape this code doesn't recognise has no safe keyless
        # projection — passing it through would ship whatever key it holds
        # (legacy rows store the answer under `a`). Refuse the resume.
        logger.warning(
            "quiz: attempt %s stores questions in an unrecognised shape; "
            "refusing to resume", attempt_id,
        )
        raise QuizAPIError(
            status_code=409,
            code=QuizErrorCode.QUIZ_ATTEMPT_NOT_RESUMABLE,
            message="This quiz can't be resumed. Start a new one.",
        )
    # Only an in-progress attempt hands back questions: a completed or
    # abandoned one would otherwise let a client keep answering (the write
    # paths refuse it, but there's no reason to ship the payload at all).
    resumable = status == "in_progress"
    return {
        "quiz_id": attempt["id"],
        "status": status,
        "resumable": resumable,
        "difficulty": attempt.get("difficulty"),
        "concept_node_id": attempt.get("concept_node_id"),
        "questions": _strip_answer_key(questions) if resumable else [],
        "responses": responses,
        "score": attempt.get("score"),
        "total": attempt.get("total"),
        "mastery_before": attempt.get("mastery_before"),
        "mastery_after": attempt.get("mastery_after"),
        "created_at": attempt.get("created_at"),
        "completed_at": attempt.get("completed_at"),
    }


@router.post("/attempts/{attempt_id}/answer")
def answer_question(attempt_id: str, body: AnswerQuestionBody, request: Request):
    """#541 C1: grade one question server-side and record the response.

    Idempotent on (attempt_id, question_index): re-answering returns the
    FIRST recorded response (`recorded: false` marks the replay) rather
    than overwriting — no revision, decided for the #537 revamp flow.
    """
    attempt_rows = table("quiz_attempts").select(
        "*", filters={"id": f"eq.{attempt_id}"}
    )
    if not attempt_rows:
        raise QuizAPIError(
            status_code=404,
            code=QuizErrorCode.QUIZ_ATTEMPT_NOT_FOUND,
            message="We couldn't find that quiz.",
        )
    attempt = attempt_rows[0]
    require_self(attempt["user_id"], request)

    if attempt.get("completed_at"):
        raise QuizAPIError(
            status_code=409,
            code=QuizErrorCode.QUIZ_ATTEMPT_ALREADY_COMPLETED,
            message="This quiz has already been submitted.",
        )
    _refuse_if_abandoned(attempt)

    questions = decrypt_json_column(attempt["questions_json"]) or []
    if body.question_index >= len(questions):
        raise QuizAPIError(
            status_code=400,
            code=QuizErrorCode.QUIZ_QUESTION_INVALID,
            message="That question isn't part of this quiz.",
        )
    question = questions[body.question_index]
    options = question.get("options", [])
    if body.selected_index >= len(options):
        raise QuizAPIError(
            status_code=400,
            code=QuizErrorCode.QUIZ_QUESTION_INVALID,
            message="That answer choice isn't part of this question.",
        )
    # Wire ids are 1-based, question_index is 0-based. When the client sends
    # both, they must agree — otherwise passing the displayed id as the index
    # silently grades the NEXT question and idempotency locks that in.
    if body.question_id is not None and body.question_id != question.get("id"):
        raise QuizAPIError(
            status_code=400,
            code=QuizErrorCode.QUIZ_QUESTION_INVALID,
            message="That answer doesn't match the question it was sent for.",
        )

    # The correct option is a property of the question, not of the answer —
    # resolve it once. -1 means a malformed item with no correct option,
    # which must never grade correct (same rule as submit's #129 fix).
    correct_index = next(
        (i for i, o in enumerate(options) if o.get("correct")), -1
    )

    def _is_correct(selected_index: int) -> bool:
        return correct_index >= 0 and correct_index == selected_index

    recorded = True
    response_row = None
    existing = table("quiz_responses").select(
        "*",
        filters={
            "attempt_id": f"eq.{attempt_id}",
            "question_index": f"eq.{body.question_index}",
        },
    )
    if existing:
        recorded = False
        response_row = existing[0]
    else:
        row = {
            "attempt_id": attempt_id,
            "question_index": body.question_index,
            "selected_index": body.selected_index,
            "is_correct": _is_correct(body.selected_index),
            "time_ms": body.time_ms,
            "confidence": body.confidence,
        }
        try:
            table("quiz_responses").insert(row)
            response_row = row
        except Exception:
            # Lost a race with a concurrent answer for the same index — the
            # UNIQUE arbitrates; return whatever won.
            recorded = False
            raced = table("quiz_responses").select(
                "*",
                filters={
                    "attempt_id": f"eq.{attempt_id}",
                    "question_index": f"eq.{body.question_index}",
                },
            )
            if not raced:
                raise
            response_row = raced[0]

    next_index = body.question_index + 1
    next_question = (
        _strip_answer_key([questions[next_index]])[0]
        if next_index < len(questions)
        else None
    )
    return {
        # Echo both addressing schemes so a client that mixed them up sees
        # it immediately rather than discovering it at submit time.
        "question_index": body.question_index,
        "question_id": question.get("id"),
        "is_correct": _is_correct(response_row["selected_index"]),
        "correct_index": correct_index,
        "explanation": question.get("explanation", ""),
        "next_question": next_question,
        "recorded": recorded,
    }


@router.post("/submit")
def submit_quiz(body: SubmitQuizBody, background_tasks: BackgroundTasks, request: Request):
    attempt_rows = table("quiz_attempts").select("*", filters={"id": f"eq.{body.quiz_id}"})
    if not attempt_rows:
        raise QuizAPIError(
            status_code=404,
            code=QuizErrorCode.QUIZ_ATTEMPT_NOT_FOUND,
            message="We couldn't find that quiz.",
        )
    attempt = attempt_rows[0]

    user_id = attempt["user_id"]
    require_self(user_id, request)

    # #521: ciphertext str for new rows, plaintext JSONB for pre-backfill rows.
    questions = decrypt_json_column(attempt["questions_json"])

    # #129: completed_at is written on the first successful submit. A re-POST
    # of the same quiz_id must not re-run apply_graph_update (double mastery
    # delta + duplicate node_mastery_events row + streak bump), the background
    # quiz-context task, or achievements. 409 rather than replaying the original
    # 200: quiz_attempts stores no mastery_before/after, so faithfully
    # reconstructing the first response would need a migration.
    if attempt.get("completed_at"):
        raise QuizAPIError(
            status_code=409,
            code=QuizErrorCode.QUIZ_ATTEMPT_ALREADY_COMPLETED,
            message="This quiz has already been submitted.",
        )
    # An abandoned attempt must not pay out mastery, XP or achievements —
    # otherwise the TTL is a label and the sweep enforces nothing.
    _refuse_if_abandoned(attempt)
    # The read above is only the fast path — two CONCURRENT submits (a
    # double-click on the final submit) would both pass it. The atomic claim
    # below (conditional update on completed_at IS NULL, PR #464 review) is
    # the real gate: exactly one request wins the row; the loser 409s before
    # any mastery write. A crash after the claim leaves the attempt
    # completed-but-scoreless (retry 409s) — strictly safer than double
    # mastery. The final update further down fills score/total/answers_json.
    claimed = table("quiz_attempts").update(
        {"completed_at": datetime.now(timezone.utc).isoformat()},
        filters={"id": f"eq.{body.quiz_id}", "completed_at": "is.null"},
    )
    if not claimed:
        raise QuizAPIError(
            status_code=409,
            code=QuizErrorCode.QUIZ_ATTEMPT_ALREADY_COMPLETED,
            message="This quiz has already been submitted.",
        )

    concept_node_id = attempt["concept_node_id"]

    # #541 C4: responses recorded through /attempts/{id}/answer are the
    # source of truth — a payload answer for the same question is ignored
    # (the recorded response was graded at answer time; letting the final
    # POST override it would reopen the client-side-grading hole C exists
    # to close). Questions never answered through C1 fall back to the
    # submitted payload, so the current all-at-the-end client keeps working.
    recorded_rows = table("quiz_responses").select(
        "question_index,selected_index",
        filters={"attempt_id": f"eq.{body.quiz_id}"},
    ) or []
    recorded_by_index = {r["question_index"]: r for r in recorded_rows}

    answer_map = {str(a.question_id): a.selected_label for a in body.answers}
    results = []
    # The reconciled answer set — what was ACTUALLY graded, which is what
    # answers_json must persist. Storing the raw payload instead left a
    # recorded-only submit with a full score beside an empty answer list,
    # and a contradicted payload answer stored despite losing to the
    # recorded response.
    graded_answers: list[dict] = []
    score = 0
    for q_index, q in enumerate(questions):
        qid = str(q["id"])
        recorded = recorded_by_index.get(q_index)
        if recorded is not None:
            sel_idx = recorded.get("selected_index")
            options = q.get("options", [])
            selected = (
                options[sel_idx]["label"]
                if isinstance(sel_idx, int) and 0 <= sel_idx < len(options)
                else ""
            )
        else:
            selected = answer_map.get(qid, "")
        if selected:
            graded_answers.append({
                "question_id": q["id"],
                "selected_label": selected,
            })
        correct_opt = next((o for o in q["options"] if o.get("correct")), None)
        correct_label = correct_opt["label"] if correct_opt else ""
        # #129: a malformed item with NO correct option must never grade as
        # correct — '' == '' would otherwise hand a free point whenever the
        # answer is also missing.
        is_correct = bool(correct_opt) and selected == correct_label
        if is_correct:
            score += 1
        results.append({
            "question_id": qid,
            "selected": selected,
            "correct": is_correct,
            "correct_answer": correct_label,
            "explanation": q.get("explanation", ""),
        })

    total = len(questions)

    # Owner-scoped read: the attempt's concept node must belong to the
    # attempt's owner. A missing/foreign node means we'd otherwise write
    # mastery to someone else's row (IDOR) — refuse before any write.
    # mastery_events was DROPPED in 0023 (events moved to node_mastery_events);
    # we no longer read or write that column here.
    node_rows = table("graph_nodes").select(
        "concept_name,mastery_score,course_id",
        filters={"id": f"eq.{concept_node_id}", "user_id": f"eq.{user_id}"},
    )
    if not node_rows:
        raise QuizAPIError(
            status_code=404,
            code=QuizErrorCode.QUIZ_CONCEPT_NOT_FOUND,
            message="We couldn't find that concept in your knowledge graph.",
        )
    node = node_rows[0]
    mastery_before = node["mastery_score"]
    # #543 E1: the model is a named seam now (services/quiz_config.py).
    # The numbers are unchanged — see docs/quiz-mastery-model.md for the
    # options the revamp gets to choose from.
    mastery_score_after = mastery_after(mastery_before, score=score, total=total)
    mastery_delta = mastery_score_after - mastery_before

    score_ratio = score / total if total > 0 else 0.0
    if score_ratio >= 0.7:
        event_type = "correct"
    elif score_ratio >= 0.4:
        event_type = "partial"
    else:
        event_type = "confusion"

    # Route the mastery write through the sanctioned graph path. The graph
    # keys on the ABSTRACT course id; apply_graph_update looks the node up by
    # (normalized) concept_name within (user_id, course_id), clamps mastery,
    # bumps times_studied/last_studied_at, records the event (now in
    # node_mastery_events), and updates the streak. We don't touch graph_nodes
    # or node_mastery_events directly — that's the graph slice's territory.
    applied = apply_graph_update(
        user_id,
        {
            "updated_nodes": [
                {
                    "concept_name": node["concept_name"],
                    "mastery_delta": mastery_delta,
                    "reason": f"Quiz: {score}/{total} correct",
                    "event_type": event_type,
                }
            ]
        },
        course_id=node.get("course_id"),
    )
    # #542 D1 (review): persist what the GRAPH actually wrote, not what we
    # predicted. apply_graph_update owns the write — it resolves the node by
    # normalized concept name and clamps the result — so its reported
    # before/after is the only value that can't disagree with graph_nodes.
    # Falls back to the local computation if the call returned nothing
    # recognisable (it degrades rather than raising).
    for change in applied or []:
        if isinstance(change, dict) and change.get("after") is not None:
            mastery_before = change.get("before", mastery_before)
            # NB: mastery_after is the imported model function (#543 E1);
            # the value lives in mastery_score_after.
            mastery_score_after = change["after"]
            mastery_delta = mastery_score_after - mastery_before
            break

    table("quiz_attempts").update(
        {
            "score": score,
            "total": total,
            # The reconciled set (recorded responses winning over payload),
            # not the raw request — the attempt's stored answers must agree
            # with the score computed from them.
            "answers_json": encrypt_json(graded_answers),
            # #542 D1: the mastery snapshot — without it a replayed/audited
            # submit can't reconstruct what the student saw, and history
            # can't show progression. Plaintext scalars (#521 rationale).
            "mastery_before": mastery_before,
            "mastery_after": mastery_score_after,
            # completed_at was already stamped by the atomic claim above.
        },
        filters={"id": f"eq.{body.quiz_id}"},
    )

    node2_rows = table("graph_nodes").select(
        "concept_name",
        filters={"id": f"eq.{concept_node_id}", "user_id": f"eq.{user_id}"},
    )
    concept_name = node2_rows[0]["concept_name"] if node2_rows else "Unknown"
    # Display name lives on user_profiles (0024); resolve + decrypt via helper.
    student_name = get_display_name(user_id) or "Student"

    existing_ctx = get_quiz_context(user_id, concept_node_id)
    ctx_prompt = (
        _load_prompt("quiz_context_update.txt")
        .replace("{concept_name}", concept_name)
        .replace("{student_name}", student_name)
        .replace("{existing_quiz_context_json}", json.dumps(existing_ctx) if existing_ctx else "{}")
        .replace("{score}", str(score))
        .replace("{total}", str(total))
        .replace("{quiz_results_json}", json.dumps(results, indent=2))
    )

    # Correlate the background write with this request's trace.
    ctx_request_id = getattr(request.state, "request_id", None) or current_request_id()

    def _update_context(prompt: str, uid: str, node_id: str, quiz_id: str,
                        request_id: str | None):
        # #529/B3: this write was `except Exception: pass` for months while
        # every attempt 42P10'd — the adaptive loop died silently. Failures
        # are loud now: ERROR log with the attempt id + request id, a
        # `quiz.context_write_failed` analytics event, and a re-raise in
        # local/test envs so a regression fails CI instead of going quiet.
        try:
            result = record_agent_usage(
                run_agent_sync(quiz_context_agent.run(prompt)),
                feature="quiz", task="quiz_context", user_id=uid,
            )
            save_quiz_context(uid, node_id, result.output.model_dump())
        except UnregisteredHandlerError:
            # E2E function mode leaves quiz_context deliberately
            # unregistered (agents/function_handlers_e2e.py) so no
            # post-response DB write races the next test's re-seed. One
            # WARNING, no traceback: the logscan oracle reports tracebacks.
            logger.warning(
                "quiz: context update skipped — quiz_context handler "
                "unregistered (function-mode seam) quiz_id=%s", quiz_id,
            )
        except Exception:
            logger.exception(
                "quiz: context update failed quiz_id=%s concept=%s "
                "request_id=%s", quiz_id, node_id, request_id,
            )
            events_service.log_event(
                "quiz.context_write_failed",
                category="error",
                user_id=uid,
                request_id=request_id,
                payload={"quiz_id": quiz_id, "concept_node_id": node_id},
            )
            if config.IS_LOCAL:
                raise

    background_tasks.add_task(
        _update_context, ctx_prompt, user_id, concept_node_id,
        body.quiz_id, ctx_request_id,
    )

    # XP + achievements: after the attempt row (score/total/answers_json) is
    # persisted above (the atomic completed_at claim + the update at :486-494
    # together gate this to exactly one successful submit per attempt id;
    # a replay 409s before reaching here). source_id=body.quiz_id is the
    # attempt id, so a hypothetical double-invocation is a no-op via the
    # xp_events idempotency key rather than a double payout.
    award_xp_safe(user_id, "quiz_completed", source_type="quiz", source_id=body.quiz_id)

    # Check for achievements after quiz completion
    try:
        from services.achievement_service import check_achievements
        check_achievements(user_id, "quizzes_completed", {})
    except Exception:
        pass

    # #117: quiz.completed on the success path only — a 409 replay (the
    # atomic completed_at claim above) or any earlier 4xx never reaches here.
    events_service.log_event(
        "quiz.completed",
        category="usage",
        user_id=user_id,
        payload={
            "quiz_id": body.quiz_id,
            "concept_node_id": concept_node_id,
            "score": score,
            "total": total,
            "mastery_delta": mastery_delta,
        },
    )

    return {
        "score": score,
        "total": total,
        "mastery_before": mastery_before,
        "mastery_after": mastery_score_after,
        "results": results,
    }
