import json
import logging
import os
import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from pydantic_ai.exceptions import UsageLimitExceeded, UnexpectedModelBehavior

from agents.quiz import quiz_agent, Quiz, QuizQuestion
from agents.deps import SaplingDeps
from db.connection import table
from models import GenerateQuizBody, SubmitQuizBody
from services.auth_guard import require_self
from services.encryption import decrypt_if_present
from services.gemini_service import MODEL_LITE, MODEL_SMART, call_gemini_json
from services.graph_service import apply_mastery_event, get_graph, update_streak
from services.quiz_context_service import get_quiz_context, save_quiz_context
from services.fingerprint import fingerprint
from services.request_context import current_request_id

logger = logging.getLogger(__name__)

router = APIRouter()

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")


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
    name = _PREF_MODEL_NAMES.get(model_pref)
    if not name:
        return None
    from agents._providers import google_model
    return google_model(name)


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
    user_message = (
        f"Generate {num_questions} {difficulty} questions for the student. "
        f"The target concept is '{concept_name}' "
        f"(concept_node_id={concept_node_id}). Follow the workflow in your "
        f"system prompt; pass concept_node_id='{concept_node_id}' to "
        f"read_recent_quiz_attempts."
    )
    if use_shared_context:
        user_message += (
            " Also call read_misconceptions_for_course and use those misconceptions "
            "as distractors and probes."
        )

    model_override = _resolve_model_pref(model_pref)
    run_kwargs: dict = {"deps": deps}
    if model_override is not None:
        run_kwargs["model"] = model_override
    result = await quiz_agent.run(user_message, **run_kwargs)
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
        # All questions dropped — degrade to legacy rather than serve
        # an empty quiz. Raise a sentinel that generate_quiz catches
        # and routes to the legacy fallback.
        raise RuntimeError(
            "quiz_agent produced no valid questions after wire-format validation"
        )
    return wire_questions


async def _legacy_generate_quiz(body: GenerateQuizBody, request: Request) -> list[dict]:
    """The pre-agent quiz generation pipeline, kept as a fallback per ADR-0001.

    Verbatim copy of the original generate_quiz body: prompt-template assembly,
    course-context augmentation, and a single call_gemini_json.
    Returns the raw `questions` list — the route handler is responsible for
    persisting it and shaping the HTTP response.
    """
    node_rows = table("graph_nodes").select(
        "*",
        filters={"id": f"eq.{body.concept_node_id}", "user_id": f"eq.{body.user_id}"},
    )
    if not node_rows:
        raise HTTPException(status_code=404, detail="Concept node not found")
    node = node_rows[0]

    graph_data = get_graph(body.user_id)
    quiz_ctx = get_quiz_context(body.user_id, body.concept_node_id)
    quiz_ctx_str = json.dumps(quiz_ctx, indent=2) if quiz_ctx else "No previous quiz history."

    prompt = (
        _load_prompt("quiz_generation.txt")
        .replace("{concept_name}", node["concept_name"])
        .replace("{mastery_score}", str(int(node["mastery_score"] * 100)))
        .replace("{difficulty}", body.difficulty)
        .replace("{num_questions}", str(body.num_questions))
        .replace("{graph_json_subset}", json.dumps(graph_data["nodes"][:10], indent=2))
        .replace("{quiz_context_json}", quiz_ctx_str)
    )

    # Append shared course-level context (misconceptions + weak areas) if available
    course_id = node.get("course_id", "")
    if body.use_shared_context and course_id:
        from services.course_context_service import get_course_context
        course_ctx = get_course_context(course_id)
        if course_ctx:
            misconceptions: list[str] = []
            weak_areas: list[str] = []
            seen_m: set[str] = set()
            seen_w: set[str] = set()
            for row in course_ctx.get("concept_stats") or []:
                if not isinstance(row, dict):
                    continue
                for m in row.get("common_misconceptions") or []:
                    m = (m or "").strip()
                    if m and m.lower() not in seen_m:
                        seen_m.add(m.lower())
                        misconceptions.append(m)
                for w in row.get("prerequisite_gaps") or []:
                    w = (w or "").strip()
                    if w and w.lower() not in seen_w:
                        seen_w.add(w.lower())
                        weak_areas.append(w)
            if misconceptions or weak_areas:
                addendum_parts = []
                if misconceptions:
                    addendum_parts.append(
                        "Common misconceptions seen across the class for this subject "
                        "(address these proactively in distractors and explanations):\n"
                        + "\n".join(f"- {m}" for m in misconceptions[:10])
                    )
                if weak_areas:
                    addendum_parts.append(
                        "Weak areas to target:\n"
                        + "\n".join(f"- {w}" for w in weak_areas[:10])
                    )
                prompt += "\n\n" + "\n\n".join(addendum_parts)

    # Honor the same fast/smart toggle the agent path uses. The mapping
    # mirrors _PREF_MODEL_NAMES exactly, so a user choosing "fast" gets
    # the same upgraded model whether the agent succeeded or fell back
    # here. Without this, "fast" was silently a no-op on the legacy
    # path (still MODEL_LITE) — the kind of inconsistency that surfaces
    # six months later as "why does Fast sometimes feel slower?"
    if body.model_pref == "smart":
        legacy_model = MODEL_SMART  # gemini-2.5-pro
    elif body.model_pref == "fast":
        legacy_model = MODEL_LITE  # gemini-2.5-flash-lite, matches _PREF_MODEL_NAMES
    else:
        legacy_model = MODEL_LITE  # gemini-2.5-flash-lite, agent default per ADR 0008
    try:
        result = call_gemini_json(prompt, model=legacy_model)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini error: {e}")

    return result.get("questions", [])


