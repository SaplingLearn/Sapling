"""`model_for` hands every caller the process's ONE model per slot (#866 Z17).

In real mode `model_for` built a new loop-safe model on every call: a template
provider, then — on the first `.client` read inside the running loop — a
per-loop provider, each with its own httpx pool (and SSL context), never
closed. That is harmless for an agent built once at import, but the loop
tutor's tier (`tier_run_kwargs`, every turn), the grader's second opinion
(each second-opinion, span and context run) and the quiz's item checks
(`quiz_learning._run_check`) call it per RUN, so each run paid a new TLS
handshake and leaked its pools — the pattern `override_model`'s cache was
added to stop. `model_for` now returns one shared model per (resolved model
name, slot), through that same cache: an env flip resolves another name and
so another model, and the A128 guard still notes every resolution. Function
mode (the E2E seam) is unchanged.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from agents import _providers
from agents._providers import model_for


@pytest.fixture
def real_mode(monkeypatch):
    monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)
    for slot in ("grader_second", "loop_tutor", "quiz_check", "classifier"):
        monkeypatch.delenv(f"SAPLING_MODEL_{slot.upper()}", raising=False)
    built: list[tuple[str, str | None]] = []
    real = _providers.provider_model

    def counting(name, **kw):
        built.append((name, kw.get("task")))
        return real(name, **kw)

    monkeypatch.setattr(_providers, "provider_model", counting)
    _providers.clear_override_model_cache()
    return built


def test_model_for_builds_one_model_per_slot_and_name(real_mode, monkeypatch):
    first = model_for("grader_second")
    assert model_for("grader_second") is first
    assert real_mode.count(("claude-sonnet-5-5", "grader_second")) == 1  # built once
    monkeypatch.setenv("SAPLING_MODEL_GRADER_SECOND", "claude-haiku-5-5")
    flipped = model_for("grader_second")
    assert flipped is not first and flipped.model_name == "claude-haiku-5-5"
    assert model_for("loop_tutor") is not model_for("grader_second")  # per slot


def test_a_shared_model_keeps_one_provider_per_event_loop(real_mode):
    """Two runs on the persistent loop share the per-loop provider (one pool)."""
    seen = []

    async def two_runs():
        seen.append(model_for("loop_tutor")._provider_for_current_loop())
        seen.append(model_for("loop_tutor")._provider_for_current_loop())

    asyncio.run(two_runs())
    assert seen[0] is seen[1]


def test_the_per_run_sites_reuse_the_slot_model(real_mode, monkeypatch):
    from agents import grader as g
    from agents.loop_tutor import tier_run_kwargs

    assert tier_run_kwargs("standard")["model"] is tier_run_kwargs("standard")["model"]
    assert tier_run_kwargs("deep")["model"] is tier_run_kwargs("deep")["model"]

    models = []

    async def fake_run(message, **kw):
        models.append(kw.get("model"))
        raise RuntimeError("stop after the model is chosen")

    monkeypatch.setattr(g.grader_agent, "run", fake_run)
    monkeypatch.setattr(g.ai_budget, "check", lambda *a, **k: g.ai_budget._NORMAL)
    deps = type("D", (), {"user_id": "u1", "feature": "tutor", "session_id": None, "course_id": None})()
    for _ in range(2):
        with pytest.raises(RuntimeError):
            asyncio.run(g._run_once("m", deps, second_opinion=True))
    assert models[0] is models[1] is model_for("grader_second")

    from services import quiz_learning

    drafted = []

    async def fake_drafting(agent, prompt, **kw):
        drafted.append(kw["model"])

    monkeypatch.setattr("agents.check_items.run_drafting", fake_drafting)
    for _ in range(2):
        asyncio.run(quiz_learning._run_check(AsyncMock(), "p", deps=None, feature="quiz_check_verify"))
    assert drafted[0] is drafted[1] is model_for("quiz_check")
    for slot in ("loop_tutor", "loop_tutor_deep", "grader_second", "quiz_check"):
        assert sum(task == slot for _, task in real_mode) == 1, slot  # one build per slot


def test_function_mode_still_builds_the_seam_model(monkeypatch):
    from pydantic_ai.models.function import FunctionModel

    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    assert isinstance(model_for("grader_second"), FunctionModel)
