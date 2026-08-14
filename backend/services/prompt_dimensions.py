"""Per-request prompt-composition dimensions (F6, #544 addendum Part 2).

Why this exists
---------------
`llm_usage.prompt_tokens` has always recorded the truth about how big each
prompt was. What it cannot record is what the prompt was made OF — so the
quiz's token cost was attributable to a request but not to a *section*, and
the only available answer to "what should we trim?" was the audit's
hand-estimate of ~2–4k in. Nobody should tune a prompt against an estimate.

These dimensions are the join key that fixes that. They ride into the
`quiz.started` event, which carries the same `request_id` as the
`llm_usage` row for the same generation, so a rollup can put "this
generation was 3.1k prompt tokens" next to "it had a catalog block, 4 RAG
chunks totalling 6.2k chars, a digest, and 12 do-not-repeat stems".

The cross-thread contract
-------------------------
The route knows most of the dimensions, but not all: whether the personal
digest existed is only known inside `read_recent_quiz_attempts`, an agent
tool whose Supabase reads run under `asyncio.to_thread`.

`contextvars.copy_context()` — which both `asyncio.to_thread` and task
creation use — copies the *mapping*, not the values. So a tool that mutates
the accumulator dict is seen by the route, while a tool that rebound the
ContextVar would not be. This module therefore only ever mutates the dict
in place after `start_capture()` installs it, and never rebinds mid-request.
(The same asymmetry is documented at the other end of the codebase in
`services/request_context.py`, where the shared ASGI scope is the only
channel that propagates back out of BaseHTTPMiddleware's downstream task.)

Contract: never raises, never blocks. This is measurement.
"""

from __future__ import annotations

import contextvars
import logging

logger = logging.getLogger(__name__)

_DIMS: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "sapling_prompt_dims", default=None,
)


def start_capture() -> dict:
    """Open a capture scope for this request and return the accumulator.

    Installs a FRESH dict: a reused one would carry a previous generation's
    grounding into this one's attribution.
    """
    dims: dict = {}
    _DIMS.set(dims)
    return dims


def record(**dims) -> None:
    """Contribute dimensions to the current scope.

    A no-op outside a scope, which is the common case for every caller that
    isn't instrumented yet — the tutor's tools, and every unit test. A tool
    must never need to know whether its caller is measuring.
    """
    try:
        current = _DIMS.get()
        if current is None:
            return
        current.update(dims)
    except Exception:  # pragma: no cover - defensive; measurement can't break a run
        logger.debug("prompt_dimensions.record slipped", exc_info=True)


def snapshot() -> dict:
    """The dimensions recorded so far, as a COPY.

    A copy because the caller's next move is to stuff this into an event
    payload that the events worker serializes on another thread — handing
    out the live dict would race a tool still recording into it.
    """
    try:
        current = _DIMS.get()
        return dict(current) if current else {}
    except Exception:  # pragma: no cover - defensive
        return {}


def clear() -> None:
    """Close the capture scope."""
    _DIMS.set(None)
