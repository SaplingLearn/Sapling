"""Class summary cost on the loop path (spec §13 A35; PKG-03 reopen).

The live sequence test of PR #673 (2026-09-27, real Gemini) found every
evidence flush regenerating `offering_summary.summary_text` on gemini-2.5-flash
for each of the student's offerings of the touched course: the summary's hash
keyed on raw per-concept scores, which move on every graded answer. 10 calls
cost $0.021969, 84% of a run whose grading cost $0.000573.

A35: with the loop on, `update_course_context` refreshes the numbers only, and
the prose is written off every request path by `refresh_stale_summaries` (the
lifespan refresher), once per offering, and only when what the prose states
changes: the student count, the class average's tier, and the tier-derived
struggling/mastered lists. With the loop off, the pre-series behaviour is
byte-identical (pinned below).

The graph, the class aggregation and the refresher all run for real here, on a
small in-memory PostgREST stand-in; only the model call is mocked.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import config
from learning import bkt
from learning.evidence import flush_pending
from services import course_context_service as ccs
from services import course_summary_refresher as refresher

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


def test_flushes_that_move_p_but_no_tier_regenerate_nothing_and_a_tier_change_once_per_offering(
    loop_on,
):
    db = _world_db()
    run = _agent()
    with _world(db, run):
        for off in OFFERINGS:
            ccs.update_course_context(off)
        assert run.await_count == 0, "the aggregate refresh never calls the model"
        assert ccs.refresh_stale_summaries() == 2, "first prose: one per offering"
        assert run.await_count == 2

        p = db.one("graph_nodes", id="n1")["mastery_score"]
        avgs = set()
        for channel in WITHIN_TIER:
            p_new = _flush(db, {"node_id": "n1", "channel": channel, "correct": False})
            assert p_new != p and bkt.tier_for(p_new) == "struggling"
            p = p_new
            assert run.await_count == 2, "no model call on the answer path"
            assert ccs.refresh_stale_summaries() == 0
            avgs.add(db.one("offering_summary", offering_id="off-a")["avg_class_mastery"])
        assert len(avgs) == len(WITHIN_TIER), "the numbers stay current on every flush"
        assert run.await_count == 2

        p = _flush(db, {"node_id": "n1", "channel": "free_response", "correct": True})
        assert bkt.tier_for(p) == "learning"
        assert run.await_count == 2, "a tier change still calls nothing on the answer path"
        assert ccs.refresh_stale_summaries() == 2, "exactly one per offering"
        assert run.await_count == 4
        assert ccs.refresh_stale_summaries() == 0
    for off in OFFERINGS:
        row = db.one("offering_summary", offering_id=off)
        assert row["top_struggling_concepts"] == []
        assert row["summary_text"] == "Class summary."
        assert row["summary_hash"] == ccs.summary_key(
            row["student_count"],
            row["avg_class_mastery"],
            row["top_struggling_concepts"],
            row["top_mastered_concepts"],
        )


def test_loop_era_refresh_writes_numbers_only_and_keeps_existing_prose(loop_on):
    db = _world_db(
        offering_summary=[
            {"offering_id": "off-a", "summary_text": "old prose", "summary_hash": "old-key"}
        ]
    )
    run = _agent()
    with _world(db, run):
        for off in OFFERINGS:
            ccs.update_course_context(off)
    run.assert_not_awaited()
    kept = db.one("offering_summary", offering_id="off-a")
    assert (kept["summary_text"], kept["summary_hash"]) == ("old prose", "old-key")
    assert kept["student_count"] == 1 and kept["top_struggling_concepts"] == ["Recursion"]
    fresh = db.one("offering_summary", offering_id="off-b")
    assert "summary_text" not in fresh and "summary_hash" not in fresh
    assert fresh["avg_class_mastery"] == pytest.approx((0.2 + 0.97 + 0.6 + 0.05) / 4, abs=1e-4)


def test_the_prompt_states_the_average_as_its_tier_not_the_raw_score(loop_on):
    db = _world_db()
    run = _agent()
    with _world(db, run):
        ccs.update_course_context("off-a")
        assert ccs.refresh_stale_summaries() == 1
    (message,) = run.await_args.args
    assert "Average class mastery: learning (30%–95%)" in message
    assert "45.5%" not in message
    assert "- Recursion" in message and "- Variables" in message
    assert "CS101 - Intro CS" in message


# ── what the key covers ──────────────────────────────────────────────────────


def test_summary_key_ignores_score_moves_inside_a_tier():
    base = ccs.summary_key(3, 0.40, ["Recursion"], ["Variables"])
    assert ccs.summary_key(3, 0.60, ["Recursion"], ["Variables"]) == base
    assert ccs.summary_key(3, 0.94, ["Recursion"], ["Variables"]) == base


@pytest.mark.parametrize(
    "changed",
    [
        (4, 0.40, ["Recursion"], ["Variables"]),  # student count
        (3, 0.96, ["Recursion"], ["Variables"]),  # the average's tier
        (3, 0.40, [], ["Variables"]),  # the struggling list
        (3, 0.40, ["Recursion"], ["Variables", "Loops"]),  # the mastered list
        (3, 0.40, ["Recursion"], ["Loops", "Variables"]),  # its order
    ],
)
def test_summary_key_changes_with_what_the_prose_states(changed):
    assert ccs.summary_key(*changed) != ccs.summary_key(3, 0.40, ["Recursion"], ["Variables"])


def test_average_tier_label_matches_bkt_tier_for_at_every_cut():
    from learning.params import BAND_NOVICE_MAX, BKT_PROFICIENT, TIER_UNEXPLORED_MAX

    for p in (0.0, TIER_UNEXPLORED_MAX, BAND_NOVICE_MAX, BKT_PROFICIENT, 1.0):
        label = ccs._avg_tier_label(p)
        assert label.startswith(bkt.tier_for(p) + " ("), (p, label)
    for p, lo, hi in ((0.29, 10, 30), (0.3, 30, 95), (0.999, 95, 100), (0.05, 0, 10)):
        assert ccs._avg_tier_label(p).endswith(f"({lo}%–{hi}%)")


def test_loop_era_lists_rank_ties_by_name_not_row_order(loop_on):
    """Postgres returns rows in heap order, and an UPDATE moves a row, so a tie
    listed in row order would change the key on a flush that changed nothing
    the prose says."""
    tied = [_node("a", "Beta", 0.2), _node("b", "Alpha", 0.2), _node("c", "Gamma", 0.97)]
    lists = []
    for rows in (tied, list(reversed(tied))):
        db = _world_db(graph_nodes=rows)
        with _world(db, _agent()):
            ccs.update_course_context("off-a")
        lists.append(db.one("offering_summary", offering_id="off-a")["top_struggling_concepts"])
    assert lists == [["Alpha", "Beta"], ["Alpha", "Beta"]]


# ── the refresher's bounds ───────────────────────────────────────────────────


def _stale_rows(n: int) -> list[dict]:
    return [
        {
            "offering_id": f"off-{i}",
            "student_count": 1,
            "avg_class_mastery": 0.5,
            "top_struggling_concepts": [],
            "top_mastered_concepts": [],
            "summary_text": None,
            "summary_hash": None,
        }
        for i in range(n)
    ]


def test_one_pass_attempts_at_most_the_batch(loop_on, monkeypatch):
    monkeypatch.setattr(config, "COURSE_SUMMARY_REFRESH_BATCH", 2)
    db = _world_db(offering_summary=_stale_rows(3))
    run = _agent()
    with _world(db, run):
        assert ccs.refresh_stale_summaries() == 2
        assert ccs.refresh_stale_summaries() == 1
        assert ccs.refresh_stale_summaries() == 0
    assert run.await_count == 3


def test_a_failed_regeneration_is_logged_kept_and_retried_next_pass(loop_on, caplog):
    db = _world_db(offering_summary=_stale_rows(2))
    run = AsyncMock(
        side_effect=[
            RuntimeError("gemini 503"),
            SimpleNamespace(output=SimpleNamespace(summary="ok")),
            SimpleNamespace(output=SimpleNamespace(summary="ok")),
        ]
    )
    with (
        _world(db, run),
        caplog.at_level(logging.WARNING, logger="services.course_context_service"),
    ):
        assert ccs.refresh_stale_summaries() == 1
        failed = db.one("offering_summary", offering_id="off-0")
        assert failed["summary_text"] is None and failed["summary_hash"] is None
        (record,) = [r for r in caplog.records if "off-0" in r.getMessage()]
        assert record.levelno == logging.WARNING and record.exc_info
        assert ccs.refresh_stale_summaries() == 1
    assert db.one("offering_summary", offering_id="off-0")["summary_text"] == "ok"


def test_refresh_is_a_noop_with_the_loop_off(loop_off):
    db = MagicMock()
    with patch("services.course_context_service.table", db):
        assert ccs.refresh_stale_summaries() == 0
    db.assert_not_called()


def test_refresher_constants_are_named_in_config():
    assert isinstance(config.COURSE_SUMMARY_REFRESH_INTERVAL_S, int)
    assert config.COURSE_SUMMARY_REFRESH_INTERVAL_S > 0
    assert isinstance(config.COURSE_SUMMARY_REFRESH_BATCH, int)
    assert config.COURSE_SUMMARY_REFRESH_BATCH > 0


# ── the lifespan task ────────────────────────────────────────────────────────


def test_refresher_is_not_started_with_the_loop_off(loop_off):
    async def scenario():
        refresher.start_refresher()
        assert refresher._task is None
        await refresher.stop_refresher()

    asyncio.run(scenario())


def test_refresher_starts_and_stops_with_the_loop_on(loop_on, monkeypatch):
    monkeypatch.setattr(refresher, "refresh_stale_summaries", lambda: 0)

    async def scenario():
        refresher.start_refresher()
        task = refresher._task
        assert task is not None and not task.done()
        await refresher.stop_refresher()
        assert task.cancelled() or task.done()
        assert refresher._task is None

    asyncio.run(scenario())


def test_the_refresher_loop_survives_a_pass_that_raises(loop_on, monkeypatch):
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("transient")
        return 0

    monkeypatch.setattr(refresher, "refresh_stale_summaries", flaky)
    monkeypatch.setattr(config, "COURSE_SUMMARY_REFRESH_INTERVAL_S", 0)

    async def scenario():
        refresher.start_refresher()
        for _ in range(200):
            if len(calls) >= 2:
                break
            await asyncio.sleep(0.01)
        await refresher.stop_refresher()

    asyncio.run(scenario())
    assert len(calls) >= 2


def test_the_app_lifespan_starts_and_stops_the_refresher():
    from fastapi.testclient import TestClient

    with (
        patch("main.start_refresher") as start,
        patch("main.stop_refresher", new=AsyncMock()) as stop,
        patch("main.ensure_bucket_exists", new=AsyncMock()),
    ):
        from main import app

        with TestClient(app):
            start.assert_called_once()
            stop.assert_not_called()
        stop.assert_awaited_once()


# ── the course-context failure is logged, never swallowed ────────────────────


@pytest.mark.parametrize(
    "payload",
    [
        {"updated_nodes": [{"concept_name": "Recursion", "mastery_delta": 0.1}]},
        {"evidence": [{"node_id": "n1", "channel": "mc", "correct": True}]},
    ],
    ids=["legacy", "evidence"],
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
        apply_graph_update(
            USER, {"updated_nodes": [{"concept_name": "Recursion", "mastery_delta": 0.1}]}, COURSE
        )
    assert [c.args for c in refresh.call_args_list] == [(off,) for off in OFFERINGS]
    assert all(c.kwargs == {} for c in refresh.call_args_list)
