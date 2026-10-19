# PKG-00 foundation — Learning Loop series (1 of 15)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> You are a fresh session. Nothing outside this file, `docs/superpowers/plans/learning-loop/LEDGER.md`, and the files this prompt lists is known to you. Do not infer intent from chat history you do not have. Do not read the whole research corpus; read the sections named below.

## Package id + goal

**PKG-00 `foundation`.** After this package: the flag + per-user gate exist and are provably inert when the env var is unset; `SaplingDeps` can carry loop state; the invariants test module exists and runs first in every later package; every module the series will fill exists as an inert stub; the ledger has this package's `done` row. `tests/test_learning_gate.py` and `tests/test_learning_loop_invariants.py` prove it.

Branch: `feat/learning-loop-00-foundation`. PR title: `feat(learning): PKG-00 foundation`.

## Read before you start (in this order)

0. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` **§13 Amendments log** — in force; where this file and §13 disagree, §13 wins. Re-read it before Task 1.
1. `docs/superpowers/plans/learning-loop/LEDGER.md` — refuse to start if any row is `blocked` or `in-progress`. All rows should be `planned`.
2. `CLAUDE.md` §Conventions and §Gotchas — the standing rules the "Do not" list below repeats.
3. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` §1 (goal), §2 (module map), §7 (flag and gate), §8 (invariants). Skim §3 headings only; PKG-01 owns the constants.
4. `docs/superpowers/plans/learning-loop/README.md` — series conventions.
5. `docs/superpowers/plans/learning-loop/HANDOFF-template.md` — what you write at the end.
6. Code you will modify: `backend/config.py:1–30` (env style), `backend/agents/deps.py:14–60` (`SaplingDeps` dataclass), `backend/routes/profile.py:78–96` (`_SETTINGS_COLS`, `_get_or_create_settings`) and `:425–460` (`ALLOWED` whitelist in the settings PATCH), `backend/models/__init__.py:327–340` (`UpdateSettingsBody`) and `:376–400` (`SettingsResponse`).
7. Code you will mirror: `backend/tests/test_document_index_status_migration.py` (migration-invariant test style), `backend/tests/conftest.py:63–76` (`_clear_lru_caches`) and `:254–312` (`_hermetic_supabase_client`), `backend/db/migrations/20260921063714_document_index_status.sql` (migration comment + `IF NOT EXISTS` style).

## State of the world

This is the first package. Verify the pre-series base is green before Task 1:

| check | command | expected |
|---|---|---|
| hermetic suite green | `cd backend && venv/bin/python -m pytest tests/ -q -x` | `… passed` (note the count N₀; it is the regression baseline for the whole series) |
| lint green | `cd backend && venv/bin/ruff check .` | `All checks passed!` |
| no series code exists | `ls backend/learning 2>/dev/null; ls docs/superpowers/plans/learning-loop/HANDOFF-0*.md 2>/dev/null` | either empty, or only the inert stubs listed in Task 6 (module docstring + `pass`) |
| latest migration prefix | `ls backend/db/migrations | tail -1` | a `2026…` timestamped file; your migration's prefix must sort after it |

Rule: any red row → STOP. Diagnose, repair on this branch as commit `fix(learning-loop): repair pre-series base — <what>`, record the deviation in `LEDGER.md`, re-run all rows. Never build on a broken base.

## Spec

### Behaviour

