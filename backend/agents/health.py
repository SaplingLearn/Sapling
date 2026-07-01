"""Gemini connectivity probe agent.

Backs the admin-only ``/api/gemini-test`` health check. It runs through the
same shared ``GoogleProvider`` the production agents use (via
``agents._providers.google_model``), so a green probe means the real agent seam
can reach Gemini — not just that some unrelated key exists.
"""

from __future__ import annotations

from pydantic_ai import Agent

from agents._providers import google_model


# Cheapest model on the shared provider; the probe only needs a round-trip.
health_probe_agent = Agent[None, str](
    model=google_model("gemini-2.5-flash-lite"),
    output_type=str,
    system_prompt="You are a connectivity probe. Reply with exactly the text the user asks for.",
    metadata={"agent": "health_probe"},
)
