"""Confirms document_notes_agent runs under its own usage budget, not the
shared WORKER_LIMITS every cheap classification/summary task uses."""
from __future__ import annotations

from agents import NOTES_LIMITS, WORKER_LIMITS
from agents.document import _step_notes


def test_notes_limits_is_not_worker_limits():
    assert NOTES_LIMITS is not WORKER_LIMITS


def test_notes_limits_total_tokens_is_generously_larger_than_worker_limits():
    assert NOTES_LIMITS.total_tokens_limit == 300_000
    assert NOTES_LIMITS.total_tokens_limit > WORKER_LIMITS.total_tokens_limit


def test_step_notes_source_uses_notes_limits():
    import inspect

    src = inspect.getsource(_step_notes)
    assert "NOTES_LIMITS" in src
    assert "usage_limits=WORKER_LIMITS" not in src
