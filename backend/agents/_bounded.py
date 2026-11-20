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
log it so drift stays visible, never reject the run. Bounded LISTS get the
same treatment (`clip_list`): keep the first N in model order, as a
decode-time `maxItems` did. Identifier-like fields
(concept names, titles, enum-ish strings) deliberately keep the strict
`max_length` — a truncated name breaks identity, so a retry is the better
failure there.
"""

from __future__ import annotations

import logging
import math

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


def clip_list_value(value, limit: int, field: str):
    """Keep the first `limit` entries of a raw list, in model order, logging
    the clip. Non-lists pass through for normal validation to reject."""
    if isinstance(value, list) and len(value) > limit:
        logger.warning("clipped %s from %d to %d items", field, len(value), limit)
        return value[:limit]
    return value


def clip_list(limit: int, field: str) -> BeforeValidator:
    """`Annotated[list[X], clip_list(N, "x")] = Field(max_length=N, ...)`: the
    list-cap twin of `clip_prose` (and of `agents/quiz.py::_clip`). The schema
    keeps `max_length` — decode-enforced on Gemini, a description hint on
    Claude — and a surplus past it is dropped before Pydantic checks it, so it
    never burns an output retry. A `min_length` stays a real error."""
    return BeforeValidator(lambda v: clip_list_value(v, limit, field))


def clamp_unit_value(value, field: str):
    """A finite number past [0, 1] clamped into it, logged (#866 Z44/Z55); any
    other value (in range, non-finite, not a number) passes through, so a
    NaN or an infinity still fails the field's ge/le."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return value
    if 0.0 <= value <= 1.0:
        return value
    clamped = min(max(float(value), 0.0), 1.0)
    logger.warning("clamped %s from %s to %s", field, value, clamped)
    return clamped


def clamp_unit(field: str) -> BeforeValidator:
    """`Annotated[float, clamp_unit("x")] = Field(ge=0.0, le=1.0, ...)`: the
    numeric twin of `clip_prose`. The schema keeps its bound (decode-enforced on
    Gemini, a description hint on Claude, whose strict JSON mode cannot enforce
    minimum/maximum), and a finite overshoot (1.02, or 95 meant as a percent)
    is clamped before Pydantic checks it, so it never fails the whole output and
    burns an output retry."""
    return BeforeValidator(lambda v: clamp_unit_value(v, field))
