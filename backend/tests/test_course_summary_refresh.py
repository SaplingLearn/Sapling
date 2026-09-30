"""Class summary cost on the loop path (spec §13 A35; PKG-03 reopen).

The live sequence test of PR #673 (2026-09-27, real Gemini) found every
evidence flush regenerating `offering_summary.summary_text` on gemini-2.5-flash
for each of the student's offerings of the touched course: the summary's hash
keyed on raw per-concept scores, which move on every graded answer. 10 calls
cost $0.021969, 84% of a run whose grading cost $0.000573.

A35: the prose has no reader, so with the loop on `update_course_context`
writes the class numbers and no prose at all (NULL text and hash), and nothing
else writes it: no `course_summary` call on the answer path or off it. (The
first fix moved the prose to a lifespan refresher; the review of that fix
showed it still paid about one call per offering per active interval, per
instance, for text nothing reads.) With the loop off, the pre-series behaviour
is byte-identical (pinned below).

The graph and the class aggregation run for real here, on a small in-memory
PostgREST stand-in; only the model call is mocked.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import config
from learning import bkt
from learning.evidence import flush_pending
from services import course_context_service as ccs

USER = "u1"
COURSE = "c1"
OFFERINGS = ("off-a", "off-b")


# ── an in-memory PostgREST stand-in ──────────────────────────────────────────


def _matches(row: dict, filters: dict | None) -> bool:
    for col, spec in (filters or {}).items():
        op, _, val = spec.partition(".")
        cur = row.get(col)
        if op == "eq":
            ok = cur is not None and str(cur) == val
        elif op == "in":
            ok = str(cur) in val.strip("()").split(",")
        elif op == "is" and val == "null":
            ok = cur is None
        else:  # pragma: no cover - a filter this stand-in was never taught
            raise AssertionError(f"unsupported filter {col}={spec}")
        if not ok:
            return False
    return True


def _project(row: dict, columns: str) -> dict:
    if columns.strip() == "*":
        return dict(row)
    return {c: row.get(c) for c in (c.strip() for c in columns.split(","))}


class _Table:
    def __init__(self, db: _DB, name: str):
        self.db, self.name = db, name

    @property
    def rows(self) -> list[dict]:
        return self.db.rows.setdefault(self.name, [])

    def select(self, columns="*", filters=None, order=None, limit=None, offset=None):
        out = [_project(r, columns) for r in self.rows if _matches(r, filters)]
        if order:
            out.sort(key=lambda r: str(r.get(order.split(".")[0])))
        if offset:
            out = out[offset:]
        if limit:
            out = out[:limit]
        return out

    def select_with_count(self, columns="*", filters=None, order=None, limit=None, offset=None):
        total = sum(1 for r in self.rows if _matches(r, filters))
        return self.select(columns, filters, order, limit, offset), total

    def insert(self, data):
        batch = data if isinstance(data, list) else [data]
        self.rows.extend(dict(r) for r in batch)
        return [dict(r) for r in batch]

    def update(self, data, filters, *, prefer_return_minimal=False):
        hit = [r for r in self.rows if _matches(r, filters)]
        for r in hit:
            r.update(data)
        return [] if prefer_return_minimal else [dict(r) for r in hit]

    def upsert(self, data, on_conflict="id"):
        keys = on_conflict.split(",")
        out = []
        for new in data if isinstance(data, list) else [data]:
            old = next((r for r in self.rows if all(r.get(k) == new.get(k) for k in keys)), None)
            if old is None:
                old = dict(new)
                self.rows.append(old)
            else:
                old.update(new)  # merge-duplicates: columns not sent are kept
            out.append(dict(old))
        return out

    def delete(self, filters):
        keep = [r for r in self.rows if not _matches(r, filters)]
        gone = len(self.rows) - len(keep)
        self.db.rows[self.name] = keep
        return [{}] * gone


class _DB:
    def __init__(self, tables: dict[str, list[dict]]):
        self.rows = {name: [dict(r) for r in rows] for name, rows in tables.items()}

    def table(self, name: str) -> _Table:
        return _Table(self, name)

    def one(self, name: str, **eq) -> dict:
        (row,) = [r for r in self.rows.get(name, []) if all(r.get(k) == v for k, v in eq.items())]
        return row


def _node(node_id: str, name: str, score: float) -> dict:
    return {
        "id": node_id,
        "user_id": USER,
        "course_id": COURSE,
        "concept_name": name,
        "mastery_score": score,
        "mastery_tier": bkt.tier_for(score),
        "times_studied": 1,
    }


def _world_db(**overrides) -> _DB:
    """One student enrolled in TWO offerings of one course (the finding's shape).
    n1 is the node the flushes move; the others hold the class average in the
    loop's `learning` tier whatever n1 does."""
    tables = {
        "courses": [{"id": COURSE, "course_code": "CS101", "course_name": "Intro CS"}],
        "course_offerings": [{"id": off, "course_id": COURSE} for off in OFFERINGS],
        "enrollments": [{"user_id": USER, "offering_id": off} for off in OFFERINGS],
        "graph_nodes": [
            _node("n1", "Recursion", 0.2),
            _node("n2", "Variables", 0.97),
            _node("n3", "Loops", 0.6),
            _node("n4", "Pointers", 0.05),
        ],
    }
    tables.update(overrides)
    return _DB(tables)


def _agent(summary: str = "Class summary.") -> AsyncMock:
    return AsyncMock(return_value=SimpleNamespace(output=SimpleNamespace(summary=summary)))


@contextmanager
def _world(db: _DB, agent_run: AsyncMock):
    with (
        patch("services.graph_service.table", side_effect=db.table),
        patch("learning.learner_state.table", side_effect=db.table),
        patch("services.course_context_service.table", side_effect=db.table),
        patch("services.academics.table", side_effect=db.table),
        patch("services.graph_service.touch_streak_safe"),
        patch("services.achievement_service.check_achievements"),
        patch.object(ccs.course_summary_agent, "run", new=agent_run),
    ):
        yield


@pytest.fixture
def loop_on(monkeypatch):
    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)


