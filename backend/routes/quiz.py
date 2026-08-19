import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from pydantic_ai.exceptions import UsageLimitExceeded, UnexpectedModelBehavior

from agents import ORCHESTRATOR_LIMITS
from agents.quiz import (
    quiz_agent, Quiz, QuizQuestion, conceptual_allowance, quiz_ask_size,
    resolve_correct_index,
)
from agents.deps import SaplingDeps
from agents._run import run_agent_sync
from agents.quiz_context import quiz_context_agent
from agents.usage import record_agent_usage
from db.connection import table
from models import GenerateQuizBody, SubmitQuizBody
from routes.learn import _get_catalog_chunk
from services import events_service
from services.auth_guard import require_self
from services.profiles import get_display_name
from services.graph_service import apply_graph_update
from services.quiz_context_service import get_quiz_context, save_quiz_context
from services.fingerprint import fingerprint
from services.rag_service import retrieve_chunks, format_rag_context
from services.request_context import current_request_id

logger = logging.getLogger(__name__)

router = APIRouter()

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")

# quiz_attempts.difficulty CHECK enum (0025).
VALID_DIFFICULTIES = {"easy", "medium", "hard"}


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



def _agent_question_to_wire(q: QuizQuestion, qid: int) -> dict | None:
    """Map an agent QuizQuestion to the legacy wire-format dict, or
    return None if the question violates the contract.

    The agent must produce `correct_answer` as one of the strings in
    `q.options`. `_resolve_correct_index` decides which one, tolerating
    retyping slips but refusing to guess between two plausible options.
    When it can't tell, we DROP the question rather than silently mark an
    arbitrary option correct — emitting an unverifiable question to the
    user is worse than a slightly shorter quiz.

    Returning None lets the caller filter questions out cleanly.
    """
    texts = q.options[: len(_OPTION_LABELS)]
    correct_i = resolve_correct_index(q.correct_answer, texts)
    options: list[dict] = [
        {"label": _OPTION_LABELS[i], "text": text, "correct": i == correct_i}
        for i, text in enumerate(texts)
    ]
    if correct_i is None:
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


# The model the guardrail retry escalates to. Deliberately NOT
# _PREF_MODEL_NAMES["fast"]: that resolves to gemini-2.5-flash-lite, which is
# also this route's DEFAULT model (agents/_providers.py::_DEFAULTS["quiz"]),
# so a "retry on a different model" built from it re-ran the identical payload
# on the identical model — measured, two ~140s failures back to back instead
# of one, then the same 502 either way. gemini-2.5-flash is the smallest
# genuine change: it leaves the failing input behind without paying Pro's
# latency on a path the student is already waiting on.
_FALLBACK_MODEL_NAME = "gemini-2.5-flash"

# Gemini 2.5 Pro always thinks — thinking_budget=0 is rejected outright (the
# same asymmetry agents/flashcard.py records: "Flash accepts thinking_budget=0
# (unlike Pro)"). 2048 is the cap routes/learn.py applies to the Pro chat
# tutor: enough for a real chain of thought, not enough latency to feel.
_PRO_THINKING_BUDGET = 2048


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


def _resolve_fallback_model():
    """Build the guardrail-retry model, or None when there is nothing to
    escalate to.

    Same SAPLING_MODEL_MODE seam as `_resolve_model_pref` (#391): outside real
    mode there is no live GoogleModel to construct, so the route simply gets
    no second attempt rather than dialing Gemini from a function-mode test.
    """
    from agents._providers import _model_mode, google_model
    if _model_mode() != "real":
        return None
    return google_model(_FALLBACK_MODEL_NAME)


def _effective_model_name(model_override) -> str:
    """The model name a run will actually use, given its `model=` override.

    None means no override, so the run lands on the agent's own task-default
    model — whose configured name `model_name_for("quiz")` reports, env
    override included. Used both to pick per-run model settings and to log the
    model a retry really escalates to, so neither can name a model the run
    isn't using.
    """
    from agents._providers import model_name_for
    return getattr(model_override, "model_name", None) or model_name_for("quiz")


