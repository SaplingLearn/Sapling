"""The eval judges' model + settings, on whichever provider the name implies.

The loop's rung and confront judges grade served tutor turns. Every loop slot
runs on Claude (owner decision 2026-11-19), so the judges default to Claude
Opus 5.5 — a different, stronger model than the Haiku/Sonnet tutor tiers they
judge. A `gemini-*` override (RUNG_JUDGE_MODEL / CONFRONT_JUDGE_MODEL) still
works and gets the Gemini thinking-budget shape; Claude 5.x rejects a thinking
budget and sampling settings, so the Claude shape is effort + a Claude-sized
max_tokens (adaptive thinking counts against it).
"""

from __future__ import annotations

from typing import Any

DEFAULT_JUDGE_MODEL = "claude-opus-5-5"


def judge_model_and_settings(name: str, *, thinking_budget: int, max_tokens: int) -> tuple[Any, Any]:
    from agents._providers import ANTHROPIC_MAX_TOKENS, provider_for_model, provider_model

    # No cross-provider fallback: a judgement must come from the model the
    # cassette records, or a stale judgement could score.
    model = provider_model(name, fallback=False)
    if provider_for_model(name) == "anthropic":
        from pydantic_ai.models.anthropic import AnthropicModelSettings

        return model, AnthropicModelSettings(max_tokens=ANTHROPIC_MAX_TOKENS, anthropic_effort="low")
    from google.genai.types import ThinkingConfig
    from pydantic_ai.models.google import GoogleModelSettings

    return model, GoogleModelSettings(
        google_thinking_config=ThinkingConfig(thinking_budget=thinking_budget),
        max_tokens=max_tokens,
        temperature=0.0,
    )
