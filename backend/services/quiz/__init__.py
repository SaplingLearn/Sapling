"""
backend/services/quiz/ — the quiz domain (#118).

What used to be ``routes/quiz.py`` (3,148 lines) plus the ten flat
``services/quiz_*.py`` modules. The route is now the HTTP surface only; each
handler's body lives here under the handler's own name.

Moved out of the route (names unchanged, re-exported by ``routes/quiz.py``):

- ``limits``: daily spend cap and rate-limit refund (#544 F1, #760).
- ``wire``: the stored/served question shape and its validity checks.
- ``attempts``: derived status, owned-attempt load and refusals, the abandon
  sweep, the attempt insert; ``answer_question`` and ``abandon_attempt``.
- ``history``: ``list_attempts`` and ``get_attempt``.
- ``grounding``: course row, BU code, catalog + RAG material, E8/E6 blocks.
- ``practice``: G5 re-serve of missed questions.
- ``generation``: ``_quiz_via_agent``, ``_generate_or_502``, ``generate_quiz``.
- ``submission``: grading, score/mastery writes, ``submit_quiz``.
- ``plan``: ``quiz_plan``, the learning loop's concept plan (spec §13 A143).

Moved from ``services/quiz_*.py`` (the old paths are aliases of these):
``algebra``, ``config``, ``context`` (was ``quiz_context_service``),
``distractors``, ``errors``, ``grading``, ``identity``, ``repetition``,
``reserve``, ``signals``.

``errors`` is the package's one ``fastapi`` import: ``QuizAPIError`` subclasses
``HTTPException`` so main.py's #540 A3 envelope handlers see every quiz error.

The public names below resolve lazily. ``agents/quiz.py`` and ``models``
import ``services.quiz.config`` while ``generation``/``submission`` import
them back, so an eager import here would be a cycle.
"""
from __future__ import annotations

import importlib

_PUBLIC = {
    "abandon_attempt": "attempts",
    "answer_question": "attempts",
    "generate_quiz": "generation",
    "get_attempt": "history",
    "list_attempts": "history",
    "quiz_plan": "plan",
    "quiz_config_payload": "config",
    "submit_quiz": "submission",
}

__all__ = sorted(_PUBLIC)


def __getattr__(name: str):
    module = _PUBLIC.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(f"{__name__}.{module}"), name)
