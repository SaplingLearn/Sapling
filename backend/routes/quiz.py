import logging
import uuid
import json
import os
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from pydantic_ai.exceptions import UsageLimitExceeded, UnexpectedModelBehavior

from agents.quiz import quiz_agent, Quiz, QuizQuestion
from agents.deps import SaplingDeps
from config import get_mastery_tier
from db.connection import table
from models import GenerateQuizBody, SubmitQuizBody
from services.auth_guard import require_self
from services.encryption import decrypt_if_present
from services.gemini_service import MODEL_LITE, call_gemini_json
from services.graph_service import get_graph, update_streak
from services.quiz_context_service import get_quiz_context, save_quiz_context
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


def _agent_question_to_wire(q: QuizQuestion, qid: int) -> dict:
    """Map an agent QuizQuestion to the legacy wire-format dict.

    For multiple_choice: emit options=[{label,text,correct}] with exactly
    one option flagged correct (the one whose `text` matches
    `q.correct_answer`; if no exact match, the first option is flagged so
    the quiz remains gradable).
    For short_answer: emit a single synthetic option (label "A") that
    holds the canonical answer, marked correct=True. This keeps
    `submit_quiz`'s grading loop (which assumes options[].correct) working
    without a special-case branch.
    """
    if q.type == "multiple_choice":
        options: list[dict] = []
        matched = False
        for i, text in enumerate(q.options[: len(_OPTION_LABELS)]):
            is_correct = (not matched) and (text.strip() == q.correct_answer.strip())
            if is_correct:
                matched = True
            options.append({
                "label": _OPTION_LABELS[i],
                "text": text,
                "correct": is_correct,
            })
        # Defensive: if no option matched the canonical answer (LLM drift),
        # mark the first one correct so submit_quiz can still score the
        # attempt instead of returning 0/N for a generation-quality issue.
        if options and not matched:
            options[0]["correct"] = True
        return {
            "id": qid,
            "question": q.question,
            "options": options,
            "explanation": q.explanation,
            "concept_tested": q.concept,
            "difficulty": q.difficulty,
        }
    # short_answer: single synthetic option carrying the canonical answer.
    return {
        "id": qid,
        "question": q.question,
        "options": [{"label": "A", "text": q.correct_answer, "correct": True}],
        "explanation": q.explanation,
        "concept_tested": q.concept,
        "difficulty": q.difficulty,
        "type": "short_answer",
    }


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
) -> list[dict]:
    """Run quiz_agent and return questions in the legacy wire shape.

    The agent's tools (read_concepts_for_user, read_misconceptions_for_course)
    pull weak-area + class misconception data themselves, replacing the
    manual prompt-string augmentation that used to live in generate_quiz.
    """
    deps = SaplingDeps(
        user_id=user_id,
        course_id=course_id,
        supabase=None,
        request_id=request_id,
    )
    user_message = (
        f"Generate {num_questions} {difficulty} questions for the student. "
        f"The target concept is '{concept_name}' (concept_node_id={concept_node_id}). "
        f"Call read_concepts_for_user to find the student's weakest concepts in this course "
        f"and bias the question mix toward those."
    )
    if use_shared_context:
        user_message += (
            " Also call read_misconceptions_for_course and use those misconceptions "
            "as distractors and probes."
        )

    result = await quiz_agent.run(user_message, deps=deps)
    quiz: Quiz = result.output
    return [_agent_question_to_wire(q, i + 1) for i, q in enumerate(quiz.questions)]


async def _legacy_generate_quiz(body: GenerateQuizBody, request: Request) -> list[dict]:
    """The pre-agent quiz generation pipeline, kept as a fallback per ADR-0001.

    Verbatim copy of the original generate_quiz body: prompt-template assembly,
    course-context augmentation, and a single call_gemini_json.
    Returns the raw `questions` list — the route handler is responsible for
    persisting it and shaping the HTTP response.
    """
    node_rows = table("graph_nodes").select(
        "*", filters={"id": f"eq.{body.concept_node_id}"}
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

    try:
        result = call_gemini_json(prompt, model=MODEL_LITE)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini error: {e}")

    return result.get("questions", [])


@router.post("/generate")
async def generate_quiz(body: GenerateQuizBody, request: Request):
    require_self(body.user_id, request)
    node_rows = table("graph_nodes").select(
        "*", filters={"id": f"eq.{body.concept_node_id}"}
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

    node_rows = table("graph_nodes").select(
        "mastery_score,times_studied,mastery_events",
        filters={"id": f"eq.{concept_node_id}"},
    )
    mastery_before = node_rows[0]["mastery_score"] if node_rows else 0.0
    mastery_after = max(0.0, min(1.0, mastery_before + (score * 0.03) - ((total - score) * 0.02)))
    new_tier = get_mastery_tier(mastery_after)
    times_studied = (node_rows[0]["times_studied"] if node_rows else 0) + 1

    score_ratio = score / total if total > 0 else 0.0
    if score_ratio >= 0.7:
        event_type = "correct"
    elif score_ratio >= 0.4:
        event_type = "partial"
    else:
        event_type = "confusion"

    existing_events = (node_rows[0].get("mastery_events") or []) if node_rows else []
    quiz_event = {
        "ts": datetime.utcnow().isoformat(),
        "delta": round(mastery_after - mastery_before, 4),
        "reason": f"Quiz: {score}/{total} correct",
        "event_type": event_type,
    }
    updated_events = (existing_events + [quiz_event])[-20:]

    table("graph_nodes").update(
        {
            "mastery_score": mastery_after,
            "mastery_tier": new_tier,
            "times_studied": times_studied,
            "last_studied_at": datetime.utcnow().isoformat(),
            "mastery_events": updated_events,
        },
        filters={"id": f"eq.{concept_node_id}"},
    )
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

    node2_rows = table("graph_nodes").select(
        "concept_name", filters={"id": f"eq.{concept_node_id}"}
    )
    user_rows = table("users").select("name", filters={"id": f"eq.{user_id}"})
    concept_name = node2_rows[0]["concept_name"] if node2_rows else "Unknown"
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
