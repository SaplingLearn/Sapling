"""Prompt caching on the learning-loop slots (spec §13 A137 (a)).

A loop slot on a claude-* model caches its static prefix (tool definitions +
system prompt, the same for every student) with one explicit breakpoint on the
last static system block, when that prefix reaches the 512-token minimum of
Claude Haiku 5.5 and Sonnet 5.5. Never automatic caching: its breakpoint
follows the per-request tail, which these slots never send twice. The Gemini
defaults (A111) and function mode are unchanged. Every request here is built
and captured before the SDK sends it; nothing reaches a network.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from agents import _providers
from agents._providers import EVIDENCE_SLOTS, model_for, provider_model
from agents.deps import SaplingDeps

CACHED = {
    "check_items",
    "check_items_verify",
    "grader",
    "grader_second",
    "loop_tutor_lite",
    "loop_tutor",
    "loop_tutor_deep",
}
UNCACHED = {"session_close", "learning_decision", "check_items_solve"}
#: Claude Haiku 5.5 / Sonnet 5.5's minimum cacheable prefix, in tokens, and the
#: offline estimate's characters per token.
MIN_CACHEABLE_TOKENS = 512
CHARS_PER_TOKEN = 4
EPHEMERAL_5M = {"type": "ephemeral", "ttl": "5m"}


class _Sent(Exception):
    def __init__(self, kwargs):
        super().__init__("captured")
        self.kwargs = kwargs


@pytest.fixture
def captured_create(monkeypatch):
    """The SDK's async `messages.create` raises the request kwargs back."""
    from anthropic import NotGiven, Omit
    from anthropic.resources.beta.messages.messages import AsyncMessages

    async def _capture(self, **kwargs):
        raise _Sent({k: v for k, v in kwargs.items() if not isinstance(v, (Omit, NotGiven))})

    monkeypatch.setattr(AsyncMessages, "create", _capture)


def _request(agent, task: str, model: str = "claude-haiku-5-5", **run) -> dict:
    deps = SaplingDeps(user_id="u", course_id="c", supabase=None, request_id="r")
    with pytest.raises(_Sent) as exc:
        asyncio.run(
            agent.run("a per-request message", deps=deps, model=provider_model(model, task=task), **run)
        )
    return exc.value.kwargs


def _agents():
    """Each slot's agents (a slot's settings reach every agent that runs on it)."""
    from agents.check_items import check_items_agent
    from agents.check_items_key_match import check_items_key_match_agent
    from agents.check_items_solve import check_items_solve_agent
    from agents.check_items_topup import check_items_topup_agent
    from agents.check_items_verify import check_items_verify_agent
    from agents.grader import grader_agent
    from agents.learning_decision import learning_decision_agent
    from agents.loop_tutor import loop_tutor_agent
    from agents.session_close import session_close_agent

    return {
        "check_items": [check_items_agent, check_items_topup_agent],
        "check_items_verify": [check_items_verify_agent],
        "check_items_solve": [check_items_solve_agent, check_items_key_match_agent],
        "grader": [grader_agent],
        "grader_second": [grader_agent],
        "learning_decision": [learning_decision_agent],
        "loop_tutor_lite": [loop_tutor_agent],
        "loop_tutor": [loop_tutor_agent],
        "loop_tutor_deep": [loop_tutor_agent],
        "session_close": [session_close_agent],
    }


def _static_chars(kwargs: dict) -> int:
    """Tool definitions + system text: the prefix a system breakpoint covers."""
    system = kwargs.get("system") or ""
    text = system if isinstance(system, str) else "".join(b.get("text", "") for b in system)
    tools = kwargs.get("tools") or []
    return len(text) + (len(json.dumps(tools, sort_keys=True)) if tools else 0)


def test_the_cached_slots_are_loop_slots_and_every_loop_slot_is_decided():
    assert _providers._ANTHROPIC_CACHED_PREFIX_TASKS == CACHED
    assert CACHED | UNCACHED == set(EVIDENCE_SLOTS)
    assert not CACHED & _providers._ANTHROPIC_CACHED_TASKS  # never automatic as well


@pytest.mark.parametrize("slot", sorted(CACHED | UNCACHED))
def test_a_claude_loop_slot_caches_its_static_prefix_only_when_long_enough(monkeypatch, slot):
    monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)
    monkeypatch.setenv(f"SAPLING_MODEL_{slot.upper()}", "claude-haiku-5-5")
    settings = model_for(slot).settings
    assert settings.get("anthropic_cache_instructions") is (True if slot in CACHED else None)
    assert "anthropic_cache" not in settings


@pytest.mark.parametrize("slot", sorted(CACHED | UNCACHED))
def test_the_measured_prefix_decides_the_slot(captured_create, slot):
    """The decision rests on the measured prefix: a prompt edit that moves a
    slot across the minimum fails here, and the slot is decided again."""
    for agent in _agents()[slot]:
        chars = _static_chars(_request(agent, slot))
        long_enough = chars >= MIN_CACHEABLE_TOKENS * CHARS_PER_TOKEN
        assert long_enough is (slot in CACHED), (slot, agent.name, chars // CHARS_PER_TOKEN)


@pytest.mark.parametrize("slot", sorted(CACHED))
def test_the_breakpoint_is_on_the_last_static_system_block_and_nowhere_else(
    captured_create, slot
):
    for agent in _agents()[slot]:
        kwargs = _request(agent, slot, model="claude-sonnet-5-5")
        blocks = kwargs["system"]
        assert [b.get("cache_control") for b in blocks] == [None] * (len(blocks) - 1) + [
            EPHEMERAL_5M
        ]
        assert "cache_control" not in kwargs  # no automatic breakpoint on the tail
        for message in kwargs["messages"]:
            content = message["content"]
            assert isinstance(content, str) or all("cache_control" not in b for b in content)


@pytest.mark.parametrize("slot", sorted(UNCACHED))
def test_a_slot_below_the_minimum_sends_no_breakpoint(captured_create, slot):
    for agent in _agents()[slot]:
        kwargs = _request(agent, slot)
        assert "cache_control" not in kwargs
        system = kwargs.get("system") or ""
        assert isinstance(system, str) or all("cache_control" not in b for b in system)


def test_the_tutor_breakpoint_covers_its_tools_too(captured_create):
    """Tools render before the system prompt, so the one marker caches both."""
    from agents.loop_tutor import loop_tutor_agent

    kwargs = _request(loop_tutor_agent, "loop_tutor")
    assert kwargs["tools"] and "cache_control" in kwargs["system"][-1]


@pytest.mark.parametrize("slot", sorted(CACHED | UNCACHED))
def test_the_gemini_defaults_and_function_mode_are_unchanged(monkeypatch, slot):
    monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)
    monkeypatch.delenv(f"SAPLING_MODEL_{slot.upper()}", raising=False)
    model = model_for(slot)
    if slot in _providers.LOOP_SLOTS_PENDING_CLAUDE_EVAL:
        assert _providers.provider_for_model(_providers._DEFAULTS[slot]) == "google"
        assert model.settings == _providers._google_settings_for(slot)  # None for a loop slot
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    assert not any(str(k).startswith("anthropic_") for k in (model_for(slot).settings or {}))