@pytest.fixture
def loop_off(monkeypatch):
    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", False)


def _flush(db: _DB, *evidence: dict) -> float:
    deps = SimpleNamespace(user_id=USER, pending_evidence=list(evidence))
    flush_pending(deps, COURSE)
    assert deps.pending_evidence == []
    return db.one("graph_nodes", id="n1")["mastery_score"]


# Wrong answers keep n1 in the loop's `struggling` tier [0.10, 0.30) while
# moving p every time; the free_response correct lifts it into `learning`.
WITHIN_TIER = ("mc", "mc", "free_response", "mc_reasoned", "mc")


# ── the finding ──────────────────────────────────────────────────────────────


def test_with_the_loop_on_no_flush_calls_the_model_not_even_on_a_tier_change(loop_on):
    """The prose has no reader (A35), so with the loop on nothing pays for it:
    not on the answer path, and not off it. The numbers stay current."""
    db = _world_db()
    run = _agent()
    with _world(db, run):
        for off in OFFERINGS:
            ccs.update_course_context(off)
        p = db.one("graph_nodes", id="n1")["mastery_score"]
        avgs = set()
        for channel in WITHIN_TIER:
            p_new = _flush(db, {"node_id": "n1", "channel": channel, "correct": False})
            assert p_new != p and bkt.tier_for(p_new) == "struggling"
            p = p_new
            avgs.add(db.one("offering_summary", offering_id="off-a")["avg_class_mastery"])
        assert len(avgs) == len(WITHIN_TIER), "the numbers stay current on every flush"

        p = _flush(db, {"node_id": "n1", "channel": "free_response", "correct": True})
        assert bkt.tier_for(p) == "learning"
    run.assert_not_awaited()
    for off in OFFERINGS:
        row = db.one("offering_summary", offering_id=off)
        assert row["top_struggling_concepts"] == [], "the lists follow the tier change"
        assert row["summary_text"] is None and row["summary_hash"] is None


