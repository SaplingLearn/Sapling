"""
backend/services/tutor/ — the AI tutor domain (#118).

What used to be ``routes/learn.py`` (2,010 lines). The route is now the HTTP
surface only; each handler's body lives here under the handler's own name,
and every helper and constant moved under its old name (re-exported by
``routes/learn.py``, so ``from routes.learn import _foo`` keeps working).

- ``run``: model preference, prompt assembly (``_prepare_chat_run``), the
  run's own text (``_new_run_text``), the #646 continuation, the #640 hook.
- ``course``: topic/session -> course and offering, course info, the BU
  catalog chunk (``_get_catalog_chunk``, also the quiz's catalog read).
- ``messages``: transcript load/write, turn-derived ids and replay (#761).
- ``pending``: lazy-session materialisation and the turn entry checks.
- ``turns``: ``start_session``, ``chat``, ``action`` and the guardrail mapping.
- ``streams``: ``chat_stream`` and ``start_session_stream``.
- ``sessions``: ``end_session``, ``list_sessions``, ``rename_session``,
  ``delete_session``, ``resume_session``, ``mode_switch``.
- ``errors``: the package's one ``fastapi`` import (``HTTPException``).

The flat modules the tutor builds on stay where they are, beside this
package: ``services/chat_stream.py`` (``stream_agent_turn``),
``services/tutor_router.py`` and ``services/tutor_sessions.py``.

The names below resolve lazily, so importing this package (the quiz does, for
``_get_catalog_chunk``) does not pull in the agents the turn modules import.
"""
from __future__ import annotations

import importlib

_PUBLIC = {
    "_get_catalog_chunk": "course",
    "MODE_DISPLAY_NAMES": "sessions",
    "SESSION_LIST_MAX": "sessions",
    "action": "turns",
    "chat": "turns",
    "chat_stream": "streams",
    "delete_session": "sessions",
    "end_session": "sessions",
    "get_user_name": "pending",
    "list_sessions": "sessions",
    "mode_switch": "sessions",
    "rename_session": "sessions",
    "resume_session": "sessions",
    "save_message": "messages",
    "save_message_sync": "messages",
    "start_session": "turns",
    "start_session_stream": "streams",
}

__all__ = sorted(_PUBLIC)


def __getattr__(name: str):
    module = _PUBLIC.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(f"{__name__}.{module}"), name)
