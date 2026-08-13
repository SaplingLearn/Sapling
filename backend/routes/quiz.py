import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from pydantic_ai.exceptions import UsageLimitExceeded, UnexpectedModelBehavior

import config
from agents import ORCHESTRATOR_LIMITS
from agents._providers import UnregisteredHandlerError
from agents.quiz import quiz_agent, Quiz, QuizQuestion
from agents.deps import SaplingDeps
from agents._run import run_agent_sync
from agents.quiz_context import quiz_context_agent
from agents.usage import record_agent_usage
from db.connection import table
from models import AnswerQuestionBody, GenerateQuizBody, SubmitQuizBody
from routes.learn import _get_catalog_chunk
from services import events_service
from services.auth_guard import require_self
from services.quiz_config import (
    CONCRETE_DIFFICULTIES,
    REQUESTED_DIFFICULTIES,
    quiz_config_payload,
)
from services.quiz_errors import QuizAPIError, QuizErrorCode
from services.profiles import get_display_name
from services.encryption import encrypt_json, decrypt_json_column
from services.graph_service import apply_graph_update
from services.quiz_context_service import get_quiz_context, save_quiz_context
from services.fingerprint import fingerprint
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


def _strip_answer_key(wire_questions: list[dict]) -> list[dict]:
    """Deep-enough copy of the wire questions without per-option `correct`
    booleans (#541 C3). Storage always keeps the key — grading is
    server-side; only the RESPONSE is stripped."""
    stripped = []
    for q in wire_questions:
        q2 = dict(q)
        q2["options"] = [
            {k: v for k, v in o.items() if k != "correct"}
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
    return {
        "id": qid,
        "question": q.question,
        "options": options,
        "explanation": q.explanation,
        "concept_tested": q.concept,
        "difficulty": q.difficulty,
    }


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


def _course_material_block(course_id: str | None, concept_name: str) -> str:
    """Best-effort catalog + document-chunk context for a concept.

    Returns "" if nothing is available (no course, no bu_code, no chunks) or
    if retrieval raises — grounding must never break quiz generation.
    """
    bu_code = _resolve_bu_code(course_id)
    if not bu_code:
        return ""
    blocks: list[str] = []
    try:
        catalog = _get_catalog_chunk(bu_code)
    except Exception:
        catalog = ""
    if catalog:
        blocks.append("COURSE CATALOG (official BU course data):\n\n" + catalog)
    try:
        chunks = retrieve_chunks(concept_name, course_id=bu_code, k=5)
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
    return "\n\n".join(blocks)


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
    material = await asyncio.to_thread(_course_material_block, course_id, concept_name)
    if material:
        user_message = (
            "COURSE MATERIAL for '" + concept_name + "':\n\n" + material
            + "\n\n[GENERATE QUIZ]\n" + routing_msg
        )
    else:
        user_message = routing_msg

    model_override = _resolve_model_pref(model_pref)
    run_kwargs: dict = {"deps": deps, "usage_limits": ORCHESTRATOR_LIMITS}
    if model_override is not None:
        run_kwargs["model"] = model_override
    result = record_agent_usage(
        await quiz_agent.run(user_message, **run_kwargs),
        feature="quiz", task="quiz", user_id=deps.user_id,
    )
    quiz: Quiz = result.output
    # Filter out questions where the agent's correct_answer didn't match
    # any option verbatim — _agent_question_to_wire returns None for those.
    # Re-number the survivors so question IDs stay 1-based and contiguous.
    wire_questions: list[dict] = []
    for q in quiz.questions:
        mapped = _agent_question_to_wire(q, len(wire_questions) + 1)
        if mapped is not None:
            wire_questions.append(mapped)
    if not wire_questions:
        # All questions dropped — raise so generate_quiz's bare-Exception
        # catch degrades to HTTP 502 (the raw-Gemini legacy fallback was
        # retired in #145) rather than serving an empty quiz.
        raise RuntimeError(
            "quiz_agent produced no valid questions after wire-format validation"
        )
    return wire_questions

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

    try:
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
        raise
    except (UsageLimitExceeded, UnexpectedModelBehavior) as e:
        # The raw-Gemini legacy fallback was retired in #145; degrade to 502
        # rather than serving a quiz from a second LLM path.
        logger.warning("Quiz agent guardrails tripped; returning 502", exc_info=e)
        raise QuizAPIError(
            status_code=502,
            code=QuizErrorCode.QUIZ_GENERATION_FAILED,
            message="Quiz generation is temporarily unavailable. Please try again.",
        ) from e
    except Exception as e:
        logger.exception("Unexpected quiz-agent failure; returning 502")
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
        },
    )
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
        response_questions = questions
    else:
        response_questions = _strip_answer_key(questions)

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
    mastery_after = max(0.0, min(1.0, mastery_before + (score * 0.03) - ((total - score) * 0.02)))
    mastery_delta = mastery_after - mastery_before

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
    apply_graph_update(
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

    table("quiz_attempts").update(
        {
            "score": score,
            "total": total,
            # The reconciled set (recorded responses winning over payload),
            # not the raw request — the attempt's stored answers must agree
            # with the score computed from them.
            "answers_json": encrypt_json(graded_answers),
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
        "mastery_after": mastery_after,
        "results": results,
    }
