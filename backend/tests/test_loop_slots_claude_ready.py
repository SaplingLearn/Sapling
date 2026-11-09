"""The learning-loop slots are Claude-ready (ADR 0030 exception, CLAUDE.md):
each still DEFAULTS to Gemini (LOOP_SLOTS_PENDING_CLAUDE_EVAL), but flipping
one with SAPLING_MODEL_<SLOT>=claude-* must send Claude-shaped settings — no
Gemini thinking budget (a 400 on Claude 5.x), no Gemini Flex tier, and the
Claude max_tokens ceiling instead of a Gemini-sized cap that adaptive thinking
would overrun. The Gemini shapes stay byte-identical to what they were."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agents._providers import (
    ANTHROPIC_MAX_TOKENS,
    LOOP_SLOTS_PENDING_CLAUDE_EVAL,
    settings_for_slot,
    slot_provider,
)

BACKEND = Path(__file__).resolve().parents[1]
_GEMINI_ONLY_KEYS = ("google_thinking_config", "service_tier")


def _flip(monkeypatch, slot: str, model: str = "claude-haiku-5-5") -> None:
    monkeypatch.setenv(f"SAPLING_MODEL_{slot.upper()}", model)


def _claude_shaped(settings) -> bool:
    return settings is None or not any(k in settings for k in _GEMINI_ONLY_KEYS)


def test_slot_provider_follows_the_override(monkeypatch):
    assert slot_provider("grader") == "google"  # the default, pending its eval
    _flip(monkeypatch, "grader")
    assert slot_provider("grader") == "anthropic"


def test_settings_for_slot_picks_the_resolved_providers_shape(monkeypatch):
    google, anthropic = {"g": 1}, {"a": 1}
    assert settings_for_slot("grader", google=google, anthropic=anthropic) is google
    _flip(monkeypatch, "grader")
    assert settings_for_slot("grader", google=google, anthropic=anthropic) is anthropic


def test_every_pending_slot_still_defaults_to_gemini():
    for slot in LOOP_SLOTS_PENDING_CLAUDE_EVAL:
        if os.getenv(f"SAPLING_MODEL_{slot.upper()}"):
            continue
        assert slot_provider(slot) == "google", slot


def test_second_opinion_settings(monkeypatch):
    from agents import grader as g

    assert g._second_opinion_settings() is g._SECOND_OPINION_SETTINGS  # Gemini: unchanged
    _flip(monkeypatch, "grader_second", "claude-sonnet-5-5")
    claude = g._second_opinion_settings()
    assert _claude_shaped(claude)
    assert claude["max_tokens"] == ANTHROPIC_MAX_TOKENS


def test_check_items_flex_tier_is_gemini_only(monkeypatch):
    from agents.check_items import _flex_settings
    from learning.params import FLEX_TIMEOUT_S

    assert _flex_settings() == {"service_tier": "flex", "timeout": FLEX_TIMEOUT_S}
    _flip(monkeypatch, "check_items")
    assert _flex_settings() == {"timeout": FLEX_TIMEOUT_S}


@pytest.mark.parametrize(
    "tier,slot,model",
    [
        ("lite", "loop_tutor_lite", "claude-haiku-5-5"),
        ("standard", "loop_tutor", "claude-haiku-5-5"),
        ("deep", "loop_tutor_deep", "claude-sonnet-5-5"),
    ],
)
def test_loop_tutor_tiers(monkeypatch, tier, slot, model):
    from agents.loop_tutor import tier_run_kwargs

    gemini = tier_run_kwargs(tier)["model_settings"]
    assert "max_tokens" in gemini  # the Gemini hard bound (thinking + visible)
    _flip(monkeypatch, slot, model)
    claude = tier_run_kwargs(tier, tool_choice="none")["model_settings"]
    assert _claude_shaped(claude)
    assert claude["max_tokens"] == ANTHROPIC_MAX_TOKENS
    assert claude["tool_choice"] == "none"  # A18 survives the flip


_PROBE = """
import json
from agents import grader, learning_decision
print(json.dumps({
    "grader": sorted(grader.grader_agent.model_settings),
    "grader_max_tokens": grader.grader_agent.model_settings.get("max_tokens"),
    "decision": sorted(learning_decision.learning_decision_agent.model_settings or {}),
}))
"""


def _import_time_settings(env: dict) -> dict:
    """Agent-level settings are fixed at import (the slot resolves at boot), so a
    flip is read in a fresh interpreter, never by reloading shared agents."""
    out = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=BACKEND,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_agent_level_settings_follow_the_slot_at_import():
    from learning.params import GRADER_OUTPUT_MAX_TOKENS

    gemini = _import_time_settings({})
    assert gemini["grader_max_tokens"] == GRADER_OUTPUT_MAX_TOKENS
    assert gemini["decision"] == ["google_thinking_config"]

    claude = _import_time_settings({
        "SAPLING_MODEL_GRADER": "claude-haiku-5-5",
        "SAPLING_MODEL_LEARNING_DECISION": "claude-haiku-5-5",
    })
    assert claude["grader_max_tokens"] == ANTHROPIC_MAX_TOKENS
    assert not any(k in claude["grader"] for k in _GEMINI_ONLY_KEYS)
    assert claude["decision"] == []
