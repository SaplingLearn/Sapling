"""
backend/services/quiz/plan.py — the GET /api/quiz/plan handler body
(learning-loop spec §13 A143; moved into the quiz package with the rest of the
quiz route's bodies, spec §13 A149).

Reads only: the concepts the quiz proposes, in the learner model's order
(`services/quiz_learning.py::concept_plan`, `learning/quiz_plan.py`).
"""
import logging

from starlette.requests import Request

from services import quiz_learning
from services.auth_guard import require_self
from services.feature_flags import flag_on
# fastapi's HTTPException, through the package's one fastapi seam (errors.py).
from services.quiz.errors import HTTPException

# Log records keep the name they had in routes/quiz.py: an operator (or a
# caplog test) filters on it.
logger = logging.getLogger("routes.quiz")


def quiz_plan(request: Request, user_id: str, course_id: str | None = None):
    """Learning-loop spec §13 A143: the concepts the quiz proposes, in the
    learner model's order — due reviews first, then concepts with an open
    misconception, then concepts the student is ready to learn — each with
    its reason, decayed p_known and band (learning/quiz_plan.py). 404 while
    `quiz_concept_plan` is off for the student; 503 when the student's state
    could not be read (the home then keeps its own ranking). Reads only."""
    require_self(user_id, request)
    if not flag_on(quiz_learning.CONCEPT_PLAN_FLAG, user_id):
        raise HTTPException(status_code=404, detail="quiz plan not enabled")
    try:
        concepts = quiz_learning.concept_plan(user_id, course_id)
    except Exception as exc:
        logger.warning("quiz: plan unavailable (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="The quiz plan is unavailable right now.") from exc
    return {"concepts": concepts}
