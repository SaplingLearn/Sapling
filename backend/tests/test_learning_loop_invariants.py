"""Learning-loop series invariants (spec §8). Source-scan and import-time
assertions only — no DB, no LLM. Every package's Task 1 replaces one or more
`pytest.skip` placeholders below with a real assertion. Never delete a test
here; never mark one xfail."""

from __future__ import annotations

import ast
import importlib
import os
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
# PKG-11: the two routes on the loop path, named explicitly in inv_01.
ROUTE_GRAPH_CALLERS = ("routes/quiz.py", "routes/flashcards.py")
_GRAPH_WRITE = re.compile(
    r'table\(\s*"(graph_nodes|graph_edges|node_mastery_events|learner_state)"\s*\)'
    r"\s*\.\s*(insert|update|upsert|delete)\s*\(",
    re.S,
)


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


GRAPH_TABLES = ("graph_nodes", "graph_edges", "node_mastery_events", "learner_state")
GRAPH_WRITER = "services/graph_service.py"
GRAPH_WRITER_FUNCS = ("apply_graph_update", "_apply_evidence")
GRAPH_ENTRY = GRAPH_WRITER_FUNCS[0]
# Writers that name neither table() nor write_state at a call site, so the
# halves below cannot see a second caller: reachable only via GRAPH_ENTRY.
GRAPH_PRIVATE_WRITERS = GRAPH_WRITER_FUNCS[1:]
# learning/learner_state.py is the learner_state table-access module (spec §2).
# Its one write, table("learner_state").upsert inside write_state, runs only
# through write_state, and the second half of inv_01 pins every write_state
# call to GRAPH_WRITER_FUNCS. Nothing else in that module may write.
LEARNER_STATE_MODULE = "learning/learner_state.py"
LEARNER_STATE_WRITE = ("learner_state", "upsert", "write_state")  # table, method, enclosing def
GRAPH_TABLE_READ_METHODS = ("select", "select_with_count")
INV01_EXEMPT_PREFIXES = ("tests/", "venv/", "db/archive/", "db/e2e_checks/")
_WRITE_CHAIN = re.compile(
    r'table\(\s*"(' + "|".join(GRAPH_TABLES) + r')"\s*\)\s*\.\s*(insert|update|upsert)\s*\('
)


def _application_py_files():
    for path in sorted(BACKEND.rglob("*.py")):
        rel = path.relative_to(BACKEND).as_posix()
        if rel.startswith(INV01_EXEMPT_PREFIXES) or path.name.startswith("seed_"):
            continue
        yield rel, path


def _write_state_call_lines(path: pathlib.Path) -> list[int]:
    tree = ast.parse(path.read_text())
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Attribute) and node.func.attr == "write_state")
            or (isinstance(node.func, ast.Name) and node.func.id == "write_state")
        )
    ]


def _graph_table_uses(source: str) -> list[tuple[int, str, str | None, str | None]]:
    """(line, table, method, enclosing def) for every `table("<graph table>")`
    call in `source`, bare or as `<module>.table(...)`, any quote style.
    `method` is the attribute called on the result (`select`, `upsert`, …),
    or None when the result is bound to a name, passed on, or returned:
    anything that is not a direct read counts. The regex half of inv_01 sees
    only a direct `.insert(`/`.update(`/`.upsert(` chain in double quotes, so
    `t = table("graph_nodes"); t.insert(...)` and `.delete(` passed it."""
    tree = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    uses = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        arg = node.args[0]
        if name != "table" or not isinstance(arg, ast.Constant) or arg.value not in GRAPH_TABLES:
            continue
        method = None
        parent = parents.get(node)
        if (
            isinstance(parent, ast.Attribute)
            and isinstance(parents.get(parent), ast.Call)
            and parents[parent].func is parent
        ):
            method = parent.attr
        enclosing = None
        up = parents.get(node)
        while up is not None:
            if isinstance(up, (ast.FunctionDef, ast.AsyncFunctionDef)):
                enclosing = up.name
                break
            up = parents.get(up)
        uses.append((node.lineno, arg.value, method, enclosing))
    return uses


