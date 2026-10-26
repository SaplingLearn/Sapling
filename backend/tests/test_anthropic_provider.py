"""ADR 0030: the Anthropic half of `agents/_providers.py`.

Every agent slot defaults to Claude. These pin the pieces that make that work
on the pinned pydantic-ai 1.x line (which predates Claude 5.x):

- the provider is inferred from the model name, and a typo fails loudly;
- the Claude 5.x profile turns on native (constrained-JSON) structured output
  and turns off forced `tool_choice` and sampling settings;
- per-task model-level settings (`max_tokens`, `effort`);
- the request actually sent to the Anthropic SDK — captured at the SDK's
  `messages.create`, so nothing leaves the process. This is the regression
  test for the first live run's 400: a profile-default native schema went out
  non-strict, without `additionalProperties: false`.
"""
from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel

from agents import _providers
from agents._providers import (
    _ANTHROPIC_EFFORT,
    _ANTHROPIC_MAX_TOKENS,
    _DEFAULTS,
    _anthropic_profile,
    anthropic_key_missing,
    model_for,
    provider_for_model,
    provider_model,
)


# ── Provider inference ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "provider"),
    [
        ("claude-haiku-5-5", "anthropic"),
        ("claude-sonnet-5-5", "anthropic"),
        ("anthropic:claude-opus-5-5", "anthropic"),
        ("gemini-2.5-flash-lite", "google"),
        ("google-gla:gemini-2.5-pro", "google"),
    ],
)
def test_provider_is_inferred_from_the_model_name(name, provider):
    assert provider_for_model(name) == provider


@pytest.mark.parametrize("name", ["gpt-5", "haiku", "", "claud-haiku-5-5"])
def test_unknown_model_name_is_a_config_error(name):
    with pytest.raises(ValueError, match="cannot infer the provider"):
        provider_for_model(name)


def test_unknown_env_override_fails_at_model_construction(monkeypatch):
    """A typo'd SAPLING_MODEL_* must not silently route to some default."""
    monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)
    monkeypatch.setenv("SAPLING_MODEL_QUIZ", "claude-haikuu")  # still claude-*
    assert isinstance(model_for("quiz"), AnthropicModel)
    monkeypatch.setenv("SAPLING_MODEL_QUIZ", "haiku-5-5")
    with pytest.raises(ValueError):
        model_for("quiz")


def test_every_default_slot_is_claude():
    """The swap itself: no agent slot still defaults to Gemini."""
    assert {provider_for_model(m) for m in _DEFAULTS.values()} == {"anthropic"}
    assert set(_ANTHROPIC_EFFORT) == set(_DEFAULTS), (
        "every slot needs an explicit Claude effort level"
    )


def test_provider_model_strips_a_provider_qualifier():
    m = provider_model("anthropic:claude-haiku-5-5")
    assert isinstance(m, AnthropicModel)
    assert m.model_name == "claude-haiku-5-5"


def test_a_gemini_slot_still_builds_a_google_model(monkeypatch):
    monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)
    monkeypatch.setenv("SAPLING_MODEL_SYLLABUS", "gemini-2.5-flash")
    m = model_for("syllabus")
    assert isinstance(m, GoogleModel)
    assert m.model_name == "gemini-2.5-flash"


# ── Claude 5.x profile ───────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"])
def test_claude_5x_profile(name):
    p = _anthropic_profile(name)
    assert p.supports_json_schema_output is True
    assert p.default_structured_output_mode == "native"
    assert p.anthropic_supports_forced_tool_choice is False
    assert p.anthropic_disallows_sampling_settings is True
    assert p.anthropic_disallows_budget_thinking is True
    assert p.anthropic_supports_effort is True
    # The provider's JSON-schema transformer must survive the override — it
    # is what makes a strict schema acceptable to Anthropic.
    assert p.json_schema_transformer is not None


def test_pre_5x_claude_keeps_pydantic_ais_own_profile():
    """Only names pydantic-ai doesn't know get the 5.x overrides."""
    p = _anthropic_profile("claude-sonnet-4-6")
    assert p.anthropic_disallows_sampling_settings is False
    assert p.default_structured_output_mode == "native"  # it supports JSON output


# ── Per-task settings ────────────────────────────────────────────────────


def test_claude_slot_carries_max_tokens_and_effort(monkeypatch):
    monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)
    m = model_for("classifier")
    assert m.settings == {"max_tokens": _ANTHROPIC_MAX_TOKENS, "anthropic_effort": "low"}
    assert model_for("study_guide").settings["anthropic_effort"] == "medium"


def test_only_tool_loop_slots_enable_prompt_caching(monkeypatch):
    """A cache write costs 1.25x input; it pays only where one run sends the
    same prefix several times (the tutor/quiz/note-chat tool loops)."""
    monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)
    for task in ("chat_tutor", "quiz", "note_chat"):
        assert model_for(task).settings.get("anthropic_cache") is True, task
    for task in ("classifier", "summary", "flashcard", "ocr_vision"):
        assert "anthropic_cache" not in model_for(task).settings, task