def test_the_loop_era_row_drops_prose_it_can_no_longer_keep_true(loop_on):
    """Prose written before the loop turned on would contradict the numbers the
    loop keeps moving, so the loop-era upsert clears it (and its hash)."""
    db = _world_db(
        offering_summary=[
            {"offering_id": "off-a", "summary_text": "old prose", "summary_hash": "old-hash"}
        ]
    )
    run = _agent()
    with _world(db, run):
        ccs.update_course_context("off-a")
    run.assert_not_awaited()
    row = db.one("offering_summary", offering_id="off-a")
    assert row["summary_text"] is None and row["summary_hash"] is None
    assert row["student_count"] == 1 and row["top_struggling_concepts"] == ["Recursion"]
    assert row["avg_class_mastery"] == pytest.approx((0.2 + 0.97 + 0.6 + 0.05) / 4, abs=1e-4)


def test_the_loop_era_writes_the_same_numbers_as_the_legacy_regime(monkeypatch):
    """The regimes differ in the prose alone."""
    numbers = (
        "offering_id",
        "student_count",
        "avg_class_mastery",
        "top_struggling_concepts",
        "top_mastered_concepts",
    )
    rows = {}
    for loop in (False, True):
        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", loop)
        db = _world_db()
        with _world(db, _agent()):
            ccs.update_course_context("off-a")
        row = db.one("offering_summary", offering_id="off-a")
        rows[loop] = {k: row[k] for k in numbers}
        assert set(row) == set(numbers) | {"summary_text", "summary_hash", "updated_at"}
    assert rows[True] == rows[False]


def test_the_kill_switch_writes_the_prose_again_once(monkeypatch):
    """Turning the loop off returns to the pre-series regime: the cleared hash
    differs from the stats hash, so the next refresh writes the prose once."""
    db = _world_db()
    run = _agent("legacy prose")
    with _world(db, run):
        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
        ccs.update_course_context("off-a")
        run.assert_not_awaited()
        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", False)
        ccs.update_course_context("off-a")
        ccs.update_course_context("off-a")
    assert run.await_count == 1
    assert db.one("offering_summary", offering_id="off-a")["summary_text"] == "legacy prose"


_AGENT = "course_summary_agent"
_SLOT = "course_summary"
_SLOT_READERS = frozenset({"model_for", "model_name_for"})  # agents/_providers.py


