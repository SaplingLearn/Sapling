"""PKG-14b (owner decision 2026-09-29, spec §13 A89): `llm_usage.session_id`.

Every llm_usage row carries the loop session its run belonged to when the run
site knows it; scripts/derive_zpd_metrics.py prefers the row's own session over
the A82 event join (which misses the opener, the probe and review grades and
the hint actions), keeping per user-day only for rows that carry neither.

The column is additive and nullable. A deploy that reaches a database before the
migration must not lose usage rows (every $/token budget cap reads them), so the
events writer drops exactly this optional column when PostgREST names it as
unknown and retries — the graph_service journal idiom.
"""

from __future__ import annotations

import ast
import importlib
import re
import sys
from pathlib import Path

import pytest

from agents.usage import record_agent_usage
from services import events_service

BACKEND = Path(__file__).resolve().parents[1]
MIG_DIR = BACKEND / "db" / "migrations"
SCRIPTS = BACKEND / "scripts"


# ── migration ────────────────────────────────────────────────────────────────


def _migration() -> Path:
    hits = sorted(MIG_DIR.glob("*_learning_llm_usage_session_id.sql"))
    assert len(hits) == 1, hits
    return hits[0]


def test_migration_is_timestamped_after_half_a():
    """Append-only (CLAUDE.md): a UTC timestamp prefix later than the last
    migration of half B's base (half A's posttest_poses)."""
    path = _migration()
    assert re.fullmatch(r"\d{14}_learning_llm_usage_session_id\.sql", path.name), path.name
    (base,) = sorted(MIG_DIR.glob("*_learning_posttest_poses.sql"))
    assert path.name > base.name


def test_migration_is_additive_nullable_and_idempotent():
    sql = _migration().read_text()
    body = "\n".join(ln for ln in sql.splitlines() if not ln.lstrip().startswith("--"))
    assert re.search(r"ALTER TABLE llm_usage\s+ADD COLUMN IF NOT EXISTS session_id text\s*;", body)
    assert "NOT NULL" not in body.upper() and "DEFAULT" not in body.upper()
    for forbidden in ("DROP ", "RENAME", "ALTER COLUMN", "UPDATE ", "DELETE "):
        assert forbidden not in body.upper(), forbidden
    # llm_usage's RLS/grants are table-level (0035) and unchanged; the column is
    # served through PostgREST's cache, so the migration reloads it.
    assert "NOTIFY pgrst, 'reload schema';" in body


# ── the writer ───────────────────────────────────────────────────────────────


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
            model_name = "gemini-2.5-flash"

        return _R()


@pytest.fixture
def sink(monkeypatch):
    rows: list = []

    class _T:
        def __init__(self, name):
            self.name = name

        def insert(self, r):
            rows.append((self.name, r))
            return r

    monkeypatch.setattr(events_service, "table", lambda name: _T(name))
    return rows


def _usage_rows(sink):
    return [r for name, batch in sink if name == "llm_usage" for r in batch]


def test_record_agent_usage_writes_the_session_it_is_given(sink):
    record_agent_usage(
        _FakeResult(), feature="loop_tutor", task="loop_tutor", user_id="u", session_id="s1"
    )
    events_service.flush_now()
    (row,) = _usage_rows(sink)
    assert row["session_id"] == "s1"


def test_every_row_carries_the_key_even_without_a_session(sink):
    """PostgREST rejects a bulk insert whose objects' keys differ (PGRST102)."""
    record_agent_usage(
        _FakeResult(), feature="loop_tutor", task="loop_tutor", user_id="u", session_id="s1"
    )
    record_agent_usage(_FakeResult(), feature="check_items", task="check_items")
    events_service.flush_now()
    rows = _usage_rows(sink)
    assert [r["session_id"] for r in rows] == ["s1", None]
    assert len({frozenset(r) for r in rows}) == 1


def test_a_blank_session_is_stored_as_null(sink):
    record_agent_usage(
        _FakeResult(), feature="loop_tutor", task="loop_tutor", user_id="u", session_id="  "
    )
    events_service.flush_now()
    (row,) = _usage_rows(sink)
    assert row["session_id"] is None


class _ColumnMissing(Exception):
    pass


@pytest.mark.parametrize(
    "message",
    [
        "Could not find the 'session_id' column of 'llm_usage' in the schema cache",  # PGRST204
        'column "session_id" of relation "llm_usage" does not exist',  # 42703
    ],
)
def test_a_database_before_the_migration_loses_no_usage_row(monkeypatch, message):
    """Code ahead of the migration: the insert names an unknown column. The
    writer drops exactly session_id and retries, so the budget caps still see
    every row."""
    written: list = []
    calls: list = []

    class _T:
        def insert(self, r):
            calls.append([dict(x) for x in r])
            if any("session_id" in x for x in r):
                raise _ColumnMissing(message)
            written.extend(r)
            return r

    monkeypatch.setattr(events_service, "table", lambda name: _T())
    record_agent_usage(
        _FakeResult(), feature="loop_tutor", task="loop_tutor", user_id="u", session_id="s1"
    )
    record_agent_usage(_FakeResult(), feature="grader", task="grader", user_id="u")
    events_service.flush_now()
    assert len(written) == 2
    assert all("session_id" not in r for r in written)
    assert all(r["cost_usd"] is not None or r["model"] for r in written)
    assert len(calls) == 2, "one failed bulk insert, one bulk retry without the column"