1. `config.LEARNING_LOOP_ENABLED` is a module-level bool read from the env var `LEARNING_LOOP_ENABLED`; any value other than case-insensitive `"true"` (including unset) is `False`.
2. `learning.gate.learning_loop_active(user_id: str) -> bool` returns `False` immediately when `config.LEARNING_LOOP_ENABLED` is `False`, without touching the database. When `True`, it reads `user_settings.learning_loop_beta` for that user through `db.connection.table("user_settings").select("learning_loop_beta", filters={"user_id": f"eq.{user_id}"})` and returns `bool(rows[0]["learning_loop_beta"])`; a missing row or a missing key is `False`. It never raises: any exception from the read is logged at WARNING and returns `False` (fail closed).
3. The gate is not yet called from any route in this package. Routes wire it in PKG-07 (learn), PKG-11 (quiz, flashcards). This package only makes it exist and prove its truth table.
4. `SaplingDeps` gains `learning_loop: bool = False`, `loop_state: Any = None`, `pending_evidence: list = field(default_factory=list)`. No existing field changes. No consumer changes.
5. `user_settings.learning_loop_beta` is readable and patchable through the existing settings endpoints (`GET/PATCH /api/profile/{user_id}/settings` or wherever `_SETTINGS_COLS`/`ALLOWED` are used — follow the code, not this sentence). Default `false`.
6. `backend/tests/test_learning_loop_invariants.py` exists with the invariants numbered in the spec §8 that can be asserted now: 2, 7, 8, 11, and a placeholder test per remaining invariant that is `pytest.skip`ped with reason `"asserted by PKG-NN"` so the module already lists all twelve.
7. Every module in spec §2 exists as an inert stub: a module docstring naming the package that fills it, nothing else. Nothing imports them. `ruff check` passes on them.

### Schema (exact)

```sql
-- <ts>_learning_loop_beta.sql
-- Learning loop series PKG-00: per-user opt-in for the new tutor loop.
-- Paired with the LEARNING_LOOP_ENABLED env var (config.py); both must be
-- true for learning.gate.learning_loop_active() to return True.
ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS learning_loop_beta boolean NOT NULL DEFAULT false;
```

### Named constants

None introduced here. `LEARNING_LOOP_ENABLED` is a config flag, not a learning constant. PKG-01 creates `backend/learning/params.py`.

### Invariants asserted by this package (spec §8 numbering)

- (2) `backend/learning/{bkt,fsrs,policy,gates,ladder,leak}.py` import nothing from `agents`, `pydantic_ai`, `google`, `db` — asserted by source scan of `import`/`from` lines (stubs trivially pass).
- (7) every `table("` / `rpc("` call under `backend/learning/` resolves to `db.connection` — asserted by grepping that each file that mentions `table(` has `from db.connection import` (stubs trivially pass).
- (8) every file matching `backend/db/migrations/*_learning_*.sql` matches `^\d{14}_learning_[a-z_]+\.sql$` and `git log --diff-filter=M --format=%h -- backend/db/migrations/*_learning_*.sql` prints nothing.
- (11) with `LEARNING_LOOP_ENABLED` unset, `learning_loop_active(uid)` is `False` for `uid in ("user_andres", "e2e-student", "nobody")` and performs no `table()` call (spy on `learning.gate.table`).

### Error semantics

The gate fails closed and never raises. No agent runs in this package, so no ADR 0024 degrade path is touched.

### Events added

None. The taxonomy is untouched in this package (PKG-06 adds `zpd.*`).

## Non-goals