def _course_summary_agent_sites(source: str) -> set[str]:
    """The scopes of one module (the innermost def's name, or "<module>") that
    reach the course_summary agent: its name, bare or under an import alias;
    the attribute on a module (`cs.course_summary_agent`); the name as a string
    (`getattr(m, "course_summary_agent")`); or a fresh agent on its model slot
    (`model_for("course_summary")`, `model_name_for(task="course_summary")`).
    An import alone is not a site."""
    tree = ast.parse(source)
    names = {_AGENT} | {
        alias.asname
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.name == _AGENT and alias.asname
    }

    def reaches(node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id in names
        if isinstance(node, ast.Attribute):
            return node.attr == _AGENT
        if isinstance(node, ast.Constant):
            return node.value == _AGENT
        if isinstance(node, ast.Call):
            func = node.func
            callee = getattr(func, "id", None) or getattr(func, "attr", None)
            args = [*node.args, *(kw.value for kw in node.keywords)]
            return callee in _SLOT_READERS and any(
                isinstance(a, ast.Constant) and a.value == _SLOT for a in args
            )
        return False

    sites: set[str] = set()

    def visit(node: ast.AST, scope: str) -> None:
        if reaches(node):
            sites.add(scope)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scope = node.name
        for child in ast.iter_child_nodes(node):
            visit(child, scope)

    visit(tree, "<module>")
    return sites


_IMPORT = "from agents.course_summary import course_summary_agent\n"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (_IMPORT + "def f():\n    return course_summary_agent.run('x')\n", {"f"}),
        (
            "from agents.course_summary import course_summary_agent as csa\n"
            "def f():\n    return csa.run('x')\n",
            {"f"},
        ),
        (
            "from agents import course_summary as cs\n"
            "def f():\n    return cs.course_summary_agent.run('x')\n",
            {"f"},
        ),
        (
            "import agents.course_summary\n"
            "async def f():\n    return await agents.course_summary.course_summary_agent.run('x')\n",
            {"f"},
        ),
        (
            "import importlib\n"
            "def f():\n"
            "    m = importlib.import_module('agents.course_summary')\n"
            "    return getattr(m, 'course_summary_agent').run('x')\n",
            {"f"},
        ),
        (
            "from pydantic_ai import Agent\nfrom agents._providers import model_for\n"
            "def f():\n    return Agent(model=model_for('course_summary')).run('x')\n",
            {"f"},
        ),
        (
            "from agents import _providers as p\n"
            "def f():\n    return google_model(p.model_name_for(task='course_summary'))\n",
            {"f"},
        ),
        (_IMPORT + "RUN = course_summary_agent.run\n", {"<module>"}),
        (
            _IMPORT + "def outer():\n    def inner():\n        return course_summary_agent\n"
            "    return inner\n",
            {"inner"},
        ),
        # Not a site: the import alone, another slot, the slot's handler
        # registration, the usage labels, and prose that names the agent.
        (_IMPORT, set()),
        ("def f():\n    return model_for('summary')\n", set()),
        ("register_function_handler('course_summary', handler)\n", set()),
        ("def f(r):\n    return record_agent_usage(r, feature='course_summary')\n", set()),
        ('def f():\n    """Runs the course_summary_agent."""\n', set()),
    ],
    ids=[
        "bare-name",
        "import-alias",
        "module-alias-attribute",
        "dotted-module-attribute",
        "getattr-string",
        "fresh-agent-on-the-slot",
        "model-name-for-keyword",
        "module-level",
        "innermost-def",
        "import-only",
        "other-slot",
        "handler-registration",
        "usage-label",
        "docstring",
    ],
)
def test_course_summary_agent_site_detector(source, expected):
    """The guard below is only as good as this detector: every way a module can
    reach the agent (or build a fresh one on its model slot) is a site."""
    assert _course_summary_agent_sites(source) == expected


def test_only_the_legacy_regime_runs_the_course_summary_agent():
    """A35: the one call site of the agent is `_generate_summary_with_gemini`,
    which `update_course_context` reaches only with the loop off. A new writer
    of the prose (a refresher, a lazy read) needs a reader first, and a spec
    amendment that adds its cost to §3.5."""
    backend = Path(ccs.__file__).resolve().parents[1]
    sites = set()
    for path in backend.rglob("*.py"):
        rel = path.relative_to(backend).as_posix()
        if rel.startswith(("tests/", "venv/")) or rel == "agents/course_summary.py":
            continue
        source = path.read_text(encoding="utf-8")
        sites |= {(rel, scope) for scope in _course_summary_agent_sites(source)}
    assert sites == {("services/course_context_service.py", "_generate_summary_with_gemini")}


# ── the course-context failure is logged, never swallowed ────────────────────


@pytest.mark.parametrize(
    "payload",
    [
        # PKG-14b: the `updated_nodes` ("legacy") payload is gone (spec §11.2).
        {"evidence": [{"node_id": "n1", "channel": "mc", "correct": True}]},
    ],
    ids=["evidence"],
)
def test_a_failed_course_context_refresh_is_logged_not_raised(payload, caplog):
    from services.graph_service import apply_graph_update

    db = _world_db()
    with (
        _world(db, _agent()),
        patch(
            "services.course_context_service.update_course_context",
            side_effect=RuntimeError("DB down"),
        ),
        caplog.at_level(logging.WARNING, logger="services.graph_service"),
    ):
        apply_graph_update(USER, payload, COURSE)
    hits = [r for r in caplog.records if "course-context refresh failed" in r.getMessage()]
    assert [r.levelno for r in hits] == [logging.WARNING] * len(OFFERINGS)
    assert all(r.exc_info for r in hits)
    assert {r.getMessage().split("offering=")[1].split()[0] for r in hits} == set(OFFERINGS)


