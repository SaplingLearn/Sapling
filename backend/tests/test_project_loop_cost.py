"""scripts/project_loop_cost.py (spec §13 A137): the offline cost projection's
pricing and mixes, hand-checked. The measurement itself replays the eval
cassettes; nothing here calls a model."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture(scope="module")
def projection():
    saved = list(sys.path)
    sys.path.insert(0, str(SCRIPTS))
    try:
        return importlib.import_module("project_loop_cost")
    finally:
        sys.path[:] = saved


def test_every_mix_keeps_the_independent_slots_independent(projection):
    from agents._providers import EVIDENCE_SLOTS, INDEPENDENT_SLOTS

    for name, mix in projection.mixes().items():
        assert set(mix) == set(EVIDENCE_SLOTS), name
        for slot, other, rule in INDEPENDENT_SLOTS:
            assert mix[slot] != mix[other], (name, slot, rule)


def test_an_uncached_haiku_call(projection, monkeypatch):
    monkeypatch.setattr(projection, "CLAUDE_THINKING", {"low": 100, "medium": 0, "high": 0})
    call = projection.Call("grader", prefix=1000, input=500, output=100)  # grader: effort low
    usd, thinking = projection.call_cost(call, projection.HAIKU, cached=False, calls=1)
    # (1500 × $0.10 + (100 + 100 thinking) × $0.50) per MTok
    assert usd == pytest.approx((1500 * 0.10 + 200 * 0.50) / 1e6)
    assert thinking == pytest.approx(100 * 0.50 / 1e6)


def test_a_cached_slot_writes_its_prefix_once_then_reads_it(projection, monkeypatch):
    monkeypatch.setattr(projection, "CLAUDE_THINKING", {"low": 100, "medium": 0, "high": 0})
    call = projection.Call("grader", prefix=1000, input=500, output=100)
    usd, _ = projection.call_cost(call, projection.HAIKU, cached=True, calls=3)
    write = (500 * 0.10 + 1000 * 0.10 * 1.25 + 200 * 0.50) / 1e6
    read = (500 * 0.10 + 1000 * 0.10 * 0.1 + 200 * 0.50) / 1e6
    assert usd == pytest.approx(write + 2 * read)
    monkeypatch.setattr(projection, "STEADY_TRAFFIC", True)
    usd, _ = projection.call_cost(call, projection.HAIKU, cached=True, calls=3)
    assert usd == pytest.approx(3 * read)


@pytest.mark.parametrize(
    "slot,model", [("session_close", "claude-haiku-5-5"), ("grader", "gemini-2.5-flash-lite")]
)
def test_caching_applies_only_to_a_cached_claude_slot(projection, slot, model):
    call = projection.Call(slot, prefix=1000, input=500, output=100)
    plain, _ = projection.call_cost(call, model, cached=False, calls=3)
    cached, _ = projection.call_cost(call, model, cached=True, calls=3)
    assert cached == pytest.approx(plain)


def test_the_deep_gemini_tier_carries_its_thinking_budget(projection):
    call = projection.Call("loop_tutor_deep", prefix=0, input=0, output=0)
    usd, thinking = projection.call_cost(call, "gemini-2.5-pro", cached=False, calls=1)
    assert usd == thinking == pytest.approx(projection.GEMINI_PRO_THINKING * 10.0 / 1e6)


def test_the_script_refuses_anything_but_replay(projection, monkeypatch):
    monkeypatch.setenv("SAPLING_EVAL_MODE", "record")
    with pytest.raises(SystemExit, match="replay"):
        projection._guard()