def _graph_table_offenders(rel: str, source: str) -> list[str]:
    """inv_01's ast half for one non-writer file: every graph-table handle
    must be a direct read, except learner_state.py's write_state upsert."""
    offenders = []
    for line, tbl, method, enclosing in _graph_table_uses(source):
        if method in GRAPH_TABLE_READ_METHODS:
            continue
        if rel == LEARNER_STATE_MODULE and (tbl, method, enclosing) == LEARNER_STATE_WRITE:
            continue
        use = f".{method}(" if method else "a handle that is not a direct read"
        offenders.append(f"{rel}:{line} uses table({tbl!r}) for {use}; only reads allowed")
    return offenders


def _private_writer_offenders(rel: str, source: str) -> list[str]:
    """inv_01: every reference to a GRAPH_PRIVATE_WRITERS function — a call,
    an import, an attribute, a getattr string — must sit inside
    GRAPH_ENTRY's body in the writer file. `_apply_evidence` writes
    learner_state, graph_nodes and node_mastery_events, so a second caller
    would be a second entry point the table/write_state halves cannot see."""
    tree = ast.parse(source)
    entry = [
        (fn.lineno, fn.end_lineno)
        for fn in tree.body
        if rel == GRAPH_WRITER and isinstance(fn, ast.FunctionDef) and fn.name == GRAPH_ENTRY
    ]
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            name = node.id
        elif isinstance(node, ast.Attribute):
            name = node.attr
        elif isinstance(node, ast.alias):
            name = node.name.rsplit(".", 1)[-1]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            name = node.value
        else:
            continue
        if name not in GRAPH_PRIVATE_WRITERS:
            continue
        if any(lo <= node.lineno <= hi for lo, hi in entry):
            continue
        offenders.append(
            f"{rel}:{node.lineno} references {name} outside {GRAPH_WRITER}::{GRAPH_ENTRY}"
        )
    return offenders


def test_inv_01_single_graph_writer():
    offenders: list[str] = []
    for rel, path in _application_py_files():
        text = path.read_text()
        if any(name in text for name in GRAPH_PRIVATE_WRITERS):
            offenders += _private_writer_offenders(rel, text)
        if rel != GRAPH_WRITER:
            for m in _WRITE_CHAIN.finditer(text):
                if (
                    rel == LEARNER_STATE_MODULE
                    and (m.group(1), m.group(2)) == LEARNER_STATE_WRITE[:2]
                ):
                    continue  # write_state's own upsert; the ast half pins it to write_state
                line = text.count("\n", 0, m.start()) + 1
                offenders.append(f"{rel}:{line} writes {m.group(1)} via .{m.group(2)}(")
            offenders += _graph_table_offenders(rel, text)
        if rel not in (GRAPH_WRITER, LEARNER_STATE_MODULE) and "write_state" in text:
            offenders.append(f"{rel} references learner_state.write_state")
    assert offenders == [], "\n".join(offenders)

    # Inside the writer file, write_state may only be called from the two
    # named functions — the evidence path is a branch of apply_graph_update,
    # not a second entry point.
    writer = BACKEND / GRAPH_WRITER
    tree = ast.parse(writer.read_text())
    allowed = [
        (fn.lineno, fn.end_lineno)
        for fn in tree.body
        if isinstance(fn, ast.FunctionDef) and fn.name in GRAPH_WRITER_FUNCS
    ]
    calls = _write_state_call_lines(writer)
    assert calls, "graph_service never calls write_state — PKG-03 not wired"
    for line in calls:
        assert any(lo <= line <= hi for lo, hi in allowed), (
            f"{GRAPH_WRITER}:{line} calls write_state outside {GRAPH_WRITER_FUNCS}"
        )
    # learner_state.py defines write_state and must not call it itself.
    assert _write_state_call_lines(BACKEND / LEARNER_STATE_MODULE) == [], (
        f"{LEARNER_STATE_MODULE} calls write_state; only {GRAPH_WRITER_FUNCS} may"
    )

    # PKG-11: the two routes on the loop path never write graph tables
    # directly; the quiz route reaches the graph only through apply_graph_update.
    for rel in ROUTE_GRAPH_CALLERS:
        text = (BACKEND / rel).read_text()
        hits = [m.group(0) for m in _GRAPH_WRITE.finditer(text)]
        assert not hits, f"{rel} writes a graph table directly: {hits}"
    assert "apply_graph_update(" in (BACKEND / "routes/quiz.py").read_text(), (
        "routes/quiz.py must reach the graph through apply_graph_update"
    )


