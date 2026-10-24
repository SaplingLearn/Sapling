"""LLM connectivity probe agent.

Backs the admin-only ``/api/gemini-test`` health check (the route name
predates the Anthropic swap, ADR 0030, and is kept for existing callers). It
runs through the same loop-safe provider construction the production agents
use (via ``agents._providers.provider_model``), so a green probe means the
real agent seam can reach the model provider — not just that some unrelated
key exists.
"""

from __future__ import annotations

from pydantic_ai import Agent

from agents._providers import HEALTH_PROBE_MODEL, provider_model


# Cheapest model on the shared provider; the probe only needs a round-trip.
health_probe_agent = Agent[None, str](
    model=provider_model(HEALTH_PROBE_MODEL),
    output_type=str,
    system_prompt="You are a connectivity probe. Reply with exactly the text the user asks for.",
    metadata={"agent": "health_probe"},
)
