"""PKG-14 final fix round (spec §13 A99): the quiz "Ask about this" session.

The quiz's AskPanel opens a tutor session about ONE quiz question the student
has just answered, and hands the tutor the question, both options and the
explanation. Two consequences, both decided here with structured data:

- **Where the session starts.** On the loop path the session skips the probe and
  the plan and starts in `teach` on the quiz's concept node (the attempt row's
  `concept_node_id`, owner-scoped) — the follow-up chat is a teach turn, not a
  409 "finish the probe first".
- **The help it is.** The tutor is asked to explain THIS question, with its
  correct option in hand, so the session is recorded in the per-student help
  ledger (A93) for the question's `question_hash` at RUNG_NO_CREDIT_MIN — the
  rung of a served reveal: the tutor may state and explain the answer. Quiz
  evidence on that hash then carries the floor (`routes/quiz.py` submit), so a
  question asked about earns no unassisted credit, in this attempt or any later
  one (A94's re-served misses included).

The question is named by (attempt id, question index); the hash is resolved
from the attempt row the student owns — a client-supplied hash is never read.
The help row is written BEFORE any tutor text is served; a failed write refuses
the session (503), because a tutor explanation the ledger cannot see would be
unassisted credit later. Shared by the loop opener (`routes/learn_loop.py`) and
the kill-switch path (`routes/learn.py`), so both lanes floor the quiz alike."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import HTTPException

from db.connection import table
from learning.help_ledger import record_help
from learning.params import RUNG_NO_CREDIT_MIN
from services.encryption import decrypt_json_column
from services.quiz_identity import wire_question_hash

logger = logging.getLogger(__name__)

QUIZ_ASK_ORIGIN = "quiz_ask"
#: the help a quiz-ask session is: the tutor explains this question with its
#: correct option in hand — a served reveal (A93: RUNG_NO_CREDIT_MIN)
QUIZ_ASK_HELP_RUNG = RUNG_NO_CREDIT_MIN
#: the help ledger's `source` for it (learning.help_ledger.SOURCES)
QUIZ_ASK_SOURCE = "quiz"

_NOT_FOUND = "quiz question not found"
_UNRECORDED = "Could not record the quiz help; please try again."


@dataclass(frozen=True)
class QuizAskTarget:
    """The quiz question a quiz-ask session is about."""

    question_hash: str
    node_id: str
    course_id: str | None


def resolve_quiz_ask(user_id: str, attempt_id: str, question_index: int) -> QuizAskTarget:
    """The question's identity and concept from the attempt row the student owns.
    404 for an attempt that is missing, another student's, or has no such
    question (or a question with no identity); a failed read raises (the route's
    error mapping makes it a 5xx — never an unrecorded session)."""
    rows = table("quiz_attempts").select(
        "user_id,concept_node_id,questions_json", filters={"id": f"eq.{attempt_id}"}, limit=1
    )
    if not rows or rows[0].get("user_id") != user_id:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    questions = decrypt_json_column(rows[0].get("questions_json")) or []
    if not isinstance(questions, list) or not 0 <= int(question_index) < len(questions):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    qh = wire_question_hash(questions[int(question_index)])
    node_id = rows[0].get("concept_node_id")
    if not qh or not node_id:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    nodes = table("graph_nodes").select(
        "id,course_id", filters={"id": f"eq.{node_id}", "user_id": f"eq.{user_id}"}, limit=1
    )
    if not nodes:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return QuizAskTarget(question_hash=qh, node_id=node_id, course_id=nodes[0].get("course_id"))


def open_quiz_ask(body, *, session_id: str | None) -> QuizAskTarget | None:
    """For a `quiz_ask` StartSessionBody: resolve the question and record the
    help row, BEFORE any tutor text exists. None for every other origin. A failed
    ledger write is a 503 (fail closed)."""
    if getattr(body, "origin", None) != QUIZ_ASK_ORIGIN:
        return None
    target = resolve_quiz_ask(body.user_id, body.quiz_attempt_id, body.quiz_question_index)
    try:
        record_help(
            body.user_id,
            target.question_hash,
            QUIZ_ASK_HELP_RUNG,
            source=QUIZ_ASK_SOURCE,
            session_id=session_id,
        )
    except Exception:
        logger.error("quiz-ask help row not recorded; refusing the session", exc_info=True)
        raise HTTPException(status_code=503, detail=_UNRECORDED) from None
    return target
