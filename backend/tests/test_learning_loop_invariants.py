"""Learning-loop series invariants (spec §8). Source-scan and import-time
assertions only — no DB, no LLM. Every package's Task 1 replaces one or more
`pytest.skip` placeholders below with a real assertion. Never delete a test
here; never mark one xfail."""

from __future__ import annotations

import pathlib
import re
import subprocess

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
LEARNING = BACKEND / "learning"
MIGRATIONS = BACKEND / "db" / "migrations"

PURE_MODULES = ("bkt.py", "fsrs.py", "policy.py", "gates.py", "ladder.py", "leak.py")
FORBIDDEN_IMPORT_ROOTS = ("agents", "pydantic_ai", "google", "db")


def _imports_of(path: pathlib.Path) -> list[str]:
    roots = []
    for line in path.read_text().splitlines():
        m = re.match(r"\s*(?:from|import)\s+([A-Za-z_][\w.]*)", line)
        if m:
            roots.append(m.group(1).split(".")[0])
    return roots


def test_inv_01_single_graph_writer():
    pytest.skip("asserted by PKG-03")


def test_inv_02_pure_modules_import_nothing_impure():
    for name in PURE_MODULES:
        path = LEARNING / name
        assert path.exists(), f"{name} missing — PKG-00 stubs it"
        bad = [r for r in _imports_of(path) if r in FORBIDDEN_IMPORT_ROOTS]
        assert not bad, f"{name} imports {bad}"


def test_inv_03_channel_guess_slip_bounds():
    pytest.skip("asserted by PKG-01")


def test_inv_04_policy_takes_no_message_text():
    pytest.skip("asserted by PKG-06")


def test_inv_05_series_event_names_in_taxonomy():
    pytest.skip("asserted by PKG-06")


def test_inv_06_series_agent_tasks_have_function_handlers():
    pytest.skip("asserted by PKG-04")


def test_inv_07_learning_tables_only_via_connection():
    for path in LEARNING.glob("*.py"):
        text = path.read_text()
        if "table(" in text or "rpc(" in text:
            assert "from db.connection import" in text, (
                f"{path.name} calls table()/rpc() without db.connection"
            )


def test_inv_08_series_migrations_named_and_never_modified():
    names = sorted(p.name for p in MIGRATIONS.glob("*_learning_*.sql"))
    for n in names:
        assert re.fullmatch(r"\d{14}_learning_[a-z_]+\.sql", n), n
    out = subprocess.run(
        [
            "git",
            "log",
            "--diff-filter=M",
            "--format=%h",
            "--",
            "backend/db/migrations/*_learning_*.sql",
        ],
        cwd=BACKEND.parent,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    assert out == "", f"series migrations were modified after creation: {out}"


def test_inv_09_no_unique_or_eq_on_encrypted_learning_columns():
    pytest.skip("asserted by PKG-04")


def test_inv_10_lru_cache_has_clear_hook():
    pytest.skip("asserted by the first package that adds an lru_cache under backend/learning/")


def test_inv_11_gate_false_when_env_unset(monkeypatch):
    monkeypatch.delenv("LEARNING_LOOP_ENABLED", raising=False)
    import importlib

    import config

    importlib.reload(config)
    from learning import gate

    importlib.reload(gate)
    calls = []
    monkeypatch.setattr(gate, "table", lambda name: calls.append(name) or _Boom())
    for uid in ("user_andres", "e2e-student", "nobody"):
        assert gate.learning_loop_active(uid) is False
    assert calls == [], "gate touched the database with the env var unset"


class _Boom:
    def select(self, *a, **k):
        raise AssertionError("must not be called")


def test_inv_12_one_prompt_stack_per_series_agent():
    pytest.skip("asserted by PKG-04")
