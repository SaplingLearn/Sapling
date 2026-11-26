"""The quiz's evidence rules for a question answered OUTSIDE a quiz attempt.

A question graded on another surface — today the study guide's
check-yourself questions (services/study_guides/answers.py) — is mastery
evidence in the quiz's own namespace (the same `question_hash`), so it obeys
the quiz's own rules, applied by the quiz's own code (one copy, never a
second that could drift):

* spec §13 A94/A100: a question counts at most ONCE per student per rolling
  QUIZ_EVIDENCE_WINDOW_HOURS, decided by a claim in `quiz_evidence_claims`
  (`services/quiz/submission.py::_farm_guard`); a failed claim counts
  nothing (fail closed). A guide's Regenerate clears its stored answers, so
  without this the same question would count again at full weight.
* spec §13 A99: the help ledger's floor — a question the student had help on
  is graded at that rung (`_help_floor`; an unreadable ledger floors at no
  credit).

A flat module on purpose: a domain package reaches another only through its
``__init__`` (.importlinter ``domains``), and these rules are the quiz's
internals.
"""
from __future__ import annotations

from services.quiz.submission import _farm_guard, _help_floor


def guard_question_evidence(user_id: str, owner_id: str, evidence: list[dict]) -> list[dict]:
    """The evidence dicts that may be written, floored: those whose question
    this call claimed for the window (`owner_id` names the claimant — a guide
    block, as a quiz names its attempt), each carrying the help ledger's rung.
    [] when every question is already claimed or the claim failed. Sync, and
    it reads and writes the database: call it off the event loop."""
    return _help_floor(user_id, _farm_guard(user_id, owner_id, evidence))
