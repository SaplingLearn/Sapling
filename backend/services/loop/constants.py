"""The loop's fixed texts and details: the 404/429 bodies, the feedback lines,
the refusal and unavailable replies, the 409 details and the probe-phase
opener template (moved verbatim from routes/learn_loop.py, #118).
"""
from __future__ import annotations

from learning.ladder import Rung
from learning.turn_shape import LOOP_PROBE_OPENER


_NOT_ENABLED = "learning loop not enabled"


_BUDGET_DETAIL = "ai budget reached"  # spec §3.5 hard-level body (A20)


#: The legacy catalog header (routes/learn.py::_prepare_chat_run), verbatim.
_CATALOG_HEADER = "COURSE CATALOG INFO (official BU course data):\n\n"


_SOURCE_HEADER = "CHECK ITEM SOURCE PASSAGES (the course text this item was written from):\n"


_SOURCE_LABEL = "student-document chunks"


_FEEDBACK_VERDICT_LINES = {
    "correct": "Correct.",
    "not_yet": "Not yet.",
    "idk": "No problem — here is the answer.",
}


_FEEDBACK_ANSWER_LEAD = "The answer: "


_FEEDBACK_NEXT_STEP = "When you're ready, try the next check."


_GRADE_UNAVAILABLE_REPLY = (
    "I couldn't check that answer just now, so nothing was recorded. "
    "Please submit it again in a moment."
)


#: A33: the guard refused the answer (it addressed the grader). Not an outage,
#: never a skip: the student is asked again; the CHECK_REFUSALS_AS_IDK-th
#: refusal of the same item is recorded as idk instead.
_ANSWER_REFUSED_REPLY = (
    "I can only check an answer written in your own words, so nothing was recorded. "
    "Please answer the question itself and submit again."
)


_IDK_RENDERED = "I don't know"


_SUBMISSION_KINDS = ("feedback", "hint_request", "unavailable", "refused")


#: A38 06(q): the 409 detail when the loop-state compare-and-set is exhausted.
_STATE_CONFLICT = "loop state changed, retry"


#: C2 (review round 3): the 409 detail for a submission on an item that is
#: graded, or being graded under another request's claim.
_ALREADY_GRADED = "already graded"


_FEEDBACK_PENDING = "feedback pending; retry feedback before another check"


_WITHDRAWN_FEEDBACK = (
    "This check has been withdrawn. {result} The question and solution are no longer "
    "available. You can continue with another check or end this session."
)


_DETERMINISTIC_RUNGS = (Rung.H2, Rung.H4, Rung.H6)


#: The session opener served without a model (A27, A121): ALWAYS while the new
#: session is in the probe phase — a neutral welcome and the check-in's intro,
#: no teaching and no question (the check-in is a pretest; teaching first skews
#: it, and a question would compete with its first item) — and at the hard
#: budget level, so a capped student can still start a session and reach the
#: probe (§3.5).
_LOOP_OPENER_TEMPLATE = LOOP_PROBE_OPENER


_WITHDRAWN_ITEM = "check item withdrawn"
