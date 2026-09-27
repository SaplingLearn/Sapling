"""LLM token-usage normalization and cost computation (issue #118).

Two concerns live here, kept separate from the write path
(``services/events_service.py``) so the persistence layer stays provider-
agnostic:

1. ``normalize_usage`` — different SDKs name their token fields differently
   (Pydantic AI's ``RunUsage`` uses ``input_tokens``/``output_tokens``; older
   builds used ``request_tokens``/``response_tokens``; Gemini's
   ``usage_metadata`` uses ``prompt_token_count``/``candidates_token_count``).
   This reduces any of them to a single ``prompt``/``completion``/``total``
   dict before the row is persisted.

2. ``cost_usd`` — a small, editable per-1K-token price map. Known models get a
   computed cost; unknown models return ``None`` (persisted as SQL NULL) and
   emit a one-time warning so an un-priced model surfaces in the logs without
   spamming one line per call.
"""

from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

logger = logging.getLogger("sapling.llm_pricing")


# Per-1,000-token USD prices as ``(input_rate, output_rate)``. Sourced from
# Google Gemini API list pricing (and TypeSafe's, for Jev); kept deliberately small and editable. A model
# missing here is not an error — its usage is still recorded, just with
# ``cost_usd = NULL``. Update this map (not the call sites) when prices change
# or a new model ships.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gemini-2.5-pro": (0.00125, 0.010),
    "gemini-2.5-flash": (0.0003, 0.0025),
    "gemini-2.5-flash-lite": (0.0001, 0.0004),
    "gemini-3.1-flash-lite": (0.00025, 0.0015),
    "gemini-2.0-flash": (0.0001, 0.0004),
    "gemini-2.0-flash-lite": (0.000075, 0.0003),
    # TypeSafe Jev (#642, ADR 0027; provider="typesafe" on the llm_usage row).
    # docs.typesafe.ai/models: $0.042 per 1M input tokens, output tokens free.
    # The response reports the versioned id; the aliases are priced too so a
    # row is never NULL-costed because an operator set SAPLING_JEV_MODEL to
    # one. Pricing may be launch-subsidised — see the ADR's vendor-risk note.
    "jev-1.13.0": (0.000042, 0.0),
    "jev-latest": (0.000042, 0.0),
    "jev-preview": (0.000042, 0.0),
}

#: Fractional digits of a stored cost — llm_usage.cost_usd is NUMERIC(18,10)
#: (migration 20260927043405). Six (the old NUMERIC(12,6)) rounded the
#: decision seam's micro-dollar calls: one Jev token is $0.000000042, so a
#: 653-token call ($0.000027426) was stored as 0.000027 and a sub-12-token call
#: as $0. cost_usd() quantizes to this scale and the admin rollups round to
#: it, so a real call's cost is stored and displayed as computed.
COST_SCALE = 10
_COST_QUANTUM = Decimal(1).scaleb(-COST_SCALE)

# Models we've already warned about — so an un-priced model logs once, not
# once per call. Module-level (per-process); tests reset entries as needed.
_warned_models: set[str] = set()

# Token-field aliases across the SDKs we touch, in priority order. First
# non-None hit wins.
_PROMPT_FIELDS = ("prompt_tokens", "input_tokens", "request_tokens", "prompt_token_count")
_COMPLETION_FIELDS = (
    "completion_tokens", "output_tokens", "response_tokens", "candidates_token_count",
)
_TOTAL_FIELDS = ("total_tokens", "total_token_count")


def _read_int(usage: Any, names: tuple[str, ...]) -> int:
    """Return the first present, int-coercible field in ``names`` (attr or key).

    Missing / None / non-numeric fields are skipped; nothing matches → 0.
    """
    for name in names:
        value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def normalize_usage(usage: Any) -> dict[str, int]:
    """Reduce any supported usage object/dict to prompt/completion/total ints.

    Handles Pydantic AI ``RunUsage`` (both current input/output and legacy
    request/response naming), Gemini ``usage_metadata``, and a plain dict that
    is already normalized. ``total`` is derived from prompt + completion when
    the source reports it as zero or omits it.
    """
    if usage is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    prompt = _read_int(usage, _PROMPT_FIELDS)
    completion = _read_int(usage, _COMPLETION_FIELDS)
    total = _read_int(usage, _TOTAL_FIELDS)
    if total <= 0:
        total = prompt + completion
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


def _canonical_model(model: str) -> str:
    """Strip a provider qualifier so 'google-gla:gemini-2.5-flash' matches.

    Pydantic AI may report a provider-prefixed model name; the price map is
    keyed on the bare Gemini model id.
    """
    return model.rsplit(":", 1)[-1].strip() if model else model


def cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Compute USD cost for a call, or ``None`` if the model isn't priced.

    Rounds to ``COST_SCALE`` (10) decimal places, half-up, to match
    ``llm_usage.cost_usd numeric(18,10)``. An unknown model returns ``None``
    and warns once.
    """
    rates = MODEL_PRICING.get(model) or MODEL_PRICING.get(_canonical_model(model))
    if rates is None:
        # SAPLING_MODEL_MODE=function runs (the e2e/CI seam) report the model
        # as 'function:<task>' — a deliberate free stand-in, not an unpriced
        # real model. Record the row with cost NULL and stay silent: warning
        # here would emit one line per task on every e2e run. Real unknown
        # models keep the one-time warning below.
        if model and model.startswith("function:"):
            return None
        if model not in _warned_models:
            _warned_models.add(model)
            logger.warning(
                "No pricing entry for model %r; llm_usage.cost_usd will be NULL. "
                "Add it to services/llm_pricing.MODEL_PRICING to enable cost rollups.",
                model,
            )
        return None

    in_rate, out_rate = rates
    cost = (
        Decimal(str(in_rate)) * Decimal(int(prompt_tokens))
        + Decimal(str(out_rate)) * Decimal(int(completion_tokens))
    ) / Decimal(1000)
    return float(cost.quantize(_COST_QUANTUM, rounding=ROUND_HALF_UP))