def test_flashcard_gemini_only_settings_follow_the_slot_to_google(monkeypatch):
    """temperature 0.7 + thinking budget 0 are Gemini-only (Claude 4.7+
    rejects a non-default temperature); they apply only on a gemini-* slot."""
    monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)
    claude = model_for("flashcard")
    assert "temperature" not in (claude.settings or {})
    # Thinking counts against max_tokens on Claude: the legacy 8192 output cap
    # must not shrink the slot's 16K budget (it would truncate a big deck).
    assert claude.settings["max_tokens"] == _ANTHROPIC_MAX_TOKENS
    from agents.flashcard import flashcard_agent
    assert not flashcard_agent.model_settings
    monkeypatch.setenv("SAPLING_MODEL_FLASHCARD", "gemini-2.5-flash")
    gemini = model_for("flashcard")
    assert gemini.settings["temperature"] == 0.7
    assert gemini.settings["max_tokens"] == 8192
    assert gemini.settings["google_thinking_config"].thinking_budget == 0


# ── The request on the wire ──────────────────────────────────────────────


class _Sent(Exception):
    def __init__(self, kwargs):
        super().__init__("captured")
        self.kwargs = kwargs


@pytest.fixture
def captured_create(monkeypatch):
    """Replace the SDK's async beta `messages.create` (the one call pydantic-ai
    makes, streamed or not) with one that raises the request kwargs back."""
    from anthropic import NotGiven, Omit
    from anthropic.resources.beta.messages.messages import AsyncMessages

    async def _capture(self, **kwargs):
        # Drop the SDK's "not sent" sentinels so the assertions see exactly
        # the fields that would reach the wire.
        raise _Sent({
            k: v for k, v in kwargs.items() if not isinstance(v, (Omit, NotGiven))
        })

    monkeypatch.setattr(AsyncMessages, "create", _capture)


def _send(agent: Agent, prompt: str = "hi", **run_kwargs) -> dict:
    with pytest.raises(_Sent) as exc:
        asyncio.run(agent.run(prompt, **run_kwargs))
    return exc.value.kwargs


class _Out(BaseModel):
    label: str = Field(max_length=40, description="a label")
    score: float = Field(ge=0.0, le=1.0)


def test_structured_output_goes_out_as_a_strict_native_schema(captured_create):
    agent = Agent(provider_model("claude-haiku-5-5", task="classifier"), output_type=_Out)
    kw = _send(agent)
    schema = kw["output_config"]["format"]["schema"]
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert schema["additionalProperties"] is False
    # Claude's strict mode rejects numeric/length constraints; the transformer
    # must have moved them out of the schema proper.
    assert "maximum" not in schema["properties"]["score"]
    assert "maxLength" not in schema["properties"]["label"]
    # No output TOOL, therefore no forced tool_choice (a 400 on Opus/Sonnet
    # 5.5, and refused alongside thinking on Haiku 5.5).
    assert not kw.get("tools")
    assert "tool_choice" not in kw
    assert kw["max_tokens"] == _ANTHROPIC_MAX_TOKENS
    assert kw["output_config"]["effort"] == "low"
    assert "temperature" not in kw