def test_inv_02_pure_modules_import_nothing_impure():
    for name in PURE_MODULES:
        path = LEARNING / name
        assert path.exists(), f"{name} missing — PKG-00 stubs it"
        bad = [r for r in _imports_of(path) if r in FORBIDDEN_IMPORT_ROOTS]
        assert not bad, f"{name} imports {bad}"


def test_inv_03_channel_guess_slip_bounds():
    """Spec §3.1 validity, asserted over the raw table so this does not depend
    on params.validate_channels being correct."""
    from learning import params

    assert set(params.CHANNELS) == {
        "free_response",
        "mc_reasoned",
        "mc",
        "teachback_llm",
        "chat_turn",
    }
    assert "idk" not in params.CHANNELS, "idk is a flag on update(), not a channel row"
    for name, row in params.CHANNELS.items():
        g, s = row["G"], row["S"]
        assert isinstance(row["strong"], bool), name
        assert 0.0 < g and 0.0 < s, name
        assert g + s < 1.0, f"{name}: G + S = {g + s}"
        assert g <= params.BKT_G_MAX, f"{name}: G {g} > BKT_G_MAX"
        assert s <= params.BKT_S_MAX, f"{name}: S {s} > BKT_S_MAX"
        assert 0.0 < params.BKT_T < 1.0 - s / (1.0 - g), f"{name}: BKT_T outside (0, 1 - S/(1-G))"
        assert g + params.S_IDK < 1.0, f"{name}: idk observation would invert"


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
    if _is_shallow_clone():
        # A depth-1 clone (actions/checkout's default) lists every file as
        # Added in its one grafted commit, so the check above cannot fail there.
        # CI must enforce it (ci.yml checks out with fetch-depth: 0), so there a
        # shallow clone is a failure; a shallow local clone only warns.
        vacuous = "inv_08: shallow clone, so the never-modified half is vacuous here"
        if _in_ci():
            pytest.fail(
                f"{vacuous}; CI must check out full history (actions/checkout fetch-depth: 0)"
            )
        warnings.warn(f"{vacuous}; it only bites on a full clone", stacklevel=1)


def _is_shallow_clone(cwd: pathlib.Path = BACKEND.parent) -> bool:
    out = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return out == "true"


def _in_ci() -> bool:
    """GitHub Actions (like most CI) sets CI=true; unset, empty, 0 or false is local."""
    return os.environ.get("CI", "").strip().lower() not in ("", "0", "false", "no")


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


def test_inv_13_fsrs_weights_pinned():
    """PKG-02: FSRS_W is the spec §3.2 FSRS-6 default vector, and fsrs.py reads
    it only from learning.params — a refit is a deliberate edit to params.py."""
    from learning.params import FSRS_S0_GOOD, FSRS_W

    assert len(FSRS_W) == 21
    assert tuple(FSRS_W[:3]) == (0.212, 1.2931, 2.3065)
    assert FSRS_S0_GOOD == FSRS_W[2]
    learning_imports = {
        line.split()[1]
        for line in (LEARNING / "fsrs.py").read_text().splitlines()
        if re.match(r"\s*from\s+learning", line)
    }
    assert learning_imports == {"learning.params"}, learning_imports
    # The line scan above misses `import learning.bkt`, `from . import bkt` and
    # imports inside functions; the ast walk sees them. `from learning.params
    # import X` also yields `learning.params.X`, which is not a module file.
    learning_modules = {
        module
        for module in _modules_imported_by(LEARNING / "fsrs.py", BACKEND)
        if module.split(".")[0] == "learning"
        and module != "learning"
        and (
            BACKEND.joinpath(*module.split(".")).with_suffix(".py").is_file()
            or BACKEND.joinpath(*module.split("."), "__init__.py").is_file()
        )
    }
    assert learning_modules == {"learning.params"}, learning_modules
