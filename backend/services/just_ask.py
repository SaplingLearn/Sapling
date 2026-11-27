"""Tutor redesign ("Just ask a question", owner decision 2026-11-26): an
ungraded chat with the tutor. A `just_ask` session starts teaching at once,
on no planned concept (the shape an empty plan leaves, as a study guide's
open Ask does), with a template opener so the student asks first, and it
grades nothing:

- no check is posed by a teach turn (`services/loop/cursor.py::_auto_poses_checks`)
  and "Check me" is refused (409 `UNGRADED_DETAIL`, at /check/next and the
  answer routes), so no check item is served or graded;
- no teach turn ends in an open question whose reply would get a verdict
  (spec §13 A121, `services/loop/turn.py::_asks_open_question`).

What the tutor reveals of a check item is still recorded by the served-text
scan, as on every loop turn. Gated per student by the `just_ask` flag (read at
the session's start only; a session opened while it was on stays ungraded).
"""
from __future__ import annotations

JUST_ASK_ORIGIN = "just_ask"
JUST_ASK_FLAG = "just_ask"
UNGRADED_DETAIL = "This session isn't graded: start a session to be checked"


def just_ask_state() -> dict:
    """The loop document a just-ask session starts with: `teach`, no planned
    concept, marked with its origin."""
    return {"phase": "teach", "origin": JUST_ASK_ORIGIN, "plan": {"approved": [], "cursor": 0}}


def is_just_ask(state: dict | None) -> bool:
    return isinstance(state, dict) and state.get("origin") == JUST_ASK_ORIGIN

