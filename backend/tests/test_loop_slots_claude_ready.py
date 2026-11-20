"""The learning-loop slots run on Claude (owner decision 2026-11-19; their
Claude eval pass is still pending, LOOP_SLOTS_PENDING_CLAUDE_EVAL). By default
each sends Claude-shaped settings — no Gemini thinking budget (a 400 on Claude
5.x), no Gemini Flex tier, and the Claude max_tokens ceiling instead of a
Gemini-sized cap that adaptive thinking would overrun. Pointing one back at
Gemini with SAPLING_MODEL_<SLOT>=gemini-* still sends the Gemini shapes,
byte-identical to what they were."""

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


def _flip(monkeypatch, slot: str, model: str = "gemini-2.5-flash-lite") -> None:
    monkeypatch.setenv(f"SAPLING_MODEL_{slot.upper()}", model)


def _claude_shaped(settings) -> bool:
    return settings is None or not any(k in settings for k in _GEMINI_ONLY_KEYS)


def test_slot_provider_follows_the_override(monkeypatch):
    assert slot_provider("grader") == "anthropic"  # the default (eval pending)
    _flip(monkeypatch, "grader")
    assert slot_provider("grader") == "google"


def test_settings_for_slot_picks_the_resolved_providers_shape(monkeypatch):
    google, anthropic = {"g": 1}, {"a": 1}
    assert settings_for_slot("grader", google=google, anthropic=anthropic) is anthropic
    _flip(monkeypatch, "grader")
    assert settings_for_slot("grader", google=google, anthropic=anthropic) is google


def test_every_pending_slot_defaults_to_claude_and_is_reported_unevaluated():
    from agents._providers import PENDING_CLAUDE_EVAL, model_name_for, unevaluated_reason

    for slot in LOOP_SLOTS_PENDING_CLAUDE_EVAL:
        if os.getenv(f"SAPLING_MODEL_{slot.upper()}"):
            continue
        assert slot_provider(slot) == "anthropic", slot
        # Honest until the A111 pass: the guard still says "not evaluated".
        assert unevaluated_reason(slot, model_name_for(slot)) == PENDING_CLAUDE_EVAL, slot


def test_second_opinion_settings(monkeypatch):
    from agents import grader as g

    claude = g._second_opinion_settings()
    assert _claude_shaped(claude)
    assert claude["max_tokens"] == ANTHROPIC_MAX_TOKENS
    _flip(monkeypatch, "grader_second", "gemini-2.5-flash")
    assert g._second_opinion_settings() is g._SECOND_OPINION_SETTINGS  # Gemini: unchanged


def test_check_items_flex_tier_is_gemini_only(monkeypatch):
    from agents.check_items import _flex_settings
    from learning.params import FLEX_TIMEOUT_S

    assert _flex_settings() == {"timeout": FLEX_TIMEOUT_S}
    _flip(monkeypatch, "check_items")
    assert _flex_settings() == {"service_tier": "flex", "timeout": FLEX_TIMEOUT_S}


@pytest.mark.parametrize(
    "tier,slot,model",
    [
        ("lite", "loop_tutor_lite", "gemini-2.5-flash-lite"),
        ("standard", "loop_tutor", "gemini-2.5-flash"),
        ("deep", "loop_tutor_deep", "gemini-2.5-pro"),
    ],
)
def test_loop_tutor_tiers(monkeypatch, tier, slot, model):
    from agents.loop_tutor import tier_run_kwargs

    claude = tier_run_kwargs(tier, tool_choice="none")["model_settings"]
    assert _claude_shaped(claude)
    assert claude["max_tokens"] == ANTHROPIC_MAX_TOKENS
    assert claude["tool_choice"] == "none"  # A18 on the default
    _flip(monkeypatch, slot, model)
    gemini = tier_run_kwargs(tier, tool_choice="none")["model_settings"]
    # the Gemini hard bound (thinking + visible), not Claude's ceiling
    assert "max_tokens" in gemini and gemini["max_tokens"] != ANTHROPIC_MAX_TOKENS
    assert gemini["tool_choice"] == "none"  # A18 survives the flip


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

    claude = _import_time_settings({})
    assert claude["grader_max_tokens"] == ANTHROPIC_MAX_TOKENS
    assert not any(k in claude["grader"] for k in _GEMINI_ONLY_KEYS)
    assert claude["decision"] == []

    gemini = _import_time_settings({
        "SAPLING_MODEL_GRADER": "gemini-2.5-flash-lite",
        "SAPLING_MODEL_LEARNING_DECISION": "gemini-2.5-flash-lite",
    })
    assert gemini["grader_max_tokens"] == GRADER_OUTPUT_MAX_TOKENS
    assert gemini["decision"] == ["google_thinking_config"]
