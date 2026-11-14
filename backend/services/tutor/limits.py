"""Per-student cost guard on the tutor turn (testathon hardening).

Every other model-spending feature already has one — quiz generation
(`services/quiz/config.py`), study guides (`services/study_guides/limits.py`),
flashcard import and suggest, the topic checklist, OCR. The TUTOR did not,
and it is the most expensive slot in the app: `agents/_providers.py` puts the
tutor on Sonnet while the generation slots run Haiku.

The per-user daily token budget (`services/llm_budget.py`) is the other half
of this, but it is behind the `llm_budget` feature flag whose first variant —
and therefore its default — is "off". With the flag off there was NOTHING
between a signed-in account and an unbounded number of Sonnet calls.

The limit is deliberately generous: a student deep in an exam-week session
sends a lot of messages, and a cost guard that interrupts real studying is a
worse bug than the one it prevents. It is sized to stop a script, not a
person — at the default a caller can still hold a long conversation, but not
thousands of turns an hour. Both numbers are env-overridable so an operator
can retune without a deploy, exactly as the quiz limits are.

Applied AFTER the ownership guard in each entry point, for the reason #544 F1
gives in `services/quiz/generation.py`: a caller who is refused for being the
wrong user must not consume the victim's quota on the way out.
"""

from __future__ import annotations

import os

from fastapi import HTTPException

from services.request_limits import acheck_rate_limit


def _positive_int_env(name: str, default: int) -> int:
    """`default` unless the env var names a positive integer (mirrors
    `services/quiz/config.py::_positive_int_env`, so a typo is ignored rather
    than disabling the guard)."""
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


#: Tutor turns per student per window. A turn is one model run: a chat
#: message, an action (hint/explain), or opening a session.
TUTOR_TURN_RATE_LIMIT = _positive_int_env("TUTOR_TURN_RATE_LIMIT", 120)
TUTOR_TURN_RATE_WINDOW_SEC = _positive_int_env("TUTOR_TURN_RATE_WINDOW_SEC", 3600)

_DETAIL = (
    "You've sent a lot of messages to the tutor this hour. "
    "Take a short break and try again."
)


async def enforce_turn_limit(user_id: str) -> None:
    """Raise 429 when `user_id` has spent this window's tutor turns.

    Async: the limiter is a PostgREST call under the `stateless_rate_limit`
    flag, and every tutor entry point is an `async def`.
    """
    retry_after = await acheck_rate_limit(
        f"tutor_turn:{user_id}",
        limit=TUTOR_TURN_RATE_LIMIT,
        window_sec=TUTOR_TURN_RATE_WINDOW_SEC,
        # Per-process, and no feature-flag read on the tutor's hot path. The
        # turn already spends a model call, so the guard in front of it must
        # not add I/O of its own — and pulling the flag store into this
        # request is a dependency a call-counter has no business having.
        # Each replica keeps its own window, so the real ceiling is
        # `limit x replicas`; that is the right trade for a guard whose job
        # is to stop a script rather than to bill anyone precisely.
        memory_only=True,
    )
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail=_DETAIL,
            headers={"Retry-After": str(retry_after)},
        )
