"""Owner decision 00 (OWNER-DECISIONS-A38.md): the learning-loop gate is
computed ONCE at route entry and carried on `SaplingDeps.learning_loop`.

Two halves:
- `learning.gate.learning_loop_for_request` is the named route-entry helper
  (PKG-14b: the env kill switch alone — default ON, no read in either state).
- only `backend/routes/` may call the gate. Agents, tools, services and the
  rest of `learning/` read the already-computed `deps.learning_loop` instead
  of doing their own per-call `user_settings` read.

Lives in its own module so the `tests/test_learning_gate.py` count (13) and
the invariants count that later package prompts pin do not move.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from test_learning_loop_invariants import db_client_calls, reload_gate

BACKEND = pathlib.Path(__file__).resolve().parents[1]
GATE_FUNCS = frozenset({"learning_loop_active", "learning_loop_for_request"})
GATE_MODULE = "learning/gate.py"
SCANNED_DIRS = ("agents", "services", "learning")


class _RaisingTable:
    def __init__(self):
        self.calls = []

    def select(self, cols, filters=None):
        self.calls.append((cols, filters))
        raise RuntimeError("pg down")


class _Table:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def select(self, cols, filters=None):
        self.calls.append((cols, filters))
        return self.rows


# PKG-14b (spec §7 "After launch"): the gate is the env kill switch alone —
# default ON, no read in either state.


@pytest.mark.parametrize("env_value", ["false", "0", "off", "no", " False "])
def test_route_entry_env_off_is_false_without_any_read(monkeypatch, env_value):
    gate = reload_gate(monkeypatch, env_value)
    t = _Table(rows=[{"learning_loop_beta": True}])
    monkeypatch.setattr("db.connection.table", lambda name: t)
    before = db_client_calls()
    assert gate.learning_loop_for_request("user_andres") is False
    assert t.calls == []
    assert db_client_calls()[len(before) :] == [], "flag off, yet the DB client was called"


@pytest.mark.parametrize("env_value", [None, "", "true", "1"])
@pytest.mark.parametrize("table_cls", [_Table, _RaisingTable])
def test_route_entry_env_on_is_true_without_any_read(monkeypatch, env_value, table_cls):
    gate = reload_gate(monkeypatch, env_value)
    t = table_cls([{"learning_loop_beta": False}]) if table_cls is _Table else table_cls()
    monkeypatch.setattr("db.connection.table", lambda name: t)
    before = db_client_calls()
    assert not hasattr(gate, "table")
    assert gate.learning_loop_for_request("user_andres") is True
    assert t.calls == []
    assert db_client_calls()[len(before) :] == []


def _gate_references(source: str) -> list[tuple[int, str]]:
    """Every call to, attribute read of, or import of a gate function."""
    hits: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name) and node.id in GATE_FUNCS:
            hits.append((node.lineno, node.id))
        elif isinstance(node, ast.Attribute) and node.attr in GATE_FUNCS:
            hits.append((node.lineno, node.attr))
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in GATE_FUNCS:
                    hits.append((node.lineno, alias.name))
    return hits


@pytest.mark.parametrize(
    "source, expected",
    [
        ("from learning.gate import learning_loop_active\n", True),
        ("from learning import gate\ndef f(u):\n    return gate.learning_loop_active(u)", True),
        ("from learning.gate import learning_loop_for_request as g\n", True),
        ("def f(deps):\n    return deps.learning_loop\n", False),
        ("# learning_loop_active is computed by the route\nX = 1\n", False),
    ],
)
def test_gate_reference_detector(source, expected):
    assert bool(_gate_references(source)) is expected


#: #118: the loop route's handler bodies moved to services/loop/ with their
#: route-entry helper. `_gate_value` is that helper (require_self, then the ONE
#: read), called first thing in a handler body, so it is still the route entry;
#: nothing else in the package may name the gate.
#: The quiz learning flags each need the loop on (services/quiz_learning.py
#: ::quiz_flags): the quiz routes' bodies call that helper first thing, once
#: per request, so it is their route entry too.
ROUTE_ENTRY_HELPERS = {
    "services/loop/state.py": "_gate_value",
    "services/quiz_learning.py": "quiz_flags",
}


def _route_entry_lines(source: str, helper: str) -> set[int]:
    lines = set()
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name == helper:
            lines |= set(range(node.lineno, node.end_lineno + 1))
        elif isinstance(node, ast.ImportFrom) and node.module == "learning.gate" and [
            a.name for a in node.names
        ] == ["learning_loop_for_request"]:
            lines.add(node.lineno)
    return lines


def test_only_routes_call_the_gate():
    offenders = []
    for top in SCANNED_DIRS:
        for path in sorted((BACKEND / top).rglob("*.py")):
            rel = path.relative_to(BACKEND).as_posix()
            if rel == GATE_MODULE:
                continue
            source = path.read_text()
            allowed = (
                _route_entry_lines(source, ROUTE_ENTRY_HELPERS[rel])
                if rel in ROUTE_ENTRY_HELPERS else set()
            )
            for lineno, name in _gate_references(source):
                if lineno not in allowed:
                    offenders.append(f"{rel}:{lineno} {name}")
    assert offenders == [], (
        "Only backend/routes/ may evaluate the learning-loop gate; everything "
        "below the route reads SaplingDeps.learning_loop (owner decision 00): "
        + ", ".join(offenders)
    )
