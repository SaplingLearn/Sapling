# Staging → Production Promotion Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hand-run staging→prod promotion sequence with `make promote` — a single command that preflights, migrates prod, pauses once for confirmation, merges `main`→`production`, waits for the deploy to actually report the promoted commit, and smokes it.

**Architecture:** A `backend/promotion/` package of four single-responsibility units (`preflight`, `snapshot`, `smoke`, `runner`). Every unit splits pure logic from IO: the pure half takes plain data and is tested hermetically, the IO half is a thin shell. `runner` sequences the stages and owns the one confirmation prompt. A later `workflow_dispatch` wrapper can call `runner.run()` unchanged.

**Tech Stack:** Python 3.12, psycopg 3 (already the migration runner's dependency), httpx 0.28 (already a backend dependency), `gh` CLI for the PR, pytest for tests.

## Global Constraints

- Tracking issue: **#516**. Reference it in commit messages.
- New code lives under `backend/promotion/`; run everything from `backend/` with `venv/bin/python`.
- `SUPABASE_DB_URL` for prod must be the **SESSION-mode pooler** URI (port 5432, user `postgres.<ref>`). The direct `db.<ref>.supabase.co` host is IPv6-only. Build it with `scripts/pooler_url.py`; production sits on the **`aws-0-us-west-2`** cluster, staging on **`aws-1-us-west-2`**.
- **No new dependencies.** psycopg and httpx are already in `requirements.txt`.
- All new tests must be hermetic — no network, no database, no prod credentials — and must pass in the default `python -m pytest tests/ -q` lane. Achieve this by injecting the IO callable, never by monkeypatching sockets.
- Never edit an applied migration. This feature adds no migrations.
- `ruff check .` must stay clean.
- The runner must **never** auto-revert, auto-rollback, or run down migrations.

---

### Task 1: Surface the build commit on `/api/health`

Without this the runner cannot distinguish "deploy hasn't landed yet" from "deploy landed and is broken".

**Files:**
- Modify: `backend/config.py` (append a function near the other env readers)
- Modify: `backend/main.py:233-237` (the `health()` return dict)
- Test: `backend/tests/test_health_build_commit.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `config.build_commit() -> str` — 7-char lowercase SHA, or the literal `"unknown"`. `/api/health` gains a `"commit"` key with that value.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_health_build_commit.py`:

```python
"""/api/health must report the deployed commit (#516).

The promotion runner polls this to tell "not deployed yet" from "deployed and
broken". A short SHA is no more sensitive than the model_mode already exposed.
"""
import pytest
from fastapi.testclient import TestClient

from config import build_commit
import main


@pytest.fixture
def client():
    return TestClient(main.app)


def test_build_commit_reads_railway_env(monkeypatch):
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "abc1234567890def")
    assert build_commit() == "abc1234"


def test_build_commit_is_unknown_when_unset(monkeypatch):
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    monkeypatch.delenv("GIT_COMMIT_SHA", raising=False)
    assert build_commit() == "unknown"


def test_build_commit_falls_back_to_generic_env(monkeypatch):
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    monkeypatch.setenv("GIT_COMMIT_SHA", "0f1e2d3c4b5a")
    assert build_commit() == "0f1e2d3"


def test_build_commit_ignores_blank_value(monkeypatch):
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "   ")
    monkeypatch.delenv("GIT_COMMIT_SHA", raising=False)
    assert build_commit() == "unknown"


def test_health_reports_commit(client, monkeypatch):
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "deadbeefcafe")
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["commit"] == "deadbee"


def test_health_keeps_existing_keys(client):
    body = client.get("/api/health").json()
    assert body["service"] == "sapling-backend"
    assert "model_mode" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_health_build_commit.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_commit' from 'config'`

- [ ] **Step 3: Add `build_commit()` to config.py**

Append to `backend/config.py`:

```python
def build_commit() -> str:
    """Short git SHA of the running build, or "unknown".

    The promotion runner (#516) polls /api/health until this matches the commit
    it just promoted, which is what lets it distinguish "the deploy has not
    landed yet" from "the deploy landed and the app is broken". Railway injects
    RAILWAY_GIT_COMMIT_SHA; GIT_COMMIT_SHA is the generic fallback for any other
    host. Local, Docker and E2E runs set neither and report "unknown", which the
    runner degrades on rather than hanging.

    Read at call time, not import time, so a test can set the env var.
    """
    raw = os.getenv("RAILWAY_GIT_COMMIT_SHA") or os.getenv("GIT_COMMIT_SHA") or ""
    return raw.strip()[:7].lower() or "unknown"
```

- [ ] **Step 4: Add the key to the health response**

In `backend/main.py`, change the body of `health()` (currently lines 233-237) to:

```python
    from agents._providers import _model_mode
    from config import build_commit

    return {
        "status": "ok",
        "service": "sapling-backend",
        "model_mode": _model_mode(),
        # The deployed commit, so a promotion can verify the code it merged is
        # actually the code answering (#516). "unknown" off Railway.
        "commit": build_commit(),
    }
```

- [ ] **Step 5: Run the new tests and the full suite**

Run: `cd backend && venv/bin/python -m pytest tests/test_health_build_commit.py -v && venv/bin/python -m pytest tests/ -q`
Expected: new file PASSES; the full suite's pass count is unchanged apart from the additions. Read the pass/skip counts, not just the exit code.

- [ ] **Step 6: Commit**

```bash
git add backend/config.py backend/main.py backend/tests/test_health_build_commit.py
git commit -m "feat(health): report the build commit so promotions can verify the deploy (#516)"
```

---

### Task 2: `promotion/preflight.py` — the read-only guards

**Files:**
- Create: `backend/promotion/__init__.py`
- Create: `backend/promotion/preflight.py`
- Test: `backend/tests/test_promotion_preflight.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Finding(kind: str, detail: str)` — frozen dataclass
  - `project_ref(value: str) -> str`
  - `ledger_diff(files: list[str], recorded: set[str]) -> tuple[list[str], list[str]]` returning `(pending, orphans)`
  - `scan_destructive(paths: list[Path]) -> list[Finding]`
  - `staging_gap(pending: list[str], staging_recorded: set[str]) -> list[str]`
  - `evaluate(...) -> list[Finding]` — aggregates all guards into blocking findings

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_promotion_preflight.py`:

```python
"""Preflight guards for the prod promotion runner (#516).

Every function here is pure — it takes plain data, so these tests need no
database, no network and no credentials.
"""
from pathlib import Path

from promotion.preflight import (
    Finding,
    evaluate,
    ledger_diff,
    project_ref,
    scan_destructive,
    staging_gap,
)

POOLER = "postgresql://postgres.abcdefghijklmnop:pw@aws-0-us-west-2.pooler.supabase.com:5432/postgres"
DIRECT = "postgresql://postgres:pw@db.abcdefghijklmnop.supabase.co:5432/postgres"
API = "https://abcdefghijklmnop.supabase.co"


def test_project_ref_from_pooler_uri():
    assert project_ref(POOLER) == "abcdefghijklmnop"


def test_project_ref_from_direct_uri():
    assert project_ref(DIRECT) == "abcdefghijklmnop"


def test_project_ref_from_api_url():
    assert project_ref(API) == "abcdefghijklmnop"


def test_project_ref_unknown_shape_is_empty():
    assert project_ref("postgresql://postgres:pw@127.0.0.1:54322/postgres") == ""


def test_ledger_diff_reports_pending_in_file_order():
    files = ["0001_a.sql", "0002_b.sql", "0003_c.sql"]
    pending, orphans = ledger_diff(files, {"0001_a.sql"})
    assert pending == ["0002_b.sql", "0003_c.sql"]
    assert orphans == []


def test_ledger_diff_reports_orphans():
    pending, orphans = ledger_diff(["0001_a.sql"], {"0001_a.sql", "0099_ghost.sql"})
    assert pending == []
    assert orphans == ["0099_ghost.sql"]


def test_staging_gap_flags_migrations_staging_never_ran():
    assert staging_gap(["0002_b.sql", "0003_c.sql"], {"0002_b.sql"}) == ["0003_c.sql"]


def test_staging_gap_empty_when_staging_is_ahead():
    assert staging_gap(["0002_b.sql"], {"0002_b.sql", "0003_c.sql"}) == []


def test_scan_destructive_flags_drop_table(tmp_path):
    f = tmp_path / "0050_x.sql"
    f.write_text("CREATE TABLE a (id int);\nDROP TABLE legacy_grades;\n")
    findings = scan_destructive([f])
    assert [x.kind for x in findings] == ["DROP TABLE"]
    assert "0050_x.sql:2" in findings[0].detail


def test_scan_destructive_flags_drop_column_and_truncate(tmp_path):
    f = tmp_path / "0051_y.sql"
    f.write_text("ALTER TABLE t DROP COLUMN old;\nTRUNCATE TABLE cache;\n")
    assert {x.kind for x in scan_destructive([f])} == {"DROP COLUMN", "TRUNCATE"}


def test_scan_destructive_flags_type_change(tmp_path):
    f = tmp_path / "0052_z.sql"
    f.write_text("ALTER TABLE t ALTER COLUMN amount TYPE numeric;\n")
    assert [x.kind for x in scan_destructive([f])] == ["ALTER COLUMN ... TYPE"]


def test_scan_destructive_ignores_line_comments(tmp_path):
    """The repo's migrations explain themselves at length; a mention is not a DROP."""
    f = tmp_path / "0053_c.sql"
    f.write_text("-- this replaces the old DROP TABLE approach\nCREATE TABLE ok (id int);\n")
    assert scan_destructive([f]) == []


def test_scan_destructive_ignores_block_comments(tmp_path):
    f = tmp_path / "0054_c.sql"
    f.write_text("/*\n  We used to TRUNCATE here.\n*/\nCREATE TABLE ok (id int);\n")
    assert scan_destructive([f]) == []


def test_scan_destructive_clean_migration_passes(tmp_path):
    f = tmp_path / "0055_ok.sql"
    f.write_text("CREATE TABLE IF NOT EXISTS t (id int);\nCREATE INDEX ON t (id);\n")
    assert scan_destructive([f]) == []


def _evaluate(**over):
    kwargs = dict(
        db_url=POOLER,
        supabase_url=API,
        ledger_exists=True,
        migration_files=["0001_a.sql", "0002_b.sql"],
        recorded={"0001_a.sql"},
        staging_recorded={"0001_a.sql", "0002_b.sql"},
        destructive=[],
        commits_ahead=3,
        allow_destructive=False,
        skip_staging_check=False,
    )
    kwargs.update(over)
    return evaluate(**kwargs)


def test_evaluate_clean_case_has_no_findings():
    assert _evaluate() == []


def test_evaluate_blocks_on_project_ref_mismatch():
    findings = _evaluate(supabase_url="https://zzzzzzzzzzzzzzzz.supabase.co")
    assert [f.kind for f in findings] == ["target-mismatch"]


def test_evaluate_blocks_when_ledger_missing():
    assert "no-ledger" in [f.kind for f in _evaluate(ledger_exists=False)]


def test_evaluate_blocks_on_orphans():
    findings = _evaluate(recorded={"0001_a.sql", "0099_ghost.sql"})
    assert "orphan" in [f.kind for f in findings]


def test_evaluate_blocks_when_staging_has_not_run_it():
    findings = _evaluate(staging_recorded={"0001_a.sql"})
    assert "staging-gap" in [f.kind for f in findings]


def test_evaluate_staging_check_can_be_skipped():
    findings = _evaluate(staging_recorded={"0001_a.sql"}, skip_staging_check=True)
    assert "staging-gap" not in [f.kind for f in findings]


def test_evaluate_blocks_on_destructive_ddl():
    findings = _evaluate(destructive=[Finding("DROP TABLE", "0002_b.sql:4: DROP TABLE x;")])
    assert "destructive" in [f.kind for f in findings]


def test_evaluate_destructive_can_be_allowed():
    findings = _evaluate(
        destructive=[Finding("DROP TABLE", "0002_b.sql:4: DROP TABLE x;")],
        allow_destructive=True,
    )
    assert "destructive" not in [f.kind for f in findings]


def test_evaluate_reports_nothing_to_promote():
    findings = _evaluate(commits_ahead=0, recorded={"0001_a.sql", "0002_b.sql"})
    assert [f.kind for f in findings] == ["nothing-to-promote"]


def test_evaluate_allows_a_migration_only_promotion():
    """Code is level but the schema is behind — that is still work to do."""
    findings = _evaluate(commits_ahead=0)  # default fixture leaves 0002_b.sql pending
    assert findings == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_promotion_preflight.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'promotion'`

- [ ] **Step 3: Create the package marker**

Create `backend/promotion/__init__.py`:

```python
"""Staging → production promotion runner (#516).

Sequences the promotion that used to be a hand-run list of commands: preflight,
snapshot, migrate, confirm, merge, wait for the deploy, smoke.

Each module splits pure logic from IO so the logic is testable without a
database or a network: `preflight` and `snapshot.diff` take plain data,
`smoke.run_checks` takes an injected fetcher, and `runner` takes injected
confirm/output callables.
"""
```

- [ ] **Step 4: Implement preflight.py**

Create `backend/promotion/preflight.py`:

```python
"""Read-only guards that must pass before production is touched (#516).

Every check here runs BEFORE any mutation. The functions are pure: callers hand
them already-fetched data (ledger rows, file lists, commit counts), which is
what keeps them testable offline and keeps the IO in one place — the runner.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

# Line-oriented, deliberately. A migration that is destructive on one line and
# harmless on the next should name the line, and the runner prints it verbatim
# so the operator judges the actual statement rather than a filename.
DESTRUCTIVE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("DROP TABLE", re.compile(r"\bDROP\s+TABLE\b", re.I)),
    ("DROP COLUMN", re.compile(r"\bDROP\s+COLUMN\b", re.I)),
    ("TRUNCATE", re.compile(r"\bTRUNCATE\b", re.I)),
    ("ALTER COLUMN ... TYPE", re.compile(r"\bALTER\s+COLUMN\b.*\bTYPE\b", re.I)),
]


@dataclass(frozen=True)
class Finding:
    """One blocking reason. `kind` is machine-readable, `detail` is for humans."""

    kind: str
    detail: str


def project_ref(value: str) -> str:
    """Supabase project ref from a DB URI or an API URL; "" if unrecognised.

    Three shapes are in play. The session-mode pooler carries the ref in the
    USERNAME (`postgres.<ref>@aws-0-...`) because the host is shared across
    projects; the direct endpoint carries it in the host (`db.<ref>.supabase.co`);
    the REST URL carries it as the leftmost label (`<ref>.supabase.co`).
    """
    parsed = urlparse(value)
    user = parsed.username or ""
    if user.startswith("postgres."):
        return user.split(".", 1)[1]
    host = parsed.hostname or ""
    if host.startswith("db.") and host.endswith(".supabase.co"):
        return host.split(".")[1]
    if host.endswith(".supabase.co"):
        return host.split(".")[0]
    return ""


def ledger_diff(files: list[str], recorded: set[str]) -> tuple[list[str], list[str]]:
    """(pending, orphans) — pending keeps `files` order, orphans are sorted.

    An orphan is a filename the ledger records that the repo does not have: that
    environment ran SQL this repo has never seen. Applying more on top compounds
    it, which is why the runner treats it as blocking.
    """
    pending = [f for f in files if f not in recorded]
    orphans = sorted(recorded - set(files))
    return pending, orphans


def staging_gap(pending: list[str], staging_recorded: set[str]) -> list[str]:
    """Pending-on-prod migrations staging has never executed.

    Production must never be the first environment to run a piece of DDL.
    """
    return [f for f in pending if f not in staging_recorded]


def _strip_comments(sql: str) -> str:
    """Blank out `--` line comments and `/* */` blocks, preserving line numbers.

    The migrations in this repo carry long explanatory headers that frequently
    NAME destructive statements while doing nothing of the kind. Scanning raw
    text would flag most of them.
    """
    without_blocks = re.sub(
        r"/\*.*?\*/",
        lambda m: re.sub(r"[^\n]", " ", m.group(0)),
        sql,
        flags=re.S,
    )
    return "\n".join(line.split("--", 1)[0] for line in without_blocks.splitlines())


def scan_destructive(paths: list[Path]) -> list[Finding]:
    """Destructive DDL in the given migration files.

    This matters because the runner applies migrations BEFORE the code merges,
    so between those stages the OLD production code runs against the NEW schema.
    Additive DDL is harmless in that window; destructive DDL is not.
    """
    findings: list[Finding] = []
    for path in paths:
        raw_lines = path.read_text().splitlines()
        scan_lines = _strip_comments("\n".join(raw_lines)).splitlines()
        for lineno, line in enumerate(scan_lines, 1):
            for label, pattern in DESTRUCTIVE_PATTERNS:
                if pattern.search(line):
                    original = raw_lines[lineno - 1].strip()
                    findings.append(Finding(label, f"{path.name}:{lineno}: {original}"))
    return findings


def evaluate(
    *,
    db_url: str,
    supabase_url: str,
    ledger_exists: bool,
    migration_files: list[str],
    recorded: set[str],
    staging_recorded: set[str],
    destructive: list[Finding],
    commits_ahead: int,
    allow_destructive: bool,
    skip_staging_check: bool,
) -> list[Finding]:
    """All blocking findings, in the order the operator should read them.

    An empty list means preflight passed and the runner may proceed.
    """
    findings: list[Finding] = []

    db_ref, api_ref = project_ref(db_url), project_ref(supabase_url)
    if db_ref and api_ref and db_ref != api_ref:
        findings.append(
            Finding(
                "target-mismatch",
                f"SUPABASE_DB_URL points at project {db_ref} but SUPABASE_URL "
                f"points at {api_ref}. The env file is mixed up — refusing to migrate.",
            )
        )

    if not ledger_exists:
        findings.append(
            Finding(
                "no-ledger",
                "schema_migrations does not exist on this database. Applying now "
                "would treat every migration as pending and fail recreating "
                "existing objects. Reconcile with `python -m db.migrate --baseline` "
                "against a verified-current schema first.",
            )
        )
        # Everything downstream reads the ledger, so stop describing it.
        return findings

    pending, orphans = ledger_diff(migration_files, recorded)
    for orphan in orphans:
        findings.append(
            Finding("orphan", f"recorded in the ledger but absent from the repo: {orphan}")
        )

    if not skip_staging_check:
        for name in staging_gap(pending, staging_recorded):
            findings.append(
                Finding(
                    "staging-gap",
                    f"{name} is pending on production but staging has never run it. "
                    "Production must not be the first environment to execute DDL. "
                    "Let migrate-staging.yml apply it first, or pass --skip-staging-check.",
                )
            )

    if destructive and not allow_destructive:
        for finding in destructive:
            findings.append(
                Finding(
                    "destructive",
                    f"{finding.kind} in a pending migration — {finding.detail}. "
                    "Migrations apply before the code merges, so the old production "
                    "code would run against this schema. Pass --allow-destructive "
                    "if that is genuinely safe here.",
                )
            )

    if commits_ahead == 0 and not pending:
        findings.append(
            Finding("nothing-to-promote", "origin/main and origin/production are identical.")
        )

    return findings
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && venv/bin/python -m pytest tests/test_promotion_preflight.py -v`
Expected: all PASS.

- [ ] **Step 6: Sanity-check the scanner against real migrations**

The scan must flag the known-destructive files and stay quiet on the additive ones. Run:

```bash
cd backend && venv/bin/python -c "
from pathlib import Path
from promotion.preflight import scan_destructive
d = Path('db/migrations')
for name in ['0013_drop_legacy_grade_tables.sql', '0021_gradebook.sql', '0030_documents_extracted_text.sql']:
    print(name, '->', [f.kind for f in scan_destructive([d / name])])
"
```

Expected: `0013_` and `0021_` report at least one kind; `0030_documents_extracted_text.sql` reports `[]`. If `0030_` reports a finding, the comment-stripping is wrong — fix it before moving on.

- [ ] **Step 7: Commit**

```bash
git add backend/promotion/__init__.py backend/promotion/preflight.py backend/tests/test_promotion_preflight.py
git commit -m "feat(promotion): read-only preflight guards for prod promotion (#516)"
```

---

### Task 3: `promotion/snapshot.py` — before/after evidence

**Files:**
- Create: `backend/promotion/snapshot.py`
- Test: `backend/tests/test_promotion_snapshot.py`

**Interfaces:**
- Consumes: `promotion` package from Task 2.
- Produces:
  - `capture(conn) -> dict` with keys `host`, `ledger_exists`, `ledger` (`list[str]`), `tables` (`dict[str, int]`)
  - `diff(before: dict, after: dict) -> dict` with keys `new_tables`, `dropped_tables`, `count_changes`, `new_migrations`
  - `format_diff(d: dict) -> str`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_promotion_snapshot.py`:

```python
"""Snapshot diffing for the promotion runner (#516).

`diff` and `format_diff` are pure, so they need no database. `capture` is a thin
psycopg shell exercised through a fake connection.
"""
from promotion.snapshot import capture, diff, format_diff


class FakeCursor:
    def __init__(self, script):
        self._script = script
        self._rows = []

    def execute(self, sql, params=None):
        for fragment, rows in self._script:
            if fragment in " ".join(sql.split()):
                self._rows = rows
                return
        raise AssertionError(f"unexpected SQL: {sql}")

    def fetchone(self):
        return self._rows[0]

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, script):
        self._script = script
        self.info = type("info", (), {"host": "aws-0-us-west-2.pooler.supabase.com"})()

    def cursor(self):
        return FakeCursor(self._script)


def test_capture_collects_ledger_and_counts():
    conn = FakeConn(
        [
            ("to_regclass", [(True,)]),
            ("FROM schema_migrations", [("0001_a.sql",), ("0002_b.sql",)]),
            ("information_schema.tables", [("users",), ("notes",)]),
            ("SELECT count(*) FROM public.users", [(8,)]),
            ("SELECT count(*) FROM public.notes", [(0,)]),
        ]
    )
    snap = capture(conn)
    assert snap["ledger_exists"] is True
    assert snap["ledger"] == ["0001_a.sql", "0002_b.sql"]
    assert snap["tables"] == {"users": 8, "notes": 0}
    assert snap["host"] == "aws-0-us-west-2.pooler.supabase.com"


def test_capture_handles_missing_ledger():
    conn = FakeConn(
        [
            ("to_regclass", [(False,)]),
            ("information_schema.tables", [("users",)]),
            ("SELECT count(*) FROM public.users", [(3,)]),
        ]
    )
    snap = capture(conn)
    assert snap["ledger_exists"] is False
    assert snap["ledger"] == []


BEFORE = {"tables": {"users": 8, "terms": 4}, "ledger": ["0001_a.sql"]}
AFTER = {"tables": {"users": 8, "terms": 3, "events": 0}, "ledger": ["0001_a.sql", "0002_b.sql"]}


def test_diff_reports_new_tables():
    assert diff(BEFORE, AFTER)["new_tables"] == ["events"]


def test_diff_reports_dropped_tables():
    assert diff(AFTER, BEFORE)["dropped_tables"] == ["events"]


def test_diff_reports_row_count_changes():
    assert diff(BEFORE, AFTER)["count_changes"] == {"terms": (4, 3)}


def test_diff_reports_new_migrations():
    assert diff(BEFORE, AFTER)["new_migrations"] == ["0002_b.sql"]


def test_diff_of_identical_snapshots_is_empty():
    d = diff(BEFORE, BEFORE)
    assert d["new_tables"] == [] and d["dropped_tables"] == []
    assert d["count_changes"] == {} and d["new_migrations"] == []


def test_format_diff_mentions_every_change():
    text = format_diff(diff(BEFORE, AFTER))
    assert "events" in text and "terms" in text and "0002_b.sql" in text


def test_format_diff_says_no_change_when_empty():
    assert "no schema or row-count changes" in format_diff(diff(BEFORE, BEFORE))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_promotion_snapshot.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'promotion.snapshot'`

- [ ] **Step 3: Implement snapshot.py**

Create `backend/promotion/snapshot.py`:

```python
"""Before/after snapshots of the production database (#516).

The point is evidence, not monitoring: capture once before migrating and once
after, then diff, so the operator confirming the merge sees exactly what the
migration did — and so a failed promotion has an artifact to reason about
instead of terminal scrollback.

SELECTs only. Nothing here writes.
"""
from __future__ import annotations

LEDGER_EXISTS_SQL = "SELECT to_regclass('public.schema_migrations') IS NOT NULL"
LEDGER_SQL = "SELECT filename FROM schema_migrations ORDER BY filename"
TABLES_SQL = """
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
    ORDER BY table_name
"""


def capture(conn) -> dict:
    """Ledger contents and per-table row counts for the connected database."""
    snapshot: dict = {"host": getattr(conn.info, "host", "unknown")}

    with conn.cursor() as cur:
        cur.execute(LEDGER_EXISTS_SQL)
        exists = bool(cur.fetchone()[0])
        snapshot["ledger_exists"] = exists

        ledger: list[str] = []
        if exists:
            cur.execute(LEDGER_SQL)
            ledger = [row[0] for row in cur.fetchall()]
        snapshot["ledger"] = ledger

        cur.execute(TABLES_SQL)
        names = [row[0] for row in cur.fetchall()]

        counts: dict[str, int] = {}
        for name in names:
            # Identifier comes from information_schema, never from user input,
            # and count(*) takes no bindable parameter for a table name.
            cur.execute(f'SELECT count(*) FROM public."{name}"')
            counts[name] = cur.fetchone()[0]
        snapshot["tables"] = counts

    return snapshot


def diff(before: dict, after: dict) -> dict:
    """What changed between two snapshots."""
    b, a = before.get("tables", {}), after.get("tables", {})
    return {
        "new_tables": sorted(set(a) - set(b)),
        "dropped_tables": sorted(set(b) - set(a)),
        "count_changes": {k: (b[k], a[k]) for k in sorted(set(b) & set(a)) if b[k] != a[k]},
        "new_migrations": [m for m in after.get("ledger", []) if m not in set(before.get("ledger", []))],
    }


def format_diff(d: dict) -> str:
    """Human-readable diff for the confirmation prompt and the final report."""
    lines: list[str] = []
    if d["new_migrations"]:
        lines.append(f"  migrations applied ({len(d['new_migrations'])}):")
        lines += [f"    + {m}" for m in d["new_migrations"]]
    if d["new_tables"]:
        lines.append(f"  new tables: {', '.join(d['new_tables'])}")
    if d["dropped_tables"]:
        lines.append(f"  DROPPED tables: {', '.join(d['dropped_tables'])}")
    if d["count_changes"]:
        lines.append("  row-count changes:")
        lines += [f"    {t}: {old} -> {new}" for t, (old, new) in d["count_changes"].items()]
    return "\n".join(lines) if lines else "  no schema or row-count changes"
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && venv/bin/python -m pytest tests/test_promotion_snapshot.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/promotion/snapshot.py backend/tests/test_promotion_snapshot.py
git commit -m "feat(promotion): prod snapshot capture and diff (#516)"
```

---

### Task 4: `promotion/smoke.py` — the durable post-deploy checks

**Files:**
- Create: `backend/promotion/smoke.py`
- Test: `backend/tests/test_promotion_smoke.py`

**Interfaces:**
- Consumes: `promotion` package.
- Produces:
  - `Check(name, target, path, expect_status: tuple[int, ...], expect_body: str = "", method: str = "GET")` — frozen dataclass
  - `CHECKS: list[Check]`
  - `Result(check, ok: bool, status: int | None, detail: str)`
  - `run_checks(fetch, api_base, web_base, checks=CHECKS) -> list[Result]` where `fetch(method, url) -> tuple[int | None, str]`
  - `httpx_fetch(method, url) -> tuple[int | None, str]` — the real IO
  - `format_results(results) -> str`
  - `live_commit(fetch, api_base) -> str` — the deployed SHA from `/api/health`, `""` if unreachable

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_promotion_smoke.py`:

```python
"""Post-deploy smoke checks for the promotion runner (#516).

`run_checks` takes an injected fetcher, so these tests make no network calls.
"""
import json

from promotion.smoke import CHECKS, Check, format_results, live_commit, run_checks

API = "https://api.example.test"
WEB = "https://example.test"

HEALTH_BODY = json.dumps({"status": "ok", "service": "sapling-backend", "commit": "abc1234"})


def fetcher(routes):
    """Build a fetch(method, url) -> (status, body) from a {(method, url): (status, body)} map."""

    def fetch(method, url):
        return routes.get((method, url), (404, "not found"))

    return fetch


def test_check_passes_on_expected_status_and_body():
    check = Check(name="health", target="api", path="/api/health", expect_status=(200,), expect_body='"status":"ok"')
    fetch = fetcher({("GET", f"{API}/api/health"): (200, '{"status":"ok"}')})
    [result] = run_checks(fetch, API, WEB, [check])
    assert result.ok is True
    assert result.status == 200


def test_check_fails_on_wrong_status():
    check = Check(name="health", target="api", path="/api/health", expect_status=(200,))
    fetch = fetcher({("GET", f"{API}/api/health"): (503, "down")})
    [result] = run_checks(fetch, API, WEB, [check])
    assert result.ok is False
    assert "503" in result.detail


def test_check_fails_when_body_marker_missing():
    check = Check(name="health", target="api", path="/api/health", expect_status=(200,), expect_body='"status":"ok"')
    fetch = fetcher({("GET", f"{API}/api/health"): (200, '{"status":"degraded"}')})
    [result] = run_checks(fetch, API, WEB, [check])
    assert result.ok is False
    assert "missing" in result.detail


def test_guarded_route_counts_401_as_mounted():
    """A 401 proves the router is mounted; the pre-promotion failure mode was 404."""
    check = Check(name="analytics", target="api", path="/api/admin/analytics/usage/summary", expect_status=(401, 403))
    fetch = fetcher({("GET", f"{API}/api/admin/analytics/usage/summary"): (401, "")})
    [result] = run_checks(fetch, API, WEB, [check])
    assert result.ok is True


def test_guarded_route_fails_on_404():
    check = Check(name="analytics", target="api", path="/api/admin/analytics/usage/summary", expect_status=(401, 403))
    fetch = fetcher({("GET", f"{API}/api/admin/analytics/usage/summary"): (404, "")})
    [result] = run_checks(fetch, API, WEB, [check])
    assert result.ok is False


def test_web_target_uses_the_web_base():
    check = Check(name="web root", target="web", path="/", expect_status=(200,))
    fetch = fetcher({("GET", f"{WEB}/"): (200, "<html>")})
    [result] = run_checks(fetch, API, WEB, [check])
    assert result.ok is True


def test_unreachable_host_is_a_failure_not_a_crash():
    def fetch(method, url):
        return None, "connection refused"

    [result] = run_checks(fetch, API, WEB, [Check(name="health", target="api", path="/api/health", expect_status=(200,))])
    assert result.ok is False
    assert result.status is None


def test_default_checks_cover_the_promotion_surface():
    paths = {c.path for c in CHECKS}
    assert "/api/health" in paths
    assert "/api/semesters" in paths
    assert "/api/admin/analytics/usage/summary" in paths
    assert "/api/auth/test-login" in paths
    assert "/" in paths


def test_default_checks_have_no_term_specific_assertions():
    """#515's fall-2026 assertions were promotion-specific and would rot."""
    for check in CHECKS:
        assert "fall-2026" not in check.expect_body
        assert "2026-05-18" not in check.expect_body


def test_test_login_check_is_a_post_expecting_404():
    [check] = [c for c in CHECKS if c.path == "/api/auth/test-login"]
    assert check.method == "POST"
    assert check.expect_status == (404,)


def test_live_commit_reads_health():
    fetch = fetcher({("GET", f"{API}/api/health"): (200, HEALTH_BODY)})
    assert live_commit(fetch, API) == "abc1234"


def test_live_commit_empty_when_unreachable():
    def fetch(method, url):
        return None, ""

    assert live_commit(fetch, API) == ""


def test_live_commit_empty_on_unparseable_body():
    fetch = fetcher({("GET", f"{API}/api/health"): (200, "<html>502</html>")})
    assert live_commit(fetch, API) == ""


def test_format_results_marks_pass_and_fail():
    check = Check(name="health", target="api", path="/api/health", expect_status=(200,))
    fetch = fetcher({("GET", f"{API}/api/health"): (500, "boom")})
    text = format_results(run_checks(fetch, API, WEB, [check]))
    assert "FAIL" in text and "health" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_promotion_smoke.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'promotion.smoke'`

- [ ] **Step 3: Implement smoke.py**

Create `backend/promotion/smoke.py`:

```python
"""Post-deploy smoke checks against the live production surface (#516).

Unauthenticated surface only. A 401/403 on a guarded route is a PASS: it proves
the router is MOUNTED, and the failure mode this catches is a 404 from code that
never shipped.

Checks are DATA, and the fetcher is injected, so the suite is testable without a
network. Deliberately excluded: assertions about specific term data (#515 asserted
`fall-2026` and a start date), which pass today and rot next term.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

DEFAULT_API = "https://api.saplinglearn.com"
DEFAULT_WEB = "https://saplinglearn.com"


@dataclass(frozen=True)
class Check:
    name: str
    target: str  # "api" | "web"
    path: str
    expect_status: tuple[int, ...]
    expect_body: str = ""
    method: str = "GET"


@dataclass
class Result:
    check: Check
    ok: bool
    status: int | None
    detail: str


CHECKS: list[Check] = [
    Check("api health", "api", "/api/health", (200,), '"status":"ok"'),
    # Mounted-not-404. These routers only exist in promoted code.
    Check("academics mounted", "api", "/api/semesters", (200,)),
    Check("notes mounted", "api", "/api/notes", (200, 401, 403, 405)),
    Check("admin analytics mounted", "api", "/api/admin/analytics/usage/summary", (401, 403)),
    Check("auth entrypoint", "api", "/api/auth/google", (200, 302, 307, 400, 401)),
    # The local/test session minter must be OFF in production. POST specifically:
    # a GET returns 405, which would mask a live endpoint.
    Check("test-login disabled", "api", "/api/auth/test-login", (404,), method="POST"),
    Check("web root", "web", "/", (200,), "<"),
    # Proves the frontend worker's build-time BACKEND_URL is right; a wrong one 500s.
    Check("web -> api proxy", "web", "/api/health", (200,), '"status":"ok"'),
]


def run_checks(fetch, api_base: str, web_base: str, checks: list[Check] | None = None) -> list[Result]:
    """Run each check through `fetch(method, url) -> (status | None, body)`."""
    results: list[Result] = []
    for check in checks if checks is not None else CHECKS:
        base = api_base if check.target == "api" else web_base
        url = f"{base.rstrip('/')}{check.path}"
        status, body = fetch(check.method, url)

        if status is None:
            results.append(Result(check, False, None, f"no response from {url}: {body[:120]}"))
            continue
        if status not in check.expect_status:
            expected = "/".join(str(s) for s in check.expect_status)
            results.append(Result(check, False, status, f"{url} -> {status}, expected {expected}"))
            continue
        if check.expect_body and check.expect_body not in body:
            results.append(Result(check, False, status, f"{url} -> {status} but missing {check.expect_body!r}"))
            continue
        results.append(Result(check, True, status, f"{url} -> {status}"))
    return results


def live_commit(fetch, api_base: str) -> str:
    """Deployed short SHA from /api/health, or "" if unreachable/unparseable."""
    status, body = fetch("GET", f"{api_base.rstrip('/')}/api/health")
    if status != 200:
        return ""
    try:
        return str(json.loads(body).get("commit", ""))
    except (ValueError, AttributeError):
        return ""


def format_results(results: list[Result]) -> str:
    return "\n".join(
        f"  {'PASS' if r.ok else 'FAIL'}  {r.check.name}  ({r.detail})" for r in results
    )


def httpx_fetch(method: str, url: str) -> tuple[int | None, str]:
    """Real IO. Imported lazily so importing this module costs nothing."""
    import httpx

    try:
        response = httpx.request(method, url, timeout=25.0, follow_redirects=False)
        return response.status_code, response.text
    except httpx.HTTPError as exc:  # DNS, TLS, timeout, refused
        return None, str(exc)
```

- [ ] **Step 4: Run the tests and lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_promotion_smoke.py -v && venv/bin/ruff check promotion/`
Expected: tests PASS, ruff clean. If ruff flags the unused `field` import, remove it.

- [ ] **Step 5: Commit**

```bash
git add backend/promotion/smoke.py backend/tests/test_promotion_smoke.py
git commit -m "feat(promotion): durable post-deploy smoke checks (#516)"
```

---

### Task 5: `promotion/runner.py` — sequencing, the one prompt, the report

**Files:**
- Create: `backend/promotion/runner.py`
- Create: `backend/promotion/__main__.py`
- Test: `backend/tests/test_promotion_runner.py`

**Interfaces:**
- Consumes: `preflight.evaluate`, `snapshot.capture/diff/format_diff`, `smoke.run_checks/live_commit/format_results`, `db.migrate.run`.
- Produces:
  - `Ports` dataclass bundling every injected callable: `connect`, `git`, `gh`, `fetch`, `confirm`, `out`, `sleep`
  - `Options` dataclass: `allow_destructive`, `skip_staging_check`, `api_base`, `web_base`, `wait_timeout`, `poll_interval`
  - `run(ports: Ports, options: Options) -> int` — process exit code (0 success, 1 failure, 2 aborted by operator)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_promotion_runner.py`:

```python
"""Stage sequencing for the promotion runner (#516).

Every port is injected, so the whole flow runs in-process with no database,
no network, no git and no gh.
"""
import json

import pytest

from promotion.runner import Options, Ports, run
from promotion.preflight import Finding

HEALTH_OLD = json.dumps({"status": "ok", "commit": "old1111"})
HEALTH_NEW = json.dumps({"status": "ok", "commit": "new2222"})


class FakeGit:
    def __init__(self, head="new2222", commits_ahead=3):
        self.head = head
        self.commits_ahead = commits_ahead
        self.calls = []

    def fetch(self):
        self.calls.append("fetch")

    def head_sha(self, ref):
        self.calls.append(f"head:{ref}")
        return self.head

    def commits_ahead_of(self, base, head):
        return self.commits_ahead


class FakeGh:
    def __init__(self):
        self.merged = False
        self.calls = []

    def ensure_pr(self, base, head, title):
        self.calls.append("ensure_pr")
        return 999

    def state(self, number):
        return "MERGED" if self.merged else "OPEN"

    def merge(self, number):
        self.calls.append("merge")
        self.merged = True


def make_ports(**over):
    """Happy path by default; override one port per test."""
    fake_git, fake_gh = FakeGit(), FakeGh()
    healths = [HEALTH_OLD, HEALTH_NEW, HEALTH_NEW, HEALTH_NEW, HEALTH_NEW]

    def fetch(method, url):
        if url.endswith("/api/health"):
            return 200, healths.pop(0) if healths else HEALTH_NEW
        if url.endswith("/api/auth/test-login"):
            return 404, ""
        if "analytics" in url:
            return 401, ""
        return 200, "<html>"

    ports = dict(
        connect=lambda: FakeConn(),
        migrate=lambda conn: ["0002_b.sql"],
        preflight_data=lambda conn: dict(
            ledger_exists=True,
            migration_files=["0001_a.sql", "0002_b.sql"],
            recorded={"0001_a.sql"},
            staging_recorded={"0001_a.sql", "0002_b.sql"},
            destructive=[],
            db_url="postgresql://postgres.ref1:p@aws-0-us-west-2.pooler.supabase.com:5432/postgres",
            supabase_url="https://ref1.supabase.co",
        ),
        snapshots=[
            {"tables": {"users": 8}, "ledger": ["0001_a.sql"]},
            {"tables": {"users": 8, "events": 0}, "ledger": ["0001_a.sql", "0002_b.sql"]},
        ],
        git=fake_git,
        gh=fake_gh,
        fetch=fetch,
        confirm=lambda prompt: True,
        out=lambda line: None,
        sleep=lambda seconds: None,
    )
    ports.update(over)
    return ports


class FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def build(ports_kwargs, **option_over):
    """Assemble Ports/Options from the dict make_ports returns."""
    snapshots = list(ports_kwargs.pop("snapshots"))
    preflight_data = ports_kwargs.pop("preflight_data")
    migrate = ports_kwargs.pop("migrate")
    ports = Ports(
        connect=ports_kwargs["connect"],
        preflight_data=preflight_data,
        capture=lambda conn: snapshots.pop(0),
        migrate=migrate,
        git=ports_kwargs["git"],
        gh=ports_kwargs["gh"],
        fetch=ports_kwargs["fetch"],
        confirm=ports_kwargs["confirm"],
        out=ports_kwargs["out"],
        sleep=ports_kwargs["sleep"],
    )
    options = Options(**{"wait_timeout": 5, "poll_interval": 0, **option_over})
    return ports, options


def test_happy_path_returns_zero_and_merges():
    kwargs = make_ports()
    gh = kwargs["gh"]
    assert run(*build(kwargs)) == 0
    assert "merge" in gh.calls


def test_preflight_failure_aborts_before_migrating():
    migrated = []
    kwargs = make_ports(migrate=lambda conn: migrated.append(1) or [])
    kwargs["preflight_data"] = lambda conn: dict(
        ledger_exists=True,
        migration_files=["0001_a.sql"],
        recorded={"0001_a.sql", "0099_ghost.sql"},  # orphan
        staging_recorded={"0001_a.sql"},
        destructive=[],
        db_url="postgresql://postgres.ref1:p@aws-0-us-west-2.pooler.supabase.com:5432/postgres",
        supabase_url="https://ref1.supabase.co",
    )
    assert run(*build(kwargs)) == 1
    assert migrated == []
    assert kwargs["gh"].calls == []


def test_declining_the_prompt_stops_without_merging():
    kwargs = make_ports(confirm=lambda prompt: False)
    gh = kwargs["gh"]
    assert run(*build(kwargs)) == 2
    assert gh.calls == []


def test_declining_warns_that_migrations_already_applied():
    lines = []
    kwargs = make_ports(confirm=lambda prompt: False, out=lines.append)
    run(*build(kwargs))
    text = "\n".join(lines).lower()
    assert "schema" in text and "ahead" in text


def test_wait_timeout_does_not_run_smoke():
    """A deploy that never lands must not be reported as a smoke failure."""
    def fetch(method, url):
        if url.endswith("/api/health"):
            return 200, HEALTH_OLD  # never advances
        raise AssertionError("smoke must not run after a wait timeout")

    kwargs = make_ports(fetch=fetch)
    assert run(*build(kwargs)) == 1


def test_smoke_failure_returns_nonzero():
    def fetch(method, url):
        if url.endswith("/api/health"):
            return 200, HEALTH_NEW
        return 500, "boom"

    kwargs = make_ports(fetch=fetch)
    assert run(*build(kwargs)) == 1


def test_smoke_failure_prints_the_revert_command():
    lines = []

    def fetch(method, url):
        if url.endswith("/api/health"):
            return 200, HEALTH_NEW
        return 500, "boom"

    kwargs = make_ports(fetch=fetch, out=lines.append)
    run(*build(kwargs))
    assert "git revert" in "\n".join(lines)


def test_smoke_failure_does_not_revert_anything():
    def fetch(method, url):
        if url.endswith("/api/health"):
            return 200, HEALTH_NEW
        return 500, "boom"

    kwargs = make_ports(fetch=fetch)
    gh = kwargs["gh"]
    run(*build(kwargs))
    assert "revert" not in " ".join(gh.calls)


def test_merge_retries_through_a_transient_failure():
    """The known gh squash-merge 502: error raised, but the PR does merge."""

    class FlakyGh(FakeGh):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        def merge(self, number):
            self.attempts += 1
            self.merged = True  # it landed despite the error
            if self.attempts == 1:
                raise RuntimeError("HTTP 502")

    kwargs = make_ports(gh=FlakyGh())
    assert run(*build(kwargs)) == 0


def test_nothing_to_promote_exits_clean():
    kwargs = make_ports()
    kwargs["git"].commits_ahead = 0
    kwargs["preflight_data"] = lambda conn: dict(
        ledger_exists=True,
        migration_files=["0001_a.sql"],
        recorded={"0001_a.sql"},
        staging_recorded={"0001_a.sql"},
        destructive=[],
        db_url="postgresql://postgres.ref1:p@aws-0-us-west-2.pooler.supabase.com:5432/postgres",
        supabase_url="https://ref1.supabase.co",
    )
    assert run(*build(kwargs)) == 0


def test_already_merged_pr_resumes_at_wait_and_smoke():
    """Re-running after a failure must not re-merge."""
    kwargs = make_ports()
    gh = kwargs["gh"]
    gh.merged = True
    assert run(*build(kwargs)) == 0
    assert "merge" not in gh.calls


def test_unknown_live_commit_degrades_instead_of_hanging():
    """No Railway env var: don't wait forever, warn and smoke anyway."""
    def fetch(method, url):
        if url.endswith("/api/health"):
            return 200, json.dumps({"status": "ok", "commit": "unknown"})
        if url.endswith("/api/auth/test-login"):
            return 404, ""
        if "analytics" in url:
            return 401, ""
        return 200, "<html>"

    lines = []
    kwargs = make_ports(fetch=fetch, out=lines.append)
    assert run(*build(kwargs)) == 0
    assert "unknown" in "\n".join(lines).lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_promotion_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'promotion.runner'`

- [ ] **Step 3: Implement runner.py**

Create `backend/promotion/runner.py`:

```python
"""Stage sequencing for the staging -> production promotion (#516).

Ordering is DB-first: migrations apply BEFORE the code merges, which is what the
destructive-DDL guard in preflight exists to protect. Between the migrate stage
and the merge, the OLD production code runs against the NEW schema.

Every side effect is an injected port, so the whole sequence is testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from promotion import preflight, smoke, snapshot

EXIT_OK, EXIT_FAIL, EXIT_ABORTED = 0, 1, 2


@dataclass
class Ports:
    connect: Callable[[], Any]
    preflight_data: Callable[[Any], dict]
    capture: Callable[[Any], dict]
    migrate: Callable[[Any], list[str]]
    git: Any
    gh: Any
    fetch: Callable[[str, str], tuple[int | None, str]]
    confirm: Callable[[str], bool]
    out: Callable[[str], None]
    sleep: Callable[[float], None]


@dataclass
class Options:
    allow_destructive: bool = False
    skip_staging_check: bool = False
    api_base: str = smoke.DEFAULT_API
    web_base: str = smoke.DEFAULT_WEB
    wait_timeout: int = 600
    poll_interval: int = 10


def run(ports: Ports, options: Options) -> int:
    out = ports.out

    # ---- Stage 1: preflight (read-only) --------------------------------
    ports.git.fetch()
    head = ports.git.head_sha("origin/main")
    commits_ahead = ports.git.commits_ahead_of("origin/production", "origin/main")

    with ports.connect() as conn:
        data = ports.preflight_data(conn)
        findings = preflight.evaluate(
            commits_ahead=commits_ahead,
            allow_destructive=options.allow_destructive,
            skip_staging_check=options.skip_staging_check,
            **data,
        )

        if findings:
            blocking = [f for f in findings if f.kind != "nothing-to-promote"]
            for finding in findings:
                out(f"  [{finding.kind}] {finding.detail}")
            if not blocking:
                out("Nothing to promote — production already matches main.")
                return EXIT_OK
            out("\nPREFLIGHT FAILED — production was not touched.")
            return EXIT_FAIL

        pending, _ = preflight.ledger_diff(data["migration_files"], data["recorded"])
        out(f"Preflight OK. {commits_ahead} commit(s) to promote, {len(pending)} migration(s) pending.")

        # ---- Stage 2-4: snapshot, migrate, snapshot --------------------
        before = ports.capture(conn)
        if pending:
            applied = ports.migrate(conn)
            out(f"Applied {len(applied)} migration(s).")
        after = ports.capture(conn)

    changes = snapshot.diff(before, after)
    out("\nDatabase changes:")
    out(snapshot.format_diff(changes))

    # ---- The one pause ------------------------------------------------
    number = ports.gh.ensure_pr("production", "main", f"Promote staging to production — {commits_ahead} commits")
    already_merged = ports.gh.state(number) == "MERGED"

    if not already_merged:
        prompt = (
            f"\nMerge PR #{number} ({commits_ahead} commits, "
            f"{len(changes['new_migrations'])} migrations applied) into production?"
        )
        if not ports.confirm(prompt):
            out(
                "\nABORTED before the merge.\n"
                "  NOTE: the migrations above are ALREADY APPLIED. Production's "
                "schema is now AHEAD of production's code.\n"
                "  Re-run to resume at the merge, or revert deliberately."
            )
            return EXIT_ABORTED

        # The squash-merge 502 wedge: gh can error while the merge lands. Never
        # trust the first failure — re-read the PR state.
        for attempt in range(5):
            try:
                ports.gh.merge(number)
            except Exception as exc:  # noqa: BLE001 — any gh failure gets re-checked
                out(f"  merge attempt {attempt + 1} errored ({exc}); re-checking PR state")
            if ports.gh.state(number) == "MERGED":
                break
            ports.sleep(options.poll_interval)
        else:
            out(f"\nPR #{number} never reported MERGED. Production code unchanged.")
            return EXIT_FAIL
    else:
        out(f"PR #{number} is already merged — resuming at the deploy wait.")

    out(f"Merged. Waiting for the deploy to report {head[:7]}.")

    # ---- Stage 6: wait for the deploy ---------------------------------
    waited = 0
    while waited < options.wait_timeout:
        live = smoke.live_commit(ports.fetch, options.api_base)
        if live == head[:7]:
            out(f"  deploy is live ({live}).")
            break
        if live == "unknown":
            out(
                "  WARNING: /api/health reports commit 'unknown' — the host is not "
                "injecting a commit SHA, so the deploy cannot be confirmed. "
                "Proceeding to smoke anyway."
            )
            break
        ports.sleep(options.poll_interval)
        waited += options.poll_interval
    else:
        out(
            f"\nTIMEOUT: the deploy never reported {head[:7]} after "
            f"{options.wait_timeout}s. NOT running smoke — a deploy failure must "
            "not look like a smoke failure. Check the Railway build."
        )
        return EXIT_FAIL

    # ---- Stage 7: smoke ------------------------------------------------
    results = smoke.run_checks(ports.fetch, options.api_base, options.web_base)
    out("\nSmoke:")
    out(smoke.format_results(results))

    if any(not r.ok for r in results):
        out(
            "\nSMOKE FAILED. Production was NOT reverted — the applied migrations "
            "cannot be rolled back, so reverting the code would leave old code "
            "against a newer schema.\n"
            "  To revert deliberately:\n"
            "    git checkout production && git revert -m 1 HEAD && git push origin production"
        )
        return EXIT_FAIL

    out("\nPROMOTION COMPLETE — all smoke checks passed.")
    return EXIT_OK
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && venv/bin/python -m pytest tests/test_promotion_runner.py -v`
Expected: all PASS. If `test_nothing_to_promote_exits_clean` fails, check that `evaluate` only emits `nothing-to-promote` when there are also no pending migrations.

- [ ] **Step 5: Implement the CLI entry point**

Create `backend/promotion/__main__.py`:

```python
"""`python -m promotion` — the real ports wired to the real world (#516).

Run from backend/ with production's env loaded:

    venv/bin/dotenv -f .env.production run -- venv/bin/python -m promotion

Flags:
    --allow-destructive      proceed despite destructive DDL in pending migrations
    --skip-staging-check     proceed despite migrations staging has never run
    --yes                    answer the confirmation prompt automatically (CI)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import psycopg

from db import migrate as db_migrate
from promotion import preflight, smoke, snapshot
from promotion.runner import Options, Ports, run


class Git:
    def fetch(self) -> None:
        subprocess.run(["git", "fetch", "origin", "--quiet"], check=True)

    def head_sha(self, ref: str) -> str:
        return subprocess.run(
            ["git", "rev-parse", ref], check=True, capture_output=True, text=True
        ).stdout.strip()

    def commits_ahead_of(self, base: str, head: str) -> int:
        result = subprocess.run(
            ["git", "rev-list", "--count", f"{base}..{head}"],
            check=True, capture_output=True, text=True,
        )
        return int(result.stdout.strip())


class Gh:
    def ensure_pr(self, base: str, head: str, title: str) -> int:
        existing = subprocess.run(
            ["gh", "pr", "list", "--base", base, "--head", head, "--state", "all",
             "--limit", "1", "--json", "number,state", "--jq", ".[0].number // empty"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        if existing:
            return int(existing)
        subprocess.run(
            ["gh", "pr", "create", "--base", base, "--head", head,
             "--title", title, "--body", "Automated promotion (#516)."],
            check=True, capture_output=True, text=True,
        )
        return self.ensure_pr(base, head, title)

    def state(self, number: int) -> str:
        return subprocess.run(
            ["gh", "pr", "view", str(number), "--json", "state", "--jq", ".state"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

    def merge(self, number: int) -> None:
        subprocess.run(["gh", "pr", "merge", str(number), "--merge"],
                       check=True, capture_output=True, text=True)


def _staging_recorded() -> set[str]:
    """Staging's ledger, so preflight can refuse DDL staging never ran."""
    url = os.environ.get("STAGING_SUPABASE_DB_URL", "").strip()
    if not url:
        return set()
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT filename FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}


def _preflight_data(conn) -> dict:
    files = [p.name for p in db_migrate.discover_migrations(db_migrate.MIGRATIONS_DIR)]
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.schema_migrations') IS NOT NULL")
        exists = bool(cur.fetchone()[0])
        recorded: set[str] = set()
        if exists:
            cur.execute("SELECT filename FROM schema_migrations")
            recorded = {row[0] for row in cur.fetchall()}

    pending, _ = preflight.ledger_diff(files, recorded)
    pending_paths = [db_migrate.MIGRATIONS_DIR / name for name in pending]
    return {
        "db_url": os.environ.get("SUPABASE_DB_URL", ""),
        "supabase_url": os.environ.get("SUPABASE_URL", ""),
        "ledger_exists": exists,
        "migration_files": files,
        "recorded": recorded,
        "staging_recorded": _staging_recorded(),
        "destructive": preflight.scan_destructive(pending_paths),
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="promotion")
    parser.add_argument("--allow-destructive", action="store_true")
    parser.add_argument("--skip-staging-check", action="store_true")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    db_url = os.environ.get("SUPABASE_DB_URL", "").strip()
    if not db_url:
        print(
            "ERROR: SUPABASE_DB_URL is not set. Run under production's env:\n"
            "  venv/bin/dotenv -f .env.production run -- venv/bin/python -m promotion\n"
            "It must be the SESSION-mode pooler URI (port 5432, user postgres.<ref>); "
            "production is on the aws-0-us-west-2 cluster. Build it with "
            "`python scripts/pooler_url.py .env.production aws-0-us-west-2 --raw`.",
            file=sys.stderr,
        )
        return 1

    def confirm(prompt: str) -> bool:
        if args.yes:
            return True
        return input(f"{prompt} [y/N] ").strip().lower() in {"y", "yes"}

    ports = Ports(
        connect=lambda: psycopg.connect(db_url),
        preflight_data=_preflight_data,
        capture=snapshot.capture,
        migrate=lambda conn: db_migrate.run(conn),
        git=Git(),
        gh=Gh(),
        fetch=smoke.httpx_fetch,
        confirm=confirm,
        out=print,
        sleep=time.sleep,
    )
    return run(ports, Options(
        allow_destructive=args.allow_destructive,
        skip_staging_check=args.skip_staging_check,
    ))


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Verify the CLI refuses to run without credentials**

Run: `cd backend && env -u SUPABASE_DB_URL venv/bin/python -m promotion`
Expected: exits 1 with the pooler instructions. **It must not connect to anything.**

- [ ] **Step 7: Run the full backend suite**

Run: `cd backend && venv/bin/python -m pytest tests/ -q && venv/bin/ruff check .`
Expected: green; read the pass/skip counts. `ruff` clean.

- [ ] **Step 8: Commit**

```bash
git add backend/promotion/runner.py backend/promotion/__main__.py backend/tests/test_promotion_runner.py
git commit -m "feat(promotion): stage sequencing, confirmation gate and CLI (#516)"
```

---

### Task 6: `make promote`, the runbook, and artifact cleanup

**Files:**
- Modify: `Makefile` (add target + `.PHONY`)
- Create: `backend/promotion/README.md`
- Modify: `CLAUDE.md` (Commands section)
- Delete: `backend/prod_snapshot.py`, `backend/prod_db_check.py`, `backend/smoke_prod_app.sh`, `backend/smoke_prod_promotion.sh`, `backend/prod_snapshot_*.json`

**Do NOT delete** `backend/apply_graph_edges_fix.py` or `backend/graph_edges_fix.sql`. Those are a separate production reconciliation (the `graph_edges` table missing from 0023), unrelated to promotion. Ruled out of scope by the human partner during pre-flight.

**Interfaces:**
- Consumes: `python -m promotion` from Task 5.
- Produces: `make promote`.

- [ ] **Step 1: Add the Makefile target**

In `Makefile`, change the `.PHONY` line to include `promote` and append:

```makefile
# Staging -> production promotion (#516): preflight, migrate prod, confirm,
# merge main->production, wait for the deploy, smoke. One prompt, at the merge.
# See backend/promotion/README.md.
promote:
	cd backend && venv/bin/dotenv -f .env.production run -- venv/bin/python -m promotion $(ARGS)
```

- [ ] **Step 2: Verify the target reaches the CLI**

Run: `make promote ARGS="--help"`
Expected: argparse usage listing `--allow-destructive`, `--skip-staging-check`, `--yes`.

- [ ] **Step 3: Write the runbook**

Create `backend/promotion/README.md`:

````markdown
# Promotion runbook

`make promote` — staging (`main`) to production. Replaces the hand-run sequence
that shipped #515.

## Before you run it

- Production's `SUPABASE_DB_URL` in `backend/.env.production` must be the
  SESSION-mode pooler URI. Build it:
  `python scripts/pooler_url.py .env.production aws-0-us-west-2 --raw`
- `STAGING_SUPABASE_DB_URL` should be set (staging is `aws-1-us-west-2`) so the
  runner can refuse DDL that staging has never executed. Without it that guard
  is inert.
- `gh` must be authenticated.

## What it does

1. **Preflight** (read-only): target-identity, ledger exists, no orphans,
   staging-ran-it-first, no destructive DDL, something to promote.
2. **Snapshot** production.
3. **Migrate** production (`db.migrate`).
4. **Snapshot** again and print the diff.
5. **Pause** — the only prompt, at the only irreversible step.
6. **Merge** `main` → `production`, retrying through the known `gh` 502.
7. **Wait** until `/api/health` reports the promoted commit (10 min timeout).
8. **Smoke** the live surface.

Exit codes: `0` success or nothing to promote, `1` failure, `2` you declined.

## The ordering you need to know about

Migrations apply **before** the code merges. Between stages 3 and 6 the OLD
production code runs against the NEW schema. Additive DDL is fine there;
destructive DDL is not, which is why preflight blocks on it and
`--allow-destructive` is an explicit decision.

**If you answer `n` at the prompt, the migrations are already applied.**
Production's schema will be ahead of its code. Re-running resumes at the merge.

## When smoke fails

Nothing is reverted, deliberately: the migrations cannot be rolled back, so
reverting the code would leave old code against a newer schema. The runner
prints the revert command; reverting is your call.

## Re-running

Safe. Preflight finds nothing pending and the PR already `MERGED`, so a second
run resumes at wait + smoke.
````

- [ ] **Step 4: Document the command in CLAUDE.md**

In `CLAUDE.md`, under the Database section of "Commands", append after the `db.seed_staging` block:

```
Promotion (repo root; full runbook `backend/promotion/README.md`):

```
make promote                      # staging -> prod: preflight, migrate, confirm, merge, verify
make promote ARGS="--yes"         # skip the confirmation prompt (CI)
```
```

- [ ] **Step 5: Delete the superseded artifacts**

These are untracked working files from the #515 promotion, now replaced by the package. Confirm each is untracked before deleting, so nothing tracked is lost:

```bash
cd /home/andresl/Projects/sapling
git status --porcelain backend/prod_snapshot.py backend/prod_db_check.py \
  backend/smoke_prod_app.sh backend/smoke_prod_promotion.sh backend/prod_snapshot_*.json
```

Expected: every line starts with `??` (untracked). Then:

```bash
rm -f backend/prod_snapshot.py backend/prod_db_check.py \
      backend/smoke_prod_app.sh backend/smoke_prod_promotion.sh \
      backend/prod_snapshot_*.json
```

`backend/apply_graph_edges_fix.py` and `backend/graph_edges_fix.sql` must survive this step untouched.

- [ ] **Step 6: Confirm the suite and lint are still green**

Run: `cd backend && venv/bin/python -m pytest tests/ -q && venv/bin/ruff check .`
Expected: green.

- [ ] **Step 7: Commit**

```bash
git add Makefile backend/promotion/README.md CLAUDE.md
git commit -m "feat(promotion): make promote target, runbook, and #515 artifact cleanup (#516)"
```

---

### Task 7: Rehearse against production read-only, then open the PR

The runner has never touched a real database. Prove the read-only half works before anyone trusts the write half.

**Files:** none modified.

**Interfaces:** consumes everything above.

> **Steps 1 and 2 are run by the controller session, NOT a subagent.** Ruled during pre-flight: production credentials and the live connection stay under direct supervision. A subagent executing this task performs Steps 3 and 4 only, after the controller reports the rehearsal results.

- [ ] **Step 1: Verify preflight against live production without mutating it** *(controller)*

Production is currently level with `main` (#515 merged today), so preflight should report `nothing-to-promote` and stop — which exercises the connection, the ledger read and the guards without applying anything.

Run:

```bash
cd backend && venv/bin/dotenv -f .env.production run -- venv/bin/python -m promotion
```

Expected: connects, reports `[nothing-to-promote] origin/main and origin/production are identical.`, exits 0. **It must not reach the confirmation prompt.**

If it reports `target-mismatch`, the `.env.production` `SUPABASE_DB_URL` is the direct IPv6-only host or points at the wrong project — fix it with `scripts/pooler_url.py` before continuing.

- [ ] **Step 2: Verify the smoke checks pass against live production** *(controller)*

Run:

```bash
cd backend && venv/bin/python -c "
from promotion.smoke import CHECKS, httpx_fetch, run_checks, format_results, DEFAULT_API, DEFAULT_WEB
results = run_checks(httpx_fetch, DEFAULT_API, DEFAULT_WEB)
print(format_results(results))
raise SystemExit(0 if all(r.ok for r in results) else 1)
"
```

Expected: every check PASSes against the current production deploy. A failure here is a real finding about production, not a bug in the checks — investigate before proceeding.

Note: `api health` will report `commit` as `unknown` until the Task 1 change is deployed. That is expected and does not fail this check.

- [ ] **Step 3: Push the branch and open the PR**

```bash
git push -u origin feat/516-promotion-runner
gh pr create --title "feat(promotion): one-command staging→prod promotion runner (#516)" \
  --body "Closes #516.

Replaces the hand-run promotion sequence from #515 with \`make promote\`.

- \`backend/promotion/\` — preflight guards, snapshot/diff, durable smoke checks, stage runner
- \`/api/health\` now reports the build commit so the deploy wait is deterministic
- deletes the untracked #515 working artifacts the package supersedes

All new tests are hermetic (injected IO — no network, no DB, no prod credentials).
Rehearsed read-only against live production: preflight correctly reports
nothing-to-promote, and the smoke checks pass against the current deploy.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

- [ ] **Step 4: Run `/code-review` on the PR before merging**

Per the repo's gate, code review runs on the PR before it merges — not as a wrap-up afterwards.

---

## Self-Review

**Spec coverage** — every acceptance item in #516 maps to a task:

| #516 acceptance item | Task |
|---|---|
| `backend/promotion/` package, four units | 2, 3, 4, 5 |
| `make promote` + `python -m promotion` | 5 (CLI), 6 (Makefile) |
| Six preflight guards, each hermetically tested | 2 |
| `/api/health` build commit + tested `unknown` fallback | 1 |
| Committed smoke checks, promotion-specific assertions removed | 4 (incl. an explicit test that `fall-2026` is absent) |
| Single prompt; declining prints "schema ahead of code" | 5 |
| Smoke failure reports, exits non-zero, touches nothing | 5 |
| Untracked `prod_*`/`smoke_prod_*` artifacts absorbed or deleted | 6 |
| Runbook replacing tribal knowledge | 6 |

**Type consistency** — `Finding(kind, detail)` is constructed identically in `preflight` and asserted in both preflight and runner tests. `fetch(method, url) -> (status | None, body)` has the same signature in `smoke.run_checks`, `smoke.live_commit`, `smoke.httpx_fetch` and the runner's `Ports.fetch`. `capture(conn) -> dict` returns the `tables`/`ledger` keys that `diff` reads. `db_migrate.run(conn)` matches the real signature at `backend/db/migrate.py:132`.

**Known follow-up, deliberately out of scope:** the `workflow_dispatch` wrapper. `runner.run(ports, options)` takes every side effect as a port, so the wrapper supplies a non-interactive `confirm` and CI secrets without touching the runner.
