"""Unit tests for services/llm_pricing.py — token-field normalization and
cost computation (issue #118).

Normalization is exercised against a *fake Pydantic AI result usage* object
and a *fake Gemini usage_metadata* object, per the success criteria: the two
SDKs name their token fields differently and both must reduce to the same
prompt/completion/total triple before persistence.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from services import llm_pricing


# ── Fakes mirroring the two real SDK shapes ─────────────────────────────────


@dataclass
class FakePydanticUsage:
    """Mirror of pydantic_ai.usage.RunUsage (v2.x): input/output/total."""

    input_tokens: int
    output_tokens: int
    total_tokens: int


@dataclass
class FakeLegacyPydanticUsage:
    """Older Pydantic AI naming the issue references: request/response."""

    request_tokens: int
    response_tokens: int
    total_tokens: int


@dataclass
class FakeGeminiUsageMetadata:
    """Mirror of google.genai response.usage_metadata."""

    prompt_token_count: int
    candidates_token_count: int
    total_token_count: int


# ── normalize_usage ─────────────────────────────────────────────────────────


def test_normalize_pydantic_ai_usage():
    usage = FakePydanticUsage(input_tokens=100, output_tokens=40, total_tokens=140)
    assert llm_pricing.normalize_usage(usage) == {
        "prompt_tokens": 100,
        "completion_tokens": 40,
        "total_tokens": 140,
    }


def test_normalize_legacy_pydantic_ai_usage():
    usage = FakeLegacyPydanticUsage(request_tokens=7, response_tokens=3, total_tokens=10)
    assert llm_pricing.normalize_usage(usage) == {
        "prompt_tokens": 7,
        "completion_tokens": 3,
        "total_tokens": 10,
    }


def test_normalize_gemini_usage_metadata():
    usage = FakeGeminiUsageMetadata(
        prompt_token_count=200, candidates_token_count=55, total_token_count=255,
    )
    assert llm_pricing.normalize_usage(usage) == {
        "prompt_tokens": 200,
        "completion_tokens": 55,
        "total_tokens": 255,
    }


def test_normalize_derives_total_when_missing_or_zero():
    """A provider may omit/zero the total; we derive prompt + completion."""
    usage = FakeGeminiUsageMetadata(
        prompt_token_count=10, candidates_token_count=5, total_token_count=0,
    )
    assert llm_pricing.normalize_usage(usage)["total_tokens"] == 15


def test_normalize_handles_none_and_missing_fields():
    assert llm_pricing.normalize_usage(None) == {
        "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
    }
    # A gemini metadata whose candidates count came back None (filtered reply).
    usage = FakeGeminiUsageMetadata(
        prompt_token_count=12, candidates_token_count=None, total_token_count=12,
    )
    assert llm_pricing.normalize_usage(usage) == {
        "prompt_tokens": 12, "completion_tokens": 0, "total_tokens": 12,
    }


def test_normalize_accepts_plain_dict():
    usage = {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}
    assert llm_pricing.normalize_usage(usage) == usage


# ── cost_usd ────────────────────────────────────────────────────────────────


def test_cost_for_known_model():
    # gemini-2.5-flash: (0.0003 in, 0.0025 out) per 1K tokens.
    # 1000 prompt -> 0.0003 ; 1000 completion -> 0.0025 ; total 0.0028.
    cost = llm_pricing.cost_usd("gemini-2.5-flash", 1000, 1000)
    assert cost == pytest.approx(0.0028)


def test_cost_for_known_model_rounds_to_six_dp():
    cost = llm_pricing.cost_usd("gemini-2.5-flash-lite", 1, 1)
    # (0.0001 + 0.0004)/1000 = 0.0000005 -> quantized to 6dp = 0.000001 (half-up)
    assert cost == pytest.approx(0.000001)


def test_cost_for_unknown_model_returns_none_and_warns_once(caplog):
    llm_pricing._warned_models.discard("totally-made-up-model")
    with caplog.at_level("WARNING"):
        assert llm_pricing.cost_usd("totally-made-up-model", 100, 100) is None
        assert llm_pricing.cost_usd("totally-made-up-model", 100, 100) is None
    warnings = [r for r in caplog.records if "totally-made-up-model" in r.getMessage()]
    assert len(warnings) == 1, "unknown model must warn exactly once"


def test_cost_strips_provider_prefix():
    """Pydantic AI may report a provider-qualified name like 'google-gla:...'."""
    plain = llm_pricing.cost_usd("gemini-2.5-flash", 1000, 0)
    prefixed = llm_pricing.cost_usd("google-gla:gemini-2.5-flash", 1000, 0)
    assert prefixed == plain


def test_cost_for_function_mode_model_is_none_and_silent(caplog):
    """SAPLING_MODEL_MODE=function runs report 'function:<task>' models.

    They are deliberate free stand-ins (the e2e/CI seam), not unpriced real
    models: cost is NULL and NO warning fires — a warning here would spam
    every e2e run, once per task.
    """
    llm_pricing._warned_models.clear()
    with caplog.at_level("WARNING"):
        assert llm_pricing.cost_usd("function:chat_tutor", 100, 100) is None
        assert llm_pricing.cost_usd("function:quiz", 100, 100) is None
    assert not caplog.records, "function:* models must not warn"
    assert "function:chat_tutor" not in llm_pricing._warned_models