@router.post("/generate")
async def generate_quiz(body: GenerateQuizBody, request: Request):
    require_self(body.user_id, request)
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
    except (UsageLimitExceeded, UnexpectedModelBehavior) as e:
        logger.warning(
            "Quiz agent guardrails tripped; falling back to legacy",
            exc_info=e,
        )
        questions = await _legacy_generate_quiz(body, request)
    except HTTPException:
        # Legacy path raises HTTPException for known states (404/502); never
        # treat those as a reason to fall back. Re-raise.
        raise
    except Exception:
        logger.exception(
            "Unexpected quiz-agent failure; falling back to legacy"
        )
        questions = await _legacy_generate_quiz(body, request)

    quiz_id = str(uuid.uuid4())
    table("quiz_attempts").insert({
        "id": quiz_id,
        "user_id": body.user_id,
        "concept_node_id": body.concept_node_id,
        "difficulty": body.difficulty,
        "questions_json": questions,
    })
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
    concept_node_id = attempt["concept_node_id"]

    answer_map = {str(a.question_id): a.selected_label for a in body.answers}
    results = []
    score = 0
    for q in questions:
        qid = str(q["id"])
        selected = answer_map.get(qid, "")
        correct_opt = next((o for o in q["options"] if o.get("correct")), None)
        correct_label = correct_opt["label"] if correct_opt else ""
        is_correct = selected == correct_label
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

    # The attempt's concept node must belong to the attempt's owner. A missing
    # or foreign node means we'd otherwise write mastery to someone else's row
    # (IDOR) — refuse before any write. The one owner-scoped fetch carries
    # everything the mastery write and the ctx prompt need.
    node_rows = table("graph_nodes").select(
        "mastery_score,times_studied,mastery_events,course_id,concept_name",
        filters={"id": f"eq.{concept_node_id}", "user_id": f"eq.{user_id}"},
    )
    if not node_rows:
        raise HTTPException(status_code=404, detail="Concept node not found")
    node = {"id": concept_node_id, **node_rows[0]}

    score_ratio = score / total if total > 0 else 0.0
    if score_ratio >= 0.7:
        event_type = "correct"
    elif score_ratio >= 0.4:
        event_type = "partial"
    else:
        event_type = "confusion"

    # Route the mastery write through the shared graph_service primitive rather
    # than re-implementing mastery/event logic and writing graph_nodes directly
    # (#128/#6). user_id keeps the write owner-scoped (IDOR defense-in-depth).
    change = apply_mastery_event(
        node,
        (score * 0.03) - ((total - score) * 0.02),
        reason=f"Quiz: {score}/{total} correct",
        event_type=event_type,
        user_id=user_id,
    )
    mastery_before = change["before"]
    mastery_after = change["after"]
    node_course_id = change["course_id"]
    concept_name = node_rows[0].get("concept_name") or "Unknown"

    table("quiz_attempts").update(
        {
            "score": score,
            "total": total,
            "answers_json": [a.model_dump() for a in body.answers],
            "completed_at": datetime.utcnow().isoformat(),
        },
        filters={"id": f"eq.{body.quiz_id}"},
    )

    update_streak(user_id)

    # Refresh the per-course aggregate the quiz just changed. Backgrounded so a
    # slow aggregation/summary never blocks the submit response (#6).
    if node_course_id:
        def _refresh_course_ctx(cid: str):
            try:
                from services.course_context_service import update_course_context
                update_course_context(cid)
            except Exception:
                pass
        background_tasks.add_task(_refresh_course_ctx, node_course_id)

    user_rows = table("users").select("name", filters={"id": f"eq.{user_id}"})
    student_name = decrypt_if_present(user_rows[0]["name"]) if user_rows else "Student"

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
            new_ctx = call_gemini_json(prompt, model=MODEL_LITE)
            save_quiz_context(uid, node_id, new_ctx)
        except Exception:
            pass

    background_tasks.add_task(_update_context, ctx_prompt, user_id, concept_node_id)

    # Check for achievements after quiz completion
    try:
        from services.achievement_service import check_achievements
        check_achievements(user_id, "quizzes_completed", {})
    except Exception:
        pass

    return {
        "score": score,
        "total": total,
        "mastery_before": mastery_before,
        "mastery_after": mastery_after,
        "results": results,
    }
