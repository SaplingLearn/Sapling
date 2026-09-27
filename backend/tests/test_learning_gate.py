"""learning.gate truth table (spec §7). Fail closed on every error."""

from __future__ import annotations

import pytest
from test_learning_loop_invariants import db_client_calls, reload_gate


def _reload(monkeypatch, env_value: str | None):
    """Hermetic: ignores backend/.env and restores config + gate afterwards
    (see reload_gate)."""
    return reload_gate(monkeypatch, env_value)


class _Table:
    def __init__(self, rows=None, raises=None):
        self.rows, self.raises, self.calls = rows, raises, []

    def select(self, cols, filters=None):
        self.calls.append((cols, filters))
        if self.raises:
            raise self.raises
        return self.rows


@pytest.mark.parametrize("env_value", [None, "false", "FALSE", "0", "", "yes"])
def test_env_off_is_false_and_reads_nothing(monkeypatch, env_value):
    gate = _reload(monkeypatch, env_value)
    t = _Table(rows=[{"learning_loop_beta": True}])
    monkeypatch.setattr(gate, "table", lambda name: t)
    before = db_client_calls()
    assert gate.learning_loop_active("user_andres") is False
    assert t.calls == []
    assert db_client_calls()[len(before) :] == [], "flag off, yet the DB client was called"


@pytest.mark.parametrize("env_value", ["true", "TRUE", "True"])
def test_env_on_row_true_is_true(monkeypatch, env_value):
    gate = _reload(monkeypatch, env_value)
    t = _Table(rows=[{"learning_loop_beta": True}])
    monkeypatch.setattr(gate, "table", lambda name: t)
    assert gate.learning_loop_active("user_andres") is True
    assert t.calls == [("learning_loop_beta", {"user_id": "eq.user_andres"})]


def test_env_on_row_false_is_false(monkeypatch):
    gate = _reload(monkeypatch, "true")
    monkeypatch.setattr(gate, "table", lambda name: _Table(rows=[{"learning_loop_beta": False}]))
    assert gate.learning_loop_active("user_andres") is False


def test_env_on_missing_row_is_false(monkeypatch):
    gate = _reload(monkeypatch, "true")
    monkeypatch.setattr(gate, "table", lambda name: _Table(rows=[]))
    assert gate.learning_loop_active("user_andres") is False


def test_env_on_missing_key_is_false(monkeypatch):
    gate = _reload(monkeypatch, "true")
    monkeypatch.setattr(gate, "table", lambda name: _Table(rows=[{"user_id": "user_andres"}]))
    assert gate.learning_loop_active("user_andres") is False


def test_read_error_fails_closed(monkeypatch, caplog):
    gate = _reload(monkeypatch, "true")
    monkeypatch.setattr(gate, "table", lambda name: _Table(raises=RuntimeError("pg down")))
    with caplog.at_level("WARNING"):
        assert gate.learning_loop_active("user_andres") is False
    assert any("learning_loop_active" in r.getMessage() for r in caplog.records)