def _build_quiz_model_settings(model_name: str):
    """Thinking config for ONE quiz run, chosen for the model that run uses.

    This cannot live on the agent, and agents/quiz.py says why: agent-level
    model_settings apply to EVERY run, including the `model_pref="smart"` run
    whose `model=` kwarg is gemini-2.5-pro, and Pro 400s on a zero budget.
    Same split as agents/chat_tutor.py + routes/learn.py, where one agent
    instance also serves both tiers.

    flash-lite and flash accept thinking_budget=0, and switching thinking off
    is what took quiz generation from runs of 361s that ended as a 502 down to
    ~18s — so those keep it off, and only a Pro run gets a budget.

    Imported lazily for the same reason as `google_model`: keeps the
    GoogleProvider construction off this module's import path.
    """
    from google.genai.types import ThinkingConfig
    from pydantic_ai.models.google import GoogleModelSettings
    # Substring, not equality: the point is "does this model refuse a zero
    # budget", which is a property of the Pro tier rather than of one version
    # string, and SAPLING_MODEL_QUIZ can name a Pro model directly.
    budget = _PRO_THINKING_BUDGET if "pro" in model_name else 0
    return GoogleModelSettings(
        google_thinking_config=ThinkingConfig(thinking_budget=budget)
    )


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
        # Read by quiz_agent's _select_requested_quiz output validator, which
        # trims the over-generated surplus back to this count (preferring
        # worked problems as it does). Without it the count is prompt-only,
        # and the model under-delivers (asked 10, returned 6) with nothing
        # to catch it.
        num_questions=num_questions,
    )
    # Keep this message routing-only; the workflow + adaptive rules
    # live in the system prompt. We just hand the agent the inputs it
    # needs and trust the prompt to drive tool calls.
    # Ask for MORE than the student wants. quiz_agent's output validator
    # then selects `num_questions` from them, preferring worked problems and
    # dropping unanswerable ones. The ratio used to be enforced by bouncing
    # a non-compliant quiz back with ModelRetry, which re-ran the whole
    # generation and walked through ORCHESTRATOR_LIMITS — a measured 43s for
    # a quiz that still missed the ratio, and 361s for one that 502'd. One
    # slightly larger generation costs a fraction of that and lets the ratio
    # be selected instead of argued for.
    ask_for = quiz_ask_size(num_questions)
    allowance = conceptual_allowance(num_questions)
    # Phrased as prose, not as a schema constraint. This message used to say
    # "may be kind='conceptual'", but QuizQuestion has no `kind` field: a
    # self-declared kind enum was measured taking flash-lite from 5/5 to 3/5
    # successful generations and was reverted, so the classification is now
    # inferred from the stem (agents/quiz.py::is_worked_problem). Constraining
    # a key the model cannot emit is wasted prompt, and RULE 2 of the system
    # prompt already states the rule in schema-supported terms.
    routing_msg = (
        f"Generate {ask_for} {difficulty} questions for the student. "
        f"At most {allowance} of them may be purely conceptual (see RULE 2) "
        f"— every other question must pose concrete values for the student "
        f"to compute with. "
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
    run_kwargs: dict = {
        "deps": deps,
        "usage_limits": ORCHESTRATOR_LIMITS,
        # Per RUN, not pinned on the agent: the same quiz_agent instance
        # serves Lite (thinking off) and Pro (thinking capped), and Pro
        # rejects thinking_budget=0. See _build_quiz_model_settings.
        "model_settings": _build_quiz_model_settings(
            _effective_model_name(model_override)
        ),
    }
    if model_override is not None:
        run_kwargs["model"] = model_override

    # On a guardrail trip, retry ONCE on a genuinely different model.
    #
    # gemini-2.5-flash-lite intermittently answers this request with an
    # empty response: `finish_reason=error`, zero output tokens, no parts.
    # Not malformed output — nothing at all. pydantic-ai spends both output
    # retries re-asking, gets the identical empty response each time
    # (identical input_tokens too), and raises UnexpectedModelBehavior,
    # which this route turns into a 502. Sampled live it hit roughly one
    # generation in four.
    #
    # The retry therefore has to CHANGE THE MODEL. Re-running the same payload
    # on the same model reproduces the failure exactly — measured, a plain
    # fresh re-run failed both times, at 137s and 144s. A retry that lands
    # back on flash-lite only doubles the student's wait before the identical
    # 502, which is why the escalation target is _FALLBACK_MODEL_NAME and not
    # the "fast" preference (which IS flash-lite, this route's default).
    #
    # Skipped when the caller named a model: an explicit "fast"/"smart"
    # preference is the student's choice, not something to override on failure.
    #
    # Cost is bounded and only paid on failure: the ~75% of requests that
    # succeed on flash-lite never build the second model.
    last_error: Exception | None = None
    result = None
    attempts: list = [run_kwargs]
    if model_override is None:
        fallback = _resolve_fallback_model()
        if fallback is not None:
            attempts.append({
                **run_kwargs,
                "model": fallback,
                # Recomputed rather than inherited, so the settings still
                # match the model if either end of this pair changes tier.
                "model_settings": _build_quiz_model_settings(
                    _effective_model_name(fallback)
                ),
            })
    for attempt, kwargs in enumerate(attempts, start=1):
        try:
            result = record_agent_usage(
                await quiz_agent.run(user_message, **kwargs),
                feature="quiz", task="quiz", user_id=deps.user_id,
            )
            break
        except UnexpectedModelBehavior as exc:
            # Only THIS exception earns a second attempt. UsageLimitExceeded
            # was caught here too, but the retry reuses the same
            # ORCHESTRATOR_LIMITS object — a run that exhausted the budget
            # exhausts it again — so retrying on it bought a second full wait
            # for a guaranteed repeat failure. It propagates to generate_quiz,
            # which maps it to the same typed 502.
            last_error = exc
            next_kwargs = attempts[attempt] if attempt < len(attempts) else None
            logger.warning(
                "quiz: generation attempt %d/%d tripped a guardrail (%s); %s",
                attempt, len(attempts), type(exc).__name__,
                # Name the model the NEXT attempt actually runs on — the old
                # line hard-coded a model this route never used.
                f"retrying on {_effective_model_name(next_kwargs.get('model'))}"
                if next_kwargs is not None else "giving up",
            )
    if result is None:
        raise last_error  # generate_quiz maps this to its typed 502
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

@router.post("/generate")
async def generate_quiz(body: GenerateQuizBody, request: Request):
    require_self(body.user_id, request)
    # quiz_attempts.difficulty is CHECK-constrained (0025); reject drift before
    # we run the agent or write an attempt row.
    if body.difficulty not in VALID_DIFFICULTIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid difficulty '{body.difficulty}'. "
                   f"Must be one of {sorted(VALID_DIFFICULTIES)}.",
        )
    node_rows = table("graph_nodes").select(
        "*",
        filters={"id": f"eq.{body.concept_node_id}", "user_id": f"eq.{body.user_id}"},
    )
    if not node_rows:
        raise HTTPException(status_code=404, detail="Concept node not found")
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
        raise HTTPException(
            status_code=502,
            detail="Quiz generation is temporarily unavailable. Please try again.",
        ) from e
    except Exception as e:
        logger.exception("Unexpected quiz-agent failure; returning 502")
        raise HTTPException(
            status_code=502,
            detail="Quiz generation is temporarily unavailable. Please try again.",
        ) from e

    quiz_id = str(uuid.uuid4())
    table("quiz_attempts").insert({
        "id": quiz_id,
        "user_id": body.user_id,
        "concept_node_id": body.concept_node_id,
        "difficulty": body.difficulty,
        "questions_json": questions,
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
    return {"quiz_id": quiz_id, "questions": questions}


@router.post("/submit")
def submit_quiz(body: SubmitQuizBody, background_tasks: BackgroundTasks, request: Request):
    attempt_rows = table("quiz_attempts").select("*", filters={"id": f"eq.{body.quiz_id}"})
    if not attempt_rows:
        raise HTTPException(status_code=404, detail="Quiz not found")
    attempt = attempt_rows[0]

    questions = attempt["questions_json"]
    if isinstance(questions, str):
        questions = json.loads(questions)
    user_id = attempt["user_id"]
    require_self(user_id, request)

    # #129: completed_at is written on the first successful submit. A re-POST
    # of the same quiz_id must not re-run apply_graph_update (double mastery
    # delta + duplicate node_mastery_events row + streak bump), the background
    # quiz-context task, or achievements. 409 rather than replaying the original
    # 200: quiz_attempts stores no mastery_before/after, so faithfully
    # reconstructing the first response would need a migration.
    if attempt.get("completed_at"):
        raise HTTPException(
            status_code=409, detail="Quiz attempt has already been submitted"
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
        raise HTTPException(
            status_code=409, detail="Quiz attempt has already been submitted"
        )

    concept_node_id = attempt["concept_node_id"]

    answer_map = {str(a.question_id): a.selected_label for a in body.answers}
    results = []
    score = 0
    for q in questions:
        qid = str(q["id"])
        selected = answer_map.get(qid, "")
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
        raise HTTPException(status_code=404, detail="Concept node not found")
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
            "answers_json": [a.model_dump() for a in body.answers],
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

    def _update_context(prompt: str, uid: str, node_id: str):
        try:
            result = record_agent_usage(
                run_agent_sync(quiz_context_agent.run(prompt)),
                feature="quiz", task="quiz_context", user_id=uid,
            )
            save_quiz_context(uid, node_id, result.output.model_dump())
        except Exception:
            pass

    background_tasks.add_task(_update_context, ctx_prompt, user_id, concept_node_id)

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