def test_tools_plus_structured_output_never_force_tool_choice(captured_create):
    """The quiz agent's shape: function tools AND a typed output."""
    agent = Agent(provider_model("claude-haiku-5-5", task="quiz"), output_type=_Out)

    @agent.tool_plain
    def lookup(topic: str) -> str:
        """Look a topic up."""
        return topic

    kw = _send(agent)
    assert [t["name"] for t in kw["tools"]] == ["lookup"]
    assert kw["tool_choice"]["type"] == "auto"
    assert kw["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert kw["output_config"]["effort"] == "low"


def test_a_stray_temperature_is_dropped_not_sent(captured_create):
    """Claude 4.7+ 400s on a non-default temperature; the 5.x profile makes
    pydantic-ai drop (and warn about) one instead of forwarding it."""
    agent = Agent(provider_model("claude-haiku-5-5"), output_type=str)
    with pytest.warns(UserWarning):
        kw = _send(agent, model_settings={"temperature": 0.7})
    assert "temperature" not in kw


def test_run_level_effort_overrides_the_slot_default(captured_create):
    """routes/learn.py's deep-turn settings ride on top of the model-level
    `low` the chat_tutor slot carries."""
    agent = Agent(provider_model("claude-sonnet-5-5", task="chat_tutor"), output_type=str)
    kw = _send(agent, model_settings={"anthropic_effort": "medium"})
    assert kw["output_config"]["effort"] == "medium"
    assert kw["model"] == "claude-sonnet-5-5"
    assert kw["cache_control"] == {"type": "ephemeral", "ttl": "5m"}, (
        "tool-loop slot must cache (5m TTL — the rate llm_pricing models)"
    )


def test_the_seam_uses_a_dummy_key_when_unset(monkeypatch):
    """Import-time construction must not need a real key (CI, tools)."""
    monkeypatch.setattr(_providers, "ANTHROPIC_API_KEY", "")
    provider = _providers._new_anthropic_provider()
    assert provider.client.api_key == "dummy-key-for-import"


def test_a_blank_key_fails_before_the_request_leaves(monkeypatch, captured_create):
    """APP_ENV=local boots without a key. A Claude call then names the missing
    env var instead of sending the dummy key off for a 401 (`captured_create`
    raising `_Sent` here would mean the request reached the SDK)."""
    from pydantic_ai.exceptions import ModelAPIError

    monkeypatch.setattr(_providers, "ANTHROPIC_API_KEY", "")
    agent = Agent(provider_model("claude-haiku-5-5", task="classifier"), output_type=str)
    with pytest.raises(ModelAPIError, match="ANTHROPIC_API_KEY is not set"):
        asyncio.run(agent.run("hi"))


def test_a_blank_key_fails_a_streamed_run_too(monkeypatch, captured_create):
    """The SSE tutor streams, which goes through `request_stream`."""
    from pydantic_ai.exceptions import ModelAPIError

    monkeypatch.setattr(_providers, "ANTHROPIC_API_KEY", "")
    agent = Agent(provider_model("claude-sonnet-5-5", task="chat_tutor"), output_type=str)

    async def _go():
        async with agent.run_stream("hi") as result:
            await result.get_output()

    with pytest.raises(ModelAPIError, match="ANTHROPIC_API_KEY is not set"):
        asyncio.run(_go())


def test_anthropic_key_missing_only_when_a_real_claude_slot_has_no_key(monkeypatch):
    monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)
    monkeypatch.setattr(_providers, "ANTHROPIC_API_KEY", "")
    assert anthropic_key_missing() is True

    monkeypatch.setattr(_providers, "ANTHROPIC_API_KEY", "sk-ant-test")
    assert anthropic_key_missing() is False

    # Function mode never reaches a provider.
    monkeypatch.setattr(_providers, "ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    assert anthropic_key_missing() is False

    # Every slot rolled back to Gemini needs no Anthropic key.
    monkeypatch.delenv("SAPLING_MODEL_MODE")
    for task in _DEFAULTS:
        monkeypatch.setenv(f"SAPLING_MODEL_{task.upper()}", "gemini-2.5-flash")
    assert anthropic_key_missing() is False


# ── Local bounds (Claude can't enforce maxLength/maxItems at decode) ─────


def test_prose_overshoot_is_clipped_at_a_word_boundary_not_rejected():
    from agents.summary import Summary

    s = Summary(headline="word " * 60, abstract="a", key_points=["a", "b", "c"])
    assert len(s.headline) <= 140
    assert s.headline.endswith("…")
    assert not s.headline[:-1].endswith(" ")


def test_list_overshoot_is_clipped_not_rejected_but_minimums_still_bite():
    from pydantic import ValidationError

    from agents.concept_extraction import ConceptList
    from agents.summary import Summary

    many = [{"name": f"C{i}", "description": "d", "importance": 0.5} for i in range(34)]
    assert len(ConceptList(concepts=many).concepts) == 30
    assert len(Summary(headline="h", abstract="a", key_points=list("abcdefghij")).key_points) == 8
    with pytest.raises(ValidationError):
        Summary(headline="h", abstract="a", key_points=["only one"])


def test_concepts_are_ordered_by_importance_whatever_the_model_sent():
    from agents.concept_extraction import ConceptList

    c = ConceptList(concepts=[
        {"name": "Low", "description": "d", "importance": 0.1},
        {"name": "High", "description": "d", "importance": 0.9},
        {"name": "Mid", "description": "d", "importance": 0.5},
    ])
    assert [x.name for x in c.concepts] == ["High", "Mid", "Low"]


def test_the_per_request_override_model_is_built_once_per_process():
    """The browser sends a fast/smart pref on every tutor turn; a fresh model
    per turn meant fresh, never-closed provider connection pools."""
    from agents._providers import override_model
    from routes.learn import _resolve_model_pref

    a = _resolve_model_pref("smart")
    b = _resolve_model_pref("smart")
    assert a is b
    assert a is override_model("claude-sonnet-5-5", "chat_tutor")
    assert _resolve_model_pref("fast") is not a


def test_api_key_env_follows_the_provider():
    from agents._providers import api_key_env_for_model

    assert api_key_env_for_model("claude-haiku-5-5") == "ANTHROPIC_API_KEY"
    assert api_key_env_for_model("gemini-2.5-flash") == "GEMINI_API_KEY"
