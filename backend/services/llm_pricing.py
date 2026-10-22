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
# Anthropic and Google Gemini API list pricing (and TypeSafe's, for Jev); kept
# deliberately small and editable. A model
# missing here is not an error — its usage is still recorded, just with
# ``cost_usd = NULL``. Update this map (not the call sites) when prices change
# or a new model ships.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # Anthropic first-party list prices (ADR 0030). Haiku 5.5's row is its
    # ≤100K-token-prompt card; longer prompts bill at the
    # `_LONG_PROMPT_PRICING` card below. Thinking tokens arrive inside
    # output_tokens, so they are priced as output — which is what they bill as.
    # Prompt caching (enabled on the tool-loop slots, agents/_providers.py)
    # bills cache reads/writes at multiples of the input rate — see
    # `_CACHE_MULTIPLIERS`.
    "claude-haiku-5-5": (0.0001, 0.0005),
    "claude-sonnet-5-5": (0.002, 0.010),
    "claude-opus-5-5": (0.004, 0.020),
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

#: Model FAMILIES priced by prefix, consulted only when a served id has no
#: exact entry above. Jev responses report the versioned id that actually
#: served (`jev-1.14.0` the day the vendor ships it, whatever alias was
#: requested), and an exact-id-only map would NULL-cost every call from then
#: on — silently, as a warning in the logs — until someone noticed. TypeSafe
#: prices the family, not the build; a new rate gets its own exact entry.
MODEL_FAMILY_PRICING: tuple[tuple[str, tuple[float, float]], ...] = (
    ("jev-", (0.000042, 0.0)),
)

#: Models whose rate card switches above a prompt-length threshold:
#: model -> (threshold_prompt_tokens, (input_rate, output_rate)). Anthropic
#: applies the card per request; a usage row is a whole agent run, so a
#: multi-request run is priced on its SUMMED prompt tokens — an over-estimate
#: only for a run whose individual requests each stayed under the threshold.
_LONG_PROMPT_PRICING: dict[str, tuple[int, tuple[float, float]]] = {
    "claude-haiku-5-5": (100_000, (0.0005, 0.0025)),
}

#: Prompt-cache pricing as ``(read_multiplier, write_multiplier)`` of the input
#: rate, by model-family prefix. Anthropic: reads 0.1x, 5-minute writes 1.25x
#: (the agents use the default 5-minute TTL; a 1-hour TTL writes at 2x and
#: would need its own entry). Families without an entry keep pricing every
#: prompt token at the full input rate — Gemini's implicit-cache discount is
#: not modelled, exactly as before ADR 0030.
_CACHE_MULTIPLIERS: tuple[tuple[str, tuple[float, float]], ...] = (
    ("claude-", (0.1, 1.25)),
)

_CACHE_READ_FIELDS = ("cache_read_tokens", "cache_read_input_tokens")
_CACHE_WRITE_FIELDS = ("cache_write_tokens", "cache_creation_input_tokens")

#: Fractional digits of a stored cost — llm_usage.cost_usd is NUMERIC(18,10)
#: (migration 20261016063803_llm_cost_precision.sql, shipped with this seam). Six (the old NUMERIC(12,6)) rounded the
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


def cache_usage(usage: Any) -> tuple[int, int]:
    """``(cache_read_tokens, cache_write_tokens)`` from a usage object/dict —
    both already INCLUDED in its prompt/input token count (pydantic-ai's
    ``RunUsage.input_tokens`` is uncached + read + write). ``(0, 0)`` when the
    source reports none."""
    if usage is None:
        return 0, 0
    return _read_int(usage, _CACHE_READ_FIELDS), _read_int(usage, _CACHE_WRITE_FIELDS)


def _canonical_model(model: str) -> str:
    """Strip a provider qualifier so 'google-gla:gemini-2.5-flash' matches.

    Pydantic AI may report a provider-prefixed model name; the price map is
    keyed on the bare Gemini model id.
    """
    return model.rsplit(":", 1)[-1].strip() if model else model


def usage_provider(model: str) -> str:
    """The ``llm_usage.provider`` label for a served model name.

    ``anthropic`` / ``gemini`` / ``typesafe`` (Jev) by name, ``function`` for
    the SAPLING_MODEL_MODE=function seam's free stand-ins, ``unknown``
    otherwise. Until ADR 0030 every agent row was hard-labelled ``gemini``;
    deriving the label from the model keeps it honest when a slot is moved
    between providers by an env flip.
    """
    if model and model.startswith("function:"):
        return "function"
    canonical = _canonical_model(model or "")
    if canonical.startswith("claude-"):
        return "anthropic"
    if canonical.startswith("gemini-"):
        return "gemini"
    if canonical.startswith("jev-"):
        return "typesafe"
    return "unknown"


def _rates_for(model: str, prompt_tokens: int = 0) -> tuple[float, float] | None:
    """Exact price entry first (raw, then provider-stripped), then the
    model's family prefix. A model with a long-prompt card switches to it
    above that card's prompt-token threshold."""
    if not model:
        return None
    canonical = _canonical_model(model)
    long_card = _LONG_PROMPT_PRICING.get(canonical)
    if long_card is not None and prompt_tokens > long_card[0]:
        return long_card[1]
    rates = MODEL_PRICING.get(model) or MODEL_PRICING.get(canonical)
    if rates is not None:
        return rates
    for prefix, family_rates in MODEL_FAMILY_PRICING:
        if canonical.startswith(prefix):
            return family_rates
    return None


def cost_usd(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    *,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float | None:
    """Compute USD cost for a call, or ``None`` if the model isn't priced.

    ``cache_read_tokens`` / ``cache_write_tokens`` are the parts of
    ``prompt_tokens`` served from / written to the provider's prompt cache;
    for a family in ``_CACHE_MULTIPLIERS`` they are re-priced at its
    multiples of the input rate, otherwise they cost like any prompt token.

    Rounds to ``COST_SCALE`` (10) decimal places, half-up, to match
    ``llm_usage.cost_usd numeric(18,10)``. An unknown model returns ``None``
    and warns once.
    """
    rates = _rates_for(model, int(prompt_tokens))
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
    read, write = int(cache_read_tokens), int(cache_write_tokens)
    read_mult = write_mult = 1.0
    canonical = _canonical_model(model)
    for prefix, multipliers in _CACHE_MULTIPLIERS:
        if canonical.startswith(prefix):
            read_mult, write_mult = multipliers
            break
    uncached = max(int(prompt_tokens) - read - write, 0)
    in_rate_d = Decimal(str(in_rate))
    cost = (
        in_rate_d * Decimal(uncached)
        + in_rate_d * Decimal(str(read_mult)) * Decimal(read)
        + in_rate_d * Decimal(str(write_mult)) * Decimal(write)
        + Decimal(str(out_rate)) * Decimal(int(completion_tokens))
    ) / Decimal(1000)
    return float(cost.quantize(_COST_QUANTUM, rounding=ROUND_HALF_UP))
