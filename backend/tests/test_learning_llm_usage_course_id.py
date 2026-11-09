"""Spec §13 A137: `llm_usage.course_id`, so the cost-per-learning-gain report can
put a loop run with no session (check-item drafting and its checks, a post-test
grade and its decisions) on its course. Additive and nullable; a deploy that
reaches a database before the migration loses no usage row (the session_id
idiom, tests/test_learning_llm_usage_session_id.py)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from agents.usage import record_agent_usage
from services import events_service

BACKEND = Path(__file__).resolve().parents[1]
MIG_DIR = BACKEND / "db" / "migrations"


def _migration() -> Path:
    (path,) = sorted(MIG_DIR.glob("*_learning_llm_usage_course_id.sql"))
    return path


def test_the_migration_is_additive_nullable_and_after_the_session_column():
    path = _migration()
    (session,) = sorted(MIG_DIR.glob("*_learning_llm_usage_session_id.sql"))
    assert re.fullmatch(r"\d{14}_learning_llm_usage_course_id\.sql", path.name)
    assert path.name > session.name
    body = "\n".join(ln for ln in path.read_text().splitlines() if not ln.lstrip().startswith("--"))
    assert "ALTER TABLE llm_usage ADD COLUMN IF NOT EXISTS course_id text;" in body
    assert "NOT NULL" not in body.upper() and "DEFAULT" not in body.upper()
    for forbidden in ("DROP ", "RENAME", "ALTER COLUMN", "UPDATE ", "DELETE "):
        assert forbidden not in body.upper(), forbidden
    assert "NOTIFY pgrst, 'reload schema';" in body


class _FakeUsage:
    input_tokens = 10
    output_tokens = 5
    total_tokens = 15


class _FakeResult:
    output = "x"

    def usage(self):
        return _FakeUsage()

    @property
    def response(self):
        class _R:
            model_name = "gemini-2.5-flash-lite"

        return _R()


@pytest.fixture
def sink(monkeypatch):
    rows: list = []

    class _T:
        def insert(self, r):
            rows.extend(r)
            return r

    monkeypatch.setattr(events_service, "table", lambda name: _T())
    return rows


def test_the_row_records_the_course_and_every_row_carries_the_key(sink):
    record_agent_usage(_FakeResult(), feature="check_items", task="check_items", course_id="c1")
    record_agent_usage(_FakeResult(), feature="loop_tutor", task="loop_tutor", session_id="s1")
    record_agent_usage(_FakeResult(), feature="check_items", task="check_items", course_id="  ")
    events_service.flush_now()
    assert [r["course_id"] for r in sink] == ["c1", None, None]
    assert len({frozenset(r) for r in sink}) == 1  # PGRST102: one key set per bulk insert


def test_a_checklist_receipt_keeps_the_keys_its_reconcile_admits():
    """A checklist receipt IS build_llm_usage_row's row (services/usage_receipts.py),
    and checklist_budget_reconcile refuses a receipt with any other key: the
    course goes onto the enqueued row only, never into the receipt."""
    sql = sorted(MIG_DIR.glob("*_checklist_budget*.sql"))[-1].read_text()
    admitted = set(re.findall(r"'(\w+)'", re.search(r"p_receipt - ARRAY\[(.*?)\]", sql, re.S).group(1)))
    row = events_service.build_llm_usage_row(
        feature="topic_checklist", task="topic_checklist", model="gemini-2.5-flash", usage=_FakeUsage()
    )
    assert "course_id" not in row
    assert set(row) | {"id", "created_at"} <= admitted


class _ColumnMissing(Exception):
    pass


def _missing(column: str) -> str:
    return f"Could not find the '{column}' column of 'llm_usage' in the schema cache"  # PGRST204


def test_a_database_before_the_migration_loses_no_usage_row(monkeypatch):
    written, calls = [], []

    class _T:
        def insert(self, r):
            calls.append([dict(x) for x in r])
            if any("course_id" in x for x in r):
                raise _ColumnMissing(_missing("course_id"))
            written.extend(r)
            return r

    monkeypatch.setattr(events_service, "table", lambda name: _T())
    record_agent_usage(_FakeResult(), feature="check_items", task="check_items", course_id="c1")
    record_agent_usage(_FakeResult(), feature="grader", task="grader", user_id="u", session_id="s1")
    events_service.flush_now()
    assert len(written) == 2 and all("course_id" not in r for r in written)
    assert all(r["session_id"] in ("s1", None) for r in written)  # the other column stays
    assert len(calls) == 2, "one failed bulk insert, one bulk retry without the column"


def test_a_database_before_both_columns_drops_each_in_turn(monkeypatch):
    """PostgREST names one unknown column per error: the writer drops each
    optional column it names, once, and never loses the rows."""
    written, calls = [], []

    class _T:
        def insert(self, r):
            calls.append([dict(x) for x in r])
            for column in ("session_id", "course_id"):
                if any(column in x for x in r):
                    raise _ColumnMissing(_missing(column))
            written.extend(r)
            return r

    monkeypatch.setattr(events_service, "table", lambda name: _T())
    record_agent_usage(_FakeResult(), feature="loop_tutor", task="loop_tutor", session_id="s1", course_id="c1")
    events_service.flush_now()
    assert len(written) == 1 and not {"session_id", "course_id"} & set(written[0])
    assert len(calls) == 3  # the first try, without session_id, without both


def test_an_unrelated_error_keeps_the_column_and_never_loops(monkeypatch):
    seen = []

    class _T:
        def insert(self, r):
            seen.append([dict(x) for x in r])
            raise RuntimeError("503 upstream timeout")

    monkeypatch.setattr(events_service, "table", lambda name: _T())
    record_agent_usage(_FakeResult(), feature="check_items", task="check_items", course_id="c1")
    events_service.flush_now()
    assert seen and all("course_id" in r for batch in seen for r in batch)
    assert len(seen) == 2  # the bulk insert, then the one-row salvage


#: (module, innermost enclosing function, the recording call) → the course_id=
#: expression. The loop's run sites that may have no session record the course
#: their deps carry; a session's row is attributed through its session.
COURSE_SITES = {
    ("agents/check_items.py", "_record_unfinished", "record_agent_usage"): {"deps.course_id"},
    ("agents/check_items.py", "run_drafting", "record_agent_usage"): {"deps.course_id"},
    ("agents/grader.py", "_run_once", "record_agent_usage"): {"deps.course_id"},
    ("services/learning_decisions.py", "_run_decision", "record_agent_usage"): {
        "getattr(deps, 'course_id', None)"
    },
    ("services/learning_decisions.py", "_record_jev_usage", "log_llm_usage"): {
        "getattr(deps, 'course_id', None)"
    },
}


def _course_kwargs(rel: str, call: str) -> dict[str, set[str | None]]:
    tree = ast.parse((BACKEND / rel).read_text())
    fns = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    found: dict[str, set[str | None]] = {}
    for node in ast.walk(tree):
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None) if isinstance(node, ast.Call) else None
        if name == call:
            owner = max((f for f in fns if f.lineno <= node.lineno <= f.end_lineno), key=lambda f: f.lineno)
            kw = {k.arg: ast.unparse(k.value) for k in node.keywords}
            found.setdefault(owner.name, set()).add(kw.get("course_id"))
    return found


@pytest.mark.parametrize("site,expr", sorted(COURSE_SITES.items()), ids=lambda v: str(v))
def test_the_session_less_loop_run_sites_record_their_course(site, expr):
    rel, fn, call = site
    calls = _course_kwargs(rel, call).get(fn)
    assert calls, f"{rel}::{fn} has no {call} call (moved? re-point this pin)"
    assert calls == expr, f"{rel}::{fn} passes course_id={calls}, expected {expr}"