- No BKT maths (PKG-01), no FSRS (PKG-02), no `apply_graph_update` change (PKG-03), no agent, tool, route, or frontend change (PKG-04+).
- No feature-flag *system* (#620). This is one env var and one column.
- No taxonomy change, no `chat_stream.py` change, no migration other than the one above.

## Tasks

### Task 1: Invariants module skeleton

**Files:**
- Create: `backend/tests/test_learning_loop_invariants.py`

**Interfaces:**
- Consumes: filesystem under `backend/`, `git`.
- Produces: the module every later package's Task 1 extends. Test names are `test_inv_NN_<slug>` so grep finds them.

- [ ] **Step 1: Write the module (these tests are the deliverable; some pass on the stubs, the rest are skipped placeholders)**

```python
"""Learning-loop series invariants (spec §8). Source-scan and import-time
assertions only — no DB, no LLM. Every package's Task 1 replaces one or more
`pytest.skip` placeholders below with a real assertion. Never delete a test
here; never mark one xfail."""
from __future__ import annotations

import os
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
            assert "from db.connection import" in text, f"{path.name} calls table()/rpc() without db.connection"


def test_inv_08_series_migrations_named_and_never_modified():
    names = sorted(p.name for p in MIGRATIONS.glob("*_learning_*.sql"))
    for n in names:
        assert re.fullmatch(r"\d{14}_learning_[a-z_]+\.sql", n), n
    out = subprocess.run(
        ["git", "log", "--diff-filter=M", "--format=%h", "--", "backend/db/migrations/*_learning_*.sql"],
        cwd=BACKEND.parent, capture_output=True, text=True, check=False,
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
```

- [ ] **Step 2: Run to see the current state**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -v`
Expected: `test_inv_02` and `test_inv_07` FAIL (`learning/` does not exist yet); `test_inv_08` PASS (no series migrations yet); `test_inv_11` ERROR (`ModuleNotFoundError: learning`); the rest SKIPPED.

- [ ] **Step 3: Commit the module as-is** (red is expected; later tasks turn it green)

```
git add backend/tests/test_learning_loop_invariants.py
git commit -m "test(learning-loop): PKG-00 — invariants module skeleton

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 2: Migration `learning_loop_beta`

**Files:**
- Create: `backend/db/migrations/<UTC>_learning_loop_beta.sql`
- Test: `backend/tests/test_learning_loop_beta_migration.py`

**Interfaces:**
- Consumes: nothing.
- Produces: column `user_settings.learning_loop_beta boolean NOT NULL DEFAULT false`.

- [ ] **Step 1: Write the failing test**

```python
"""PKG-00 migration invariants. Live schema is proven by migration replay in
the E2E lane; this guards the properties later packages depend on."""
import pathlib
import re

MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"


def _migration() -> str:
    hits = sorted(MIG_DIR.glob("*_learning_loop_beta.sql"))
    assert len(hits) == 1, f"expected exactly one learning_loop_beta migration, got {hits}"
    return hits[0].read_text()


def test_column_defaults_to_opted_out():
    sql = _migration()
    assert re.search(
        r"learning_loop_beta\s+boolean\s+NOT NULL\s+DEFAULT\s+false", sql
    ), "learning_loop_beta must be boolean NOT NULL DEFAULT false"


def test_migration_is_idempotent():
    assert "ADD COLUMN IF NOT EXISTS" in _migration()


def test_migration_prefix_is_a_utc_timestamp():
    name = sorted(MIG_DIR.glob("*_learning_loop_beta.sql"))[0].name
    assert re.fullmatch(r"\d{14}_learning_loop_beta\.sql", name), name
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_loop_beta_migration.py -v`
Expected: FAIL — `expected exactly one learning_loop_beta migration, got []`

- [ ] **Step 3: Write the migration**

Generate the prefix with `date -u +%Y%m%d%H%M%S`. File content is the SQL in §Spec/Schema, verbatim, including the comment.

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_loop_beta_migration.py tests/test_learning_loop_invariants.py::test_inv_08_series_migrations_named_and_never_modified -v && venv/bin/ruff check .`
Expected: 4 passed; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/db/migrations/*_learning_loop_beta.sql backend/tests/test_learning_loop_beta_migration.py
git commit -m "feat(learning-loop): PKG-00 — user_settings.learning_loop_beta migration

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 3: Env flag + gate

**Files:**
- Modify: `backend/config.py` (add one line next to the other `os.getenv` reads)
- Create: `backend/learning/__init__.py`, `backend/learning/gate.py`
- Test: `backend/tests/test_learning_gate.py`

**Interfaces:**
- Consumes: `config.LEARNING_LOOP_ENABLED`, `db.connection.table`.
- Produces: `learning.gate.learning_loop_active(user_id: str) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
"""learning.gate truth table (spec §7). Fail closed on every error."""
from __future__ import annotations

import importlib

import pytest


def _reload(monkeypatch, env_value: str | None):
    if env_value is None:
        monkeypatch.delenv("LEARNING_LOOP_ENABLED", raising=False)
    else:
        monkeypatch.setenv("LEARNING_LOOP_ENABLED", env_value)
    import config
    importlib.reload(config)
    from learning import gate
    importlib.reload(gate)
    return gate


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
    assert gate.learning_loop_active("user_andres") is False
    assert t.calls == []


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_gate.py -v`
Expected: ERROR at collection/first test — `ModuleNotFoundError: No module named 'learning'`

- [ ] **Step 3: Implement**

`backend/config.py`, next to the other env reads:
```python
# Learning loop series (docs/superpowers/specs/2026-09-26-learning-loop-design.md §7).
# Only "true" (any case) enables; everything else, including unset, is off.
LEARNING_LOOP_ENABLED = os.getenv("LEARNING_LOOP_ENABLED", "false").strip().lower() == "true"
```

`backend/learning/__init__.py`:
```python
"""Learning loop: learner model, scheduler, and tutoring policy.

Pure modules (bkt, fsrs, policy, gates, ladder, leak) import nothing from
agents/, pydantic_ai, google, or db/ — enforced by
tests/test_learning_loop_invariants.py. Spec: docs/superpowers/specs/
2026-09-26-learning-loop-design.md
"""
```

`backend/learning/gate.py`:
```python
"""Flag + per-user opt-in for the learning loop (spec §7). Fails closed."""
from __future__ import annotations

import logging

import config
from db.connection import table

logger = logging.getLogger("sapling.learning.gate")


def learning_loop_active(user_id: str) -> bool:
    """True only when LEARNING_LOOP_ENABLED is set AND the user opted in.

    Never raises. With the env var off it performs no database read, so the
    flag-off path is byte-identical to the pre-series product.
    """
    if not config.LEARNING_LOOP_ENABLED:
        return False
    try:
        rows = table("user_settings").select(
            "learning_loop_beta", filters={"user_id": f"eq.{user_id}"}
        )
    except Exception as exc:  # fail closed
        logger.warning("learning_loop_active: read failed for %s: %s", user_id, exc)
        return False
    if not rows:
        return False
    return bool(rows[0].get("learning_loop_beta", False))
```

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_gate.py tests/test_learning_loop_invariants.py -v && venv/bin/ruff check .`
Expected: gate tests all pass; `test_inv_11` passes; `test_inv_02`/`test_inv_07` still FAIL until Task 6 creates the pure-module stubs; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/config.py backend/learning/__init__.py backend/learning/gate.py backend/tests/test_learning_gate.py
git commit -m "feat(learning-loop): PKG-00 — LEARNING_LOOP_ENABLED flag and fail-closed gate

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 4: `SaplingDeps` fields

**Files:**
- Modify: `backend/agents/deps.py`
- Test: `backend/tests/test_learning_deps.py`

**Interfaces:**
- Produces: `SaplingDeps.learning_loop: bool = False`, `SaplingDeps.loop_state: Any = None`, `SaplingDeps.pending_evidence: list = field(default_factory=list)`.

- [ ] **Step 1: Write the failing test**

```python
"""SaplingDeps carries loop state without changing any existing default."""
from agents.deps import SaplingDeps


def test_defaults_are_inert():
    d = SaplingDeps(user_id="u", course_id=None, supabase=None, request_id="r")
    assert d.learning_loop is False
    assert d.loop_state is None
    assert d.pending_evidence == []


def test_pending_evidence_is_per_instance():
    a = SaplingDeps(user_id="u", course_id=None, supabase=None, request_id="r")
    b = SaplingDeps(user_id="v", course_id=None, supabase=None, request_id="s")
    a.pending_evidence.append({"node_id": "n"})
    assert b.pending_evidence == []


def test_existing_defaults_unchanged():
    d = SaplingDeps(user_id="u", course_id=None, supabase=None, request_id="r")
    assert d.session_id is None
    assert d.feature == "unknown"
    assert d.share_class_context is True
    assert d.graph_updates == [] and d.mastery_changes == [] and d.retrieval is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_deps.py -v`
Expected: FAIL — `AttributeError: 'SaplingDeps' object has no attribute 'learning_loop'`

- [ ] **Step 3: Implement** — append three fields at the end of the dataclass, and three docstring entries in the same style as the existing ones:
```python
    learning_loop: bool = False
    loop_state: Any = None
    pending_evidence: list = field(default_factory=list)
```
Docstring text: `learning_loop`: result of `learning.gate.learning_loop_active` for this request; selects the loop tool set and routes. `loop_state`: the session's typed loop state (PKG-06); None on the legacy path. `pending_evidence`: `learning.evidence.Evidence` dicts accumulated by `graded_check_tool` (PKG-05) for the ROUTE to persist through `apply_graph_update` — tools never write graph tables.

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_deps.py tests/test_model_mode_seam.py -q && venv/bin/ruff check .`
Expected: all passed; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/agents/deps.py backend/tests/test_learning_deps.py
git commit -m "feat(learning-loop): PKG-00 — SaplingDeps loop fields

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 5: Settings read/patch for `learning_loop_beta`

**Files:**
- Modify: `backend/routes/profile.py` (`_SETTINGS_COLS`, `ALLOWED`), `backend/models/__init__.py` (`UpdateSettingsBody`, `SettingsResponse`)
- Test: `backend/tests/test_learning_settings_flag.py`

**Interfaces:**
- Produces: `learning_loop_beta` in the settings GET payload; PATCH accepts `{"learning_loop_beta": true|false}`.

- [ ] **Step 1: Write the failing test** — mirror the closest existing settings test (grep `share_class_context` in `backend/tests/` and copy its request/fixture shape; `share_class_context` was added the same way in #72). Assert: (a) `"learning_loop_beta"` appears in `_SETTINGS_COLS`; (b) PATCH with `{"learning_loop_beta": true}` reaches `table("user_settings").update` with that key; (c) PATCH with an unknown key does not.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_settings_flag.py -v`
Expected: FAIL on (a) — `'learning_loop_beta' not in _SETTINGS_COLS`

- [ ] **Step 3: Implement** — add `learning_loop_beta,` to `_SETTINGS_COLS` (after `share_class_context,`), add `"learning_loop_beta"` to `ALLOWED` with a one-line comment citing PKG-00, add `learning_loop_beta: Optional[bool] = None` to `UpdateSettingsBody` and `learning_loop_beta: bool = False` to `SettingsResponse`.

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_settings_flag.py tests/ -q -k "settings or profile" && venv/bin/ruff check .`
Expected: all passed; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/routes/profile.py backend/models/__init__.py backend/tests/test_learning_settings_flag.py
git commit -m "feat(learning-loop): PKG-00 — learning_loop_beta in settings read/patch

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 6: Inert stubs for the whole series

**Files:**
- Create (module docstring only, one line naming the owning package; no code): `backend/learning/params.py` (PKG-01), `bkt.py` (PKG-01), `fsrs.py` (PKG-02), `evidence.py` (PKG-03), `learner_state.py` (PKG-03), `checks.py` (PKG-04), `ladder.py` (PKG-06), `policy.py` (PKG-06), `gates.py` (PKG-06), `leak.py` (PKG-06), `probe.py` (PKG-08), `planner.py` (PKG-08), `session_close.py` (PKG-09), `learner_brief.py` (PKG-09), `misconceptions.py` (PKG-10), `review.py` (PKG-12); `backend/agents/check_items.py` (PKG-04), `backend/agents/grader.py` (PKG-05), `backend/agents/tools/check.py` (PKG-05), `backend/agents/loop_tutor.py` (PKG-07), `backend/routes/learn_loop.py` (PKG-07; NOT mounted), `backend/services/check_item_service.py` (PKG-04); `frontend/src/components/learn/LoopLearn.tsx` (PKG-13; `export {};` plus a comment), `frontend/e2e/learn-loop.spec.ts` (PKG-13; comment only).

These may already exist from the planning step. If so, verify each is docstring-only and skip creation.

- [ ] **Step 1: Create or verify**

Run: `for f in backend/learning/{params,bkt,fsrs,evidence,learner_state,checks,ladder,policy,gates,leak,probe,planner,session_close,learner_brief,misconceptions,review}.py backend/agents/{check_items,grader,loop_tutor}.py backend/agents/tools/check.py backend/routes/learn_loop.py backend/services/check_item_service.py; do test -s "$f" && echo "ok $f" || echo "MISSING $f"; done`
Expected: every line `ok`.

- [ ] **Step 2: Run the invariants and the full suite**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -v && venv/bin/python -m pytest tests/ -q && venv/bin/ruff check .`
Expected: inv 02, 07, 08, 11 PASS, the rest SKIPPED; full suite `N₀ + (new tests) passed`, zero failures; `All checks passed!`

- [ ] **Step 3: Commit** (only if you created or changed a stub)

```
git add backend/learning backend/agents/check_items.py backend/agents/grader.py backend/agents/loop_tutor.py backend/agents/tools/check.py backend/routes/learn_loop.py backend/services/check_item_service.py frontend/src/components/learn/LoopLearn.tsx frontend/e2e/learn-loop.spec.ts
git commit -m "chore(learning-loop): PKG-00 — inert stubs for the series

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 7: Hand-off + ledger

- [ ] **Step 1:** Write `docs/superpowers/plans/learning-loop/HANDOFF-00.md` from `HANDOFF-template.md`. "Verify commands" must be exactly these five lines (they become PKG-01/02/04's State-of-the-world rows):

```
cd backend && venv/bin/python -m pytest tests/test_learning_gate.py -q                          → 11 passed
cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q               → 4 passed, 8 skipped
cd backend && venv/bin/python -m pytest tests/test_learning_deps.py tests/test_learning_settings_flag.py tests/test_learning_loop_beta_migration.py -q → all passed
grep -n "^LEARNING_LOOP_ENABLED" backend/config.py                                               → 1 hit
ls backend/db/migrations/*_learning_loop_beta.sql                                                → 1 file
```

- [ ] **Step 2:** Append the ledger row: `| 00 | foundation | done | feat/learning-loop-00-foundation | <sha> | 5 modules | — | HANDOFF-00.md |`. Add nothing to Deviations unless something differed from this prompt.

- [ ] **Step 3: Commit + PR**

```
git add docs/superpowers/plans/learning-loop/HANDOFF-00.md docs/superpowers/plans/learning-loop/LEDGER.md
git commit -m "docs(learning-loop): PKG-00 — hand-off and ledger

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
gh pr create --title "feat(learning): PKG-00 foundation" --body-file - <<'EOF'
Learning loop series, package 0 of 15. Spec: docs/superpowers/specs/2026-09-26-learning-loop-design.md.

- LEARNING_LOOP_ENABLED env flag + user_settings.learning_loop_beta column + fail-closed learning.gate
- SaplingDeps loop fields (inert defaults)
- learning_loop_beta in settings GET/PATCH
- tests/test_learning_loop_invariants.py skeleton (4 asserted, 8 placeholders)
- inert stubs for every series module

Flag-off behaviour is byte-identical: no route calls the gate yet.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

## Self-check loop (run after every task, and once more before the PR)

1. `cd backend && venv/bin/ruff check . && venv/bin/ruff format --check learning tests/test_learning_*.py`
2. `venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q`
3. `venv/bin/python -m pytest tests/ -q` (no `SAPLING_MODEL_MODE` exported)
4. Prompts/tool descriptions touched? **No** in this package → skip evals. (If you find yourself editing anything under `backend/agents/` other than `deps.py`, stop: scope creep.)
5. Request-path agent or route touched? **No** → skip the E2E cycle.
6. Scope check: `git diff --stat main...HEAD` — every path must be in this prompt's Files lists. Anything else: `git checkout main -- <path>` or record a Deviation.
7. Sync check: `grep -o "E2E_[A-Z_]*" backend/agents/function_handlers_e2e.py | sort -u` unchanged from `main`.

Green = all seven clean. Max 5 iterations per loop; then write a `BLOCKED` row in `LEDGER.md` with hypothesis, commands, outputs, and stop.

## Regression guard

- Pre-series suite count N₀ (from State of the world) must be unchanged except for the tests this package adds. Zero failures, zero new skips outside `test_learning_loop_invariants.py`.
- `tests/test_model_mode_seam.py`, `tests/test_event_capture_seams.py`, `tests/test_graph_service.py` unchanged and green.
- With `LEARNING_LOOP_ENABLED` unset: no route behaviour changes (none call the gate). With it set to `true`: still no route behaviour changes in this package.

## Acceptance criteria (the next session pastes these)

1. `cd backend && venv/bin/python -m pytest tests/test_learning_gate.py -q` → `11 passed`
2. `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q` → `4 passed, 8 skipped`
3. `cd backend && venv/bin/python -m pytest tests/ -q` → zero failures
4. `cd backend && venv/bin/ruff check .` → `All checks passed!`
5. `grep -c "learning_loop_beta" backend/routes/profile.py backend/models/__init__.py` → ≥ 2 and ≥ 2
6. `git diff --stat main...HEAD` lists only: `backend/config.py`, `backend/agents/deps.py`, `backend/routes/profile.py`, `backend/models/__init__.py`, `backend/learning/*`, `backend/db/migrations/*_learning_loop_beta.sql`, `backend/tests/test_learning_*.py`, the stub files, `docs/superpowers/plans/learning-loop/{HANDOFF-00.md,LEDGER.md}`.
7. `LEDGER.md` has row `00 | foundation | done | …`.

## Hand-off

`docs/superpowers/plans/learning-loop/HANDOFF-00.md` per the template; the Verify commands block is fixed above (Task 7). Open questions to record: whether `services/request_context` offers a per-request cache the gate should use (PKG-07 decides; the gate does one read per call until then).

## Do not

- Do not call the gate from any route. Do not mount `routes/learn_loop.py`. Do not touch `services/chat_stream.py`, `services/events_service.py`, `agents/chat_tutor.py`, `services/graph_service.py`.
- Do not add a feature-flag table or a generic flags mechanism.
- All Supabase access through `db/connection.py::table()`; no `httpx`, no `supabase` import.
- Migrations: UTC-timestamp prefix, `_learning_` infix, append-only, never edited after creation.
- No `lru_cache` in this package.
- No numeric literals that belong in `learning/params.py` (there are none here).
- Do not skip, xfail, or delete any pre-existing test. Do not hand-edit eval cassettes or baselines.
- Do not change `SaplingDeps` existing fields or their defaults.
- Logscan `ALLOWLIST` in `backend/e2e_oracles/logscan.py` stays `()`.
- End every commit with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; end the PR body with the Claude Code attribution line.

## If you get stuck

1. Re-read §Spec and the spec file's §7/§8 before guessing.
2. Three failed iterations on one task → append a `BLOCKED` row to `LEDGER.md` (hypothesis, commands run, outputs), commit what is green, open the PR as draft, stop.
3. Never widen scope to unblock. Never disable a test to unblock.
4. Ambiguity → choose the option closest to the spec, mark it `†` in the hand-off, continue.
