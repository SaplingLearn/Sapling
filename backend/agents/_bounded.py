"""Local enforcement of output-length bounds (ADR 0030).

Gemini's structured output enforced `maxLength` at DECODE time: a bounded
string simply could not come out longer. Claude's strict JSON mode cannot
express string-length constraints at all — pydantic-ai's
AnthropicJsonSchemaTransformer moves `maxLength` into the field description —
so the bound became a request the model can overshoot. Pydantic still
validates locally, and an overshoot then burns the agent's output retries and
fails the run outright (the first Claude eval recording failed a document
summary three times on a 145-150-char headline against a 140 cap).

For FREE-PROSE fields, where a few trailing words are not load-bearing, the
right local equivalent of a decode-time cap is a clip, exactly as
`agents/quiz.py::_clip` already does for list caps: trim at a word boundary,
log it so drift stays visible, never reject the run. Identifier-like fields
(concept names, titles, enum-ish strings) deliberately keep the strict
`max_length` — a truncated name breaks identity, so a retry is the better
failure there.
"""

from __future__ import annotations

import logging

from pydantic import BeforeValidator

logger = logging.getLogger("sapling.agents.bounded")

_ELLIPSIS = "…"


def clip_prose_value(value, limit: int, field: str):
    """Clip a string longer than `limit` at the last word boundary that keeps
    the result (plus an ellipsis) within `limit`. Non-strings and in-bound
    strings pass through untouched for normal validation."""
    if not isinstance(value, str) or len(value) <= limit:
        return value
    budget = limit - len(_ELLIPSIS)
    head = value[:budget]
    cut = head.rfind(" ")
    # Only back up to a word boundary when one is reasonably close; a single
    # enormous token is hard-cut instead of collapsing to nothing.
    if cut >= budget * 0.6:
        head = head[:cut]
    clipped = head.rstrip(" ,;:-—") + _ELLIPSIS
    logger.warning("clipped %s from %d to %d chars", field, len(value), len(clipped))
    return clipped


def clip_prose(limit: int, field: str) -> BeforeValidator:
    """`Annotated[str, clip_prose(N, "x")] = Field(max_length=N, ...)`: keep
    the schema's `max_length` (a decode-time cap on Gemini, a description
    hint on Claude) and clip an overshoot before Pydantic checks it."""
    return BeforeValidator(lambda v: clip_prose_value(v, limit, field))