def test_an_unrelated_insert_error_keeps_the_column(monkeypatch):
    """Only an error that NAMES the optional column drops it; anything else goes
    through the existing per-row salvage unchanged."""
    seen: list = []

    class _T:
        def insert(self, r):
            seen.append([dict(x) for x in r])
            raise RuntimeError("503 upstream timeout")

    monkeypatch.setattr(events_service, "table", lambda name: _T())
    record_agent_usage(
        _FakeResult(), feature="loop_tutor", task="loop_tutor", user_id="u", session_id="s1"
    )
    events_service.flush_now()
    assert seen and all("session_id" in r for batch in seen for r in batch)


# ── run sites that know a session pass it ───────────────────────────────────

#: (module, innermost enclosing function) → the expression(s) its
#: record_agent_usage calls pass as session_id=. A session is known at exactly
#: these sites. Not listed, on purpose: agents/check_items.py (course assets, no
#: session), agents/session_close.py (its request is already mapped by the
#: learn.session_closed event, A82, and its run seam carries no session id), and
#: the non-tutor features (documents, notes, quiz, study guide, …).
SESSION_SITES = {
    ("agents/grader.py", "_run_once"): {"deps.session_id"},
    ("services/decisions.py", "_run_decision"): {"deps.session_id"},
    ("routes/learn_loop.py", "record_usage"): {"self.session_id"},
    ("routes/learn_loop.py", "_loop_continuation_text"): {"turn.session_id"},
    ("routes/learn.py", "_continuation_text"): {"getattr(carried.get('deps'), 'session_id', None)"},
    ("routes/learn.py", "_start_session_agent"): {"session_id"},
    ("routes/learn.py", "_chat_via_agent"): {"session_id"},
    ("routes/learn.py", "_usage"): {
        "body.session_id",
        "session_id",
    },  # /chat/stream, the opener stream
    ("routes/learn.py", "_action_turn"): {"body.session_id"},
}


def _session_kwargs(rel: str) -> dict[str, list[str | None]]:
    """innermost enclosing function name → the session_id= of each call in it."""
    tree = ast.parse((BACKEND / rel).read_text())
    fns = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    found: dict[str, list[str | None]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "record_agent_usage":
            owner = max(
                (f for f in fns if f.lineno <= node.lineno <= f.end_lineno), key=lambda f: f.lineno
            )
            kw = {k.arg: ast.unparse(k.value) for k in node.keywords}
            found.setdefault(owner.name, []).append(kw.get("session_id"))
    return found


@pytest.mark.parametrize("site,expr", sorted(SESSION_SITES.items()), ids=lambda v: str(v))
def test_run_sites_that_know_the_session_pass_it(site, expr):
    rel, fn = site
    calls = _session_kwargs(rel).get(fn)
    assert calls, f"{rel}::{fn} has no record_agent_usage call (moved? re-point this pin)"
    assert set(calls) == expr, f"{rel}::{fn} passes session_id={calls}, expected {expr}"


# ── the report prefers the row's own session ────────────────────────────────


def _script():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    return importlib.import_module("derive_zpd_metrics")


def _usage(req, task, usd, *, session=None, day="20", user="u"):
    return {
        "id": f"{req}-{task}",
        "user_id": user,
        "request_id": req,
        "task": task,
        "cost_usd": usd,
        "created_at": f"2026-09-{day}T10:00:00+00:00",
        "session_id": session,
    }


def test_the_usage_read_selects_the_session_column():
    assert "session_id" in _script()._USAGE_COLS.split(",")


def test_report_prefers_the_rows_own_session_over_the_event_join():
    usage = [
        _usage("r1", "loop_tutor", "0.010", session="s-own"),  # own key wins over the join
        _usage(
            "r2", "grader", "0.002", session="s-own"
        ),  # the opener/probe class: no event maps it
        _usage("r3", "loop_tutor", "0.020"),  # older row: the A82 join still maps it
        _usage("r4", "loop_tutor", "0.040", day="21"),  # neither: per user-day
    ]
    out = _script().report(
        usage, [], [], sessions_by_request={("u", "r1"): "s-event", ("u", "r3"): "s-event"}
    )
    assert out["cost_per_session"] == {
        "s-event": pytest.approx(0.020),
        "s-own": pytest.approx(0.012),
    }
    assert out["cost_per_user_day"] == {"u/2026-09-21": pytest.approx(0.040)}


def test_report_ignores_a_blank_own_session():
    out = _script().report(
        [_usage("r1", "loop_tutor", "0.010", session="")], [], [], sessions_by_request={}
    )
    assert out["cost_per_session"] == {}
    assert out["cost_per_user_day"] == {"u/2026-09-20": pytest.approx(0.010)}
