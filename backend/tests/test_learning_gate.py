"""learning.gate truth table (spec §7, post-launch: env-only kill switch, default ON)."""

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


# PKG-14b (spec §7 "After launch", §11.5): the env var is a kill switch that
# defaults ON, and the gate reads no table — the per-user toggle is retired.


@pytest.mark.parametrize(
    "env_value,expected",
    [
        (None, True),
        ("", True),
        ("true", True),
        ("1", True),
        ("false", False),
        ("FALSE", False),
        ("0", False),
        ("off", False),
        ("no", False),
    ],
)
def test_env_flag_defaults_on(monkeypatch, env_value, expected):
    import config

    _reload(monkeypatch, env_value)
    assert config.LEARNING_LOOP_ENABLED is expected


@pytest.mark.parametrize("env_value", ["false", "FALSE", " False ", "0", "off", "no"])
def test_env_off_is_false_and_reads_nothing(monkeypatch, env_value):
    gate = _reload(monkeypatch, env_value)
    t = _Table(rows=[{"learning_loop_beta": True}])
    monkeypatch.setattr("db.connection.table", lambda name: t)
    before = db_client_calls()
    assert gate.learning_loop_active("user_andres") is False
    assert t.calls == []
    assert db_client_calls()[len(before) :] == [], "flag off, yet the DB client was called"


@pytest.mark.parametrize(
    "rows,raises",
    [
        ([{"learning_loop_beta": True}], None),
        ([{"learning_loop_beta": False}], None),
        ([], None),
        ([{"user_id": "user_andres"}], None),
        (None, RuntimeError("pg down")),
    ],
)
def test_env_on_is_true_for_any_row_state_and_reads_nothing(monkeypatch, rows, raises):
    gate = _reload(monkeypatch, None)
    t = _Table(rows=rows, raises=raises)
    monkeypatch.setattr("db.connection.table", lambda name: t)
    before = db_client_calls()
    assert not hasattr(gate, "table")
    assert gate.learning_loop_active("user_andres") is True
    assert t.calls == []
    assert db_client_calls()[len(before) :] == []