@pytest.mark.parametrize(
    ("call", "expected", "offerings"),
    [
        ("add_course", {"course_id": COURSE, "already_existed": False}, ("off-a",)),
        ("delete_node", {"deleted": True}, OFFERINGS),
        ("delete_course", {"deleted": True}, OFFERINGS),
    ],
)
def test_every_other_failed_course_context_refresh_is_logged_not_raised(
    call, expected, offerings, caplog
):
    """The other three callers in graph_service follow the same rule as
    apply_graph_update: the write they follow stands, and the failure shows."""
    from services import graph_service

    db = _world_db(enrollments=[]) if call == "add_course" else _world_db()
    args = {
        "add_course": (USER, COURSE),
        "delete_node": (USER, "n1"),
        "delete_course": (USER, COURSE),
    }[call]
    with (
        _world(db, _agent()),
        patch("services.academics.resolve_offering", return_value="off-a"),
        patch(
            "services.course_context_service.update_course_context",
            side_effect=RuntimeError("DB down"),
        ),
        caplog.at_level(logging.WARNING, logger="services.graph_service"),
    ):
        assert getattr(graph_service, call)(*args) == expected
    hits = [r for r in caplog.records if "course-context refresh failed" in r.getMessage()]
    assert [r.levelno for r in hits] == [logging.WARNING] * len(offerings)
    assert all(r.exc_info for r in hits)
    assert sorted(r.getMessage().split("offering=")[1].split()[0] for r in hits) == sorted(offerings)


# ── legacy: byte-identical with the loop off ─────────────────────────────────


def test_legacy_regenerates_on_every_score_change_with_the_precise_average(loop_off):
    """The pre-series behaviour, pinned as it was before A35: the hash keys on
    the raw per-concept stats, so every score change regenerates, synchronously,
    with the average to 0.1%."""
    db = _world_db()
    run = _agent("legacy prose")
    with _world(db, run):
        ccs.update_course_context("off-a")
        assert run.await_count == 1
        ccs.update_course_context("off-a")
        assert run.await_count == 1, "unchanged stats: no call"
        db.one("graph_nodes", id="n1")["mastery_score"] = 0.22  # same tier
        ccs.update_course_context("off-a")
        assert run.await_count == 2
    (message,) = run.await_args.args
    assert "Average class mastery: 46.0%" in message
    row = db.one("offering_summary", offering_id="off-a")
    expected_hash = ccs._generate_data_hash(
        [
            {
                "concept": name,
                "avg_mastery": score,
                "pct_struggling": 1.0 if tier == "struggling" else 0.0,
                "pct_mastered": 1.0 if tier == "mastered" else 0.0,
            }
            for name, score, tier in (
                ("Recursion", 0.22, "struggling"),
                ("Variables", 0.97, "mastered"),
                ("Loops", 0.6, "learning"),
                ("Pointers", 0.05, "unexplored"),
            )
        ]
    )
    assert row["summary_hash"] == expected_hash
    assert row["summary_text"] == "legacy prose"
    assert set(row) == {
        "offering_id",
        "student_count",
        "avg_class_mastery",
        "top_struggling_concepts",
        "top_mastered_concepts",
        "summary_text",
        "summary_hash",
        "updated_at",
    }


def test_legacy_graph_update_calls_the_refresh_with_the_offering_only(loop_off):
    from services.graph_service import apply_graph_update

    db = _world_db()
    with (
        _world(db, _agent()),
        patch("services.course_context_service.update_course_context") as refresh,
    ):
        # PKG-14b: graded evidence is the one mastery-moving payload left;
        # "legacy" names the class-summary regime (loop off), not the payload.
        apply_graph_update(
            USER, {"evidence": [{"node_id": "n1", "channel": "mc", "correct": True}]}, COURSE
        )
    assert [c.args for c in refresh.call_args_list] == [(off,) for off in OFFERINGS]
    assert all(c.kwargs == {} for c in refresh.call_args_list)
