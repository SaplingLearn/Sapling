"""Learning-loop series invariants (spec §8). Source-scan and import-time
assertions only — no DB, no LLM. Every package's Task 1 replaces one or more
`pytest.skip` placeholders below with a real assertion. Never delete a test
here; never mark one xfail."""

from __future__ import annotations

import ast
import importlib
import pathlib
import re
import subprocess
import warnings

import dotenv
import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
LEARNING = BACKEND / "learning"
MIGRATIONS = BACKEND / "db" / "migrations"

PURE_MODULES = ("bkt.py", "fsrs.py", "policy.py", "gates.py", "ladder.py", "leak.py")
FORBIDDEN_IMPORT_ROOTS = ("agents", "pydantic_ai", "google", "db")


def reload_gate(monkeypatch, env_value: str | None):
    """Re-evaluate `config` and `learning.gate` with LEARNING_LOOP_ENABLED set
    to `env_value` (None = unset), and return the gate module. Hermetic:

    - config.py calls load_dotenv() at import time, so a bare reload re-reads
      backend/.env and would put back a variable this test just deleted.
      load_dotenv is a no-op for the reload.
    - every attribute the reload rebinds is registered with monkeypatch first,
      so undo puts the original objects back. monkeypatch alone restores the
      env var but not the flag computed from it, which would leak into every
      later test.
    """
    import config
    from learning import gate

    for module in (config, gate):
        for name, value in list(vars(module).items()):
            if not name.startswith("__"):
                monkeypatch.setattr(module, name, value)
    if env_value is None:
        monkeypatch.delenv("LEARNING_LOOP_ENABLED", raising=False)
    else:
        monkeypatch.setenv("LEARNING_LOOP_ENABLED", env_value)
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    importlib.reload(config)
    importlib.reload(gate)
    return gate


def db_client_calls() -> list:
    """Every call that has reached db.connection's HTTP client so far. The
    conftest hermetic fixture swaps that client for a MagicMock, so any read
    path (learning.gate.table, db.connection.table, rpc) shows up here, not
    only the symbol a test spies on."""
    import db.connection as dbconn

    return list(dbconn._client.mock_calls)


def _imports_of(path: pathlib.Path) -> list[str]:
    """Top-level names of every module `path` imports, plus everything the
    `learning` modules it imports pull in, transitively. It parses with ast, so
    comma lists (`import math, db.connection`), relative imports, and imports
    inside functions all count. A pure module therefore cannot reach `db`
    through `learning.gate` or `learning.learner_state`. `path` lives in the
    `learning` package, so its parent's parent is the import root."""
    root = path.parent.parent
    roots: list[str] = []
    seen: set[pathlib.Path] = set()
    todo = [path]
    while todo:
        current = todo.pop()
        if current in seen:
            continue
        seen.add(current)
        for module in _modules_imported_by(current, root):
            roots.append(module.split(".")[0])
            todo.extend(_learning_files(module, root))
    return list(dict.fromkeys(roots))


def _modules_imported_by(path: pathlib.Path, root: pathlib.Path) -> list[str]:
    """Absolute dotted names `path` imports. `from X import name` yields both
    X and X.name, because `name` may be a submodule."""
    modules: list[str] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            modules += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = path.parent
                for _ in range(node.level - 1):
                    base = base.parent
                package = ".".join(base.relative_to(root).parts)
                module = ".".join(part for part in (package, node.module) if part)
            else:
                module = node.module or ""
            modules.append(module)
            modules += [f"{module}.{alias.name}" for alias in node.names]
    return modules


def _learning_files(module: str, root: pathlib.Path) -> list[pathlib.Path]:
    """Source files importing `module` executes, if it is in the `learning`
    package: each package `__init__.py` on the way down, then the module."""
    parts = module.split(".")
    if parts[0] != "learning":
        return []
    files = [root.joinpath(*parts[:i], "__init__.py") for i in range(1, len(parts) + 1)]
    files.append(root.joinpath(*parts).with_suffix(".py"))
    return [f for f in files if f.is_file()]


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
    shallow = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=BACKEND.parent,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if shallow == "true":
        # A depth-1 clone (actions/checkout's default) lists every file as
        # Added in its one grafted commit, so the check above cannot fail there.
        warnings.warn(
            "inv_08: shallow clone, so the never-modified half is vacuous here; "
            "it only bites on a full clone (CI needs actions/checkout fetch-depth: 0)",
            stacklevel=1,
        )


def test_inv_09_no_unique_or_eq_on_encrypted_learning_columns():
    pytest.skip("asserted by PKG-04")


def test_inv_10_lru_cache_has_clear_hook():
    pytest.skip("asserted by the first package that adds an lru_cache under backend/learning/")


def test_inv_11_gate_false_when_env_unset(monkeypatch):
    gate = reload_gate(monkeypatch, None)
    calls = []
    monkeypatch.setattr(gate, "table", lambda name: calls.append(name) or _Boom(calls))
    before = db_client_calls()
    for uid in ("user_andres", "e2e-student", "nobody"):
        assert gate.learning_loop_active(uid) is False
    assert calls == [], "gate touched the database with the env var unset"
    assert db_client_calls()[len(before) :] == [], (
        "gate reached the DB client with the env var unset"
    )


class _Boom:
    """Stand-in table that records a read instead of raising: the gate
    swallows every exception, so a raise here would never reach the test."""

    def __init__(self, calls: list | None = None):
        self.calls = calls if calls is not None else []

    def select(self, *a, **k):
        self.calls.append(("select", a, k))
        return []


def test_inv_12_one_prompt_stack_per_series_agent():
    pytest.skip("asserted by PKG-04")
