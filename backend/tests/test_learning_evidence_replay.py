"""Spec §13 A123: the journal replay equals the incremental writer.

The single writer (services/graph_service.py::_calculate_evidence) and the
replay (learning/evidence_replay.py::replay) share one state transition; these
tests drive the REAL writer through generated histories — several concepts on
a prerequisite graph, multi-row operations, idk, help rungs H1..H6, low grader
confidence, same-session re-checks (flagged and writer-forced), review
retention targets, propagation both ways, gaps from seconds to weeks — and then
replay the journal it wrote from scratch. Every learner_state row (all the
evidence columns, to the bit), every graph_nodes mirror and every journaled
p_before → p_after must come back exactly. Rows written before A123 (no
retention, recheck or propagation columns) replay exactly too wherever their
rule holds: the default retention, the weight-derived recheck flag, unchanged
prerequisite edges.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone

import pytest

from evidence_journal_fakes import Clock, LearningJournalDB, _same_state, install
from learning import evidence_replay
from learning.evidence_replay import ReplayError, observation, replay
from learning.params import BKT_L0

USER, COURSE = "u-replay", "c-replay"
NODES = ("n-a", "n-b", "n-c", "n-d", "n-e")
CHANNELS = ("free_response", "mc_reasoned", "mc", "teachback_llm", "chat_turn")


def _graph(db: LearningJournalDB) -> None:
    for node in NODES:
        db.add_node(USER, COURSE, node, name=f"Concept {node}")
    # a → b → c, a → d, d → e (prerequisite → dependent)
    for prereq, dependent in (("n-a", "n-b"), ("n-b", "n-c"), ("n-a", "n-d"), ("n-d", "n-e")):
        db.add_prereq(USER, prereq, dependent)


def _evidence(rng: random.Random, *, session: str | None, tagged: bool) -> dict:
    channel = rng.choice(CHANNELS)
    idk = rng.random() < 0.1
    qh = f"q{rng.randrange(14)}"
    ev = {
        "node_id": rng.choice(NODES),
        "channel": channel,
        "idk": idk,
        "correct": (not idk) and rng.random() < 0.62,
        "max_rung": rng.choice((0, 0, 0, 0, 1, 2, 3, 4, 6)),
        "confidence": rng.choice((None, None, 0.92, 0.41)),
        "session_id": session,
        "question_hash": qh,
        "check_item_id": f"ci-{qh}",
        "same_session_recheck": rng.random() < 0.12,
    }
    if tagged:
        ev["planning_provenance"] = {
            "check_item_id": ev["check_item_id"], "difficulty": rng.choice((1, 2, 3)),
            "synthetic_idk": False, "previously_seen": False,
        }
    return ev


def history(seed: int, *, ops: int = 26, retention: bool = True, tagged: bool = True) -> list:
    """[(gap seconds, retention, [evidence dicts])] — a reproducible history."""
    rng = random.Random(seed)
    out = []
    for _ in range(ops):
        session = rng.choice((None, "s-1", "s-2", "s-3"))
        tag = tagged and session is not None and rng.random() < 0.3
        evs = [_evidence(rng, session=session, tagged=tag) for _ in range(rng.choice((1, 1, 1, 2, 3)))]
        target = rng.choice((None, None, 0.85, 0.95)) if retention else None
        gap = rng.choice((0.5, 90.0, 3_600.0, 86_400.0, 3 * 86_400.0, 12 * 86_400.0, 40 * 86_400.0))
        out.append((gap, target, evs))
    return out


def run(monkeypatch, ops, *, skip=lambda ev: False):
    """Drive the REAL single writer through `ops` on a fresh store; `skip`
    leaves evidences out (the clock still runs through every operation)."""
    from services.graph_service import apply_graph_update

    db, clock = LearningJournalDB(), Clock()
    _graph(db)
    install(monkeypatch, db, clock)
    for gap, retention, evs in ops:
        clock.advance(seconds=gap)
        kept = [dict(ev) for ev in evs if not skip(ev)]
        if kept:
            apply_graph_update(USER, {"evidence": kept}, COURSE, retention=retention)
    return db, clock


def _journal(db: LearningJournalDB) -> list[dict]:
    return db._learning_evidence_void_snapshot(
        {"p_user_id": USER, "p_course_id": COURSE, "p_question_hash": "-"}
    )["journal"]


def _replay(db: LearningJournalDB, journal: list[dict]):
    return replay(
        [observation(r) for r in journal], user_id=USER,
        edges=db._course_edges(USER, COURSE), owned=set(NODES),
    )


def _assert_replay_matches(db: LearningJournalDB, rep) -> None:
    stored = {n: db.state(USER, n) for n in NODES if db.state(USER, n) is not None}
    assert set(rep.state_rows) == set(stored)
    for node, row in stored.items():
        mine = rep.state_rows[node]
        for key in ("p_known", "fsrs_d", "fsrs_s"):
            assert mine[key] == row[key], (node, key)  # to the bit: one transition, two drivers
        assert _same_state(mine, row), (node, mine, row)
        assert rep.mirrors[node] == db.nodes[node]["mastery_score"], node
    for row in db.journal:
        assert rep.trace[row["id"]] == (row["p_before"], row["p_after"]), row["id"]


@pytest.mark.parametrize("seed", range(40))
def test_replaying_the_journal_reproduces_the_incremental_writer_exactly(monkeypatch, seed):
    db, _ = run(monkeypatch, history(seed))
    journal = _journal(db)
    assert journal and all(r["retention"] is not None and r["propagated_to"] is not None for r in journal)
    _assert_replay_matches(db, _replay(db, journal))


@pytest.mark.parametrize("seed", range(40, 70))
def test_rows_from_before_a123_replay_exactly_by_their_rule(monkeypatch, seed):
    """No retention, recheck or propagation columns (the pre-A123 journal):
    the default target (every writer but the review used it — no review
    target in this history), the recheck flag from the planning envelope or
    the weight, propagation along the (unchanged) prerequisite edges."""
    db, _ = run(monkeypatch, history(seed, retention=False))
    legacy = [
        {**r, "retention": None, "same_session_recheck": None, "propagated_to": None}
        for r in _journal(db)
    ]
    _assert_replay_matches(db, _replay(db, legacy))


def test_the_writer_journals_every_replay_input(monkeypatch):
    """A123: the review's retention target, the final recheck flag (forced by
    the writer on a repeat in the session) and the propagation targets."""
    ops = [
        (60.0, 0.95, [{"node_id": "n-c", "channel": "free_response", "correct": True,
                       "session_id": "s", "question_hash": "q1", "check_item_id": "ci-1"}]),
        (60.0, None, [{"node_id": "n-c", "channel": "free_response", "correct": True,
                       "session_id": "s", "question_hash": "q1", "check_item_id": "ci-1"}]),
        (60.0, None, [{"node_id": "n-c", "channel": "free_response", "correct": False,
                       "session_id": "s", "question_hash": "q2", "check_item_id": "ci-2"}]),
        (60.0, None, [{"node_id": "n-c", "channel": "free_response", "correct": True,
                       "max_rung": 4, "session_id": "s", "question_hash": "q3", "check_item_id": "ci-3"}]),
    ]
    db, _ = run(monkeypatch, ops)
    rows = db.journal
    assert [r["retention"] for r in rows] == [0.95, 0.9, 0.9, 0.9]
    assert [r["same_session_recheck"] for r in rows] == [False, True, False, False]
    # correct → its prerequisite parent; incorrect → its dependents (none for n-c);
    # weight 0 (correct after H4) → nobody
    assert [r["propagated_to"] for r in rows] == [["n-b"], ["n-b"], [], []]


def test_a_journaled_propagation_is_followed_not_the_edges_of_today(monkeypatch):
    """A row that journaled its propagation replays it even when the edge it
    went along is gone since; a pre-A123 row follows the edges of today."""
    ops = [(60.0, None, [{"node_id": "n-b", "channel": "free_response", "correct": True}])]
    db, _ = run(monkeypatch, ops)
    journal = _journal(db)
    assert journal[0]["propagated_to"] == ["n-a"]
    db.edges = []  # the prerequisite edge was deleted afterwards
    rep = _replay(db, journal)
    assert rep.state_rows["n-a"]["p_known"] == db.state(USER, "n-a")["p_known"]
    legacy = _replay(db, [{**journal[0], "propagated_to": None}])
    assert "n-a" not in legacy.state_rows  # today's graph has no edge to follow


def test_a_row_the_replay_cannot_read_fails_closed():
    row = {
        "id": "e1", "node_id": "n", "created_at": "2026-09-01T09:00:00+00:00", "channel": "free_response",
        "correct": True, "assisted": False, "max_rung": 0, "weight": 1.0, "reason": "evidence:free_response",
        "confidence": None, "same_session_recheck": None, "planning_recheck": None, "retention": None,
        "propagated_to": None,
    }
    assert observation(row).recheck is False
    for broken in (
        {"channel": "idk"}, {"correct": None}, {"weight": 1.5}, {"weight": None},
        {"max_rung": 9}, {"created_at": "yesterday"}, {"retention": 0.0},
        {"propagated_to": "n-x"}, {"same_session_recheck": "yes"},
        # correct, unassisted, confident: no recheck flag gives a 0.7 weight
        {"weight": 0.7},
    ):
        with pytest.raises(ReplayError):
            observation({**row, **broken})


def test_the_weight_decides_a_legacy_recheck_flag_only_where_it_matters():
    base = {
        "id": "e1", "node_id": "n", "created_at": "2026-09-01T09:00:00+00:00", "channel": "mc",
        "assisted": False, "max_rung": 0, "reason": "evidence:mc", "retention": None,
        "propagated_to": None, "same_session_recheck": None, "planning_recheck": None,
    }
    assert observation({**base, "correct": True, "weight": 0.5, "confidence": None}).recheck is True
    assert observation({**base, "correct": True, "weight": 0.25, "confidence": 0.3}).recheck is True
    assert observation({**base, "correct": True, "weight": 0.5, "confidence": 0.3}).recheck is False
    # a wrong answer resets the streak whatever the flag: never needed, never guessed
    assert observation({**base, "correct": False, "weight": 0.5, "confidence": None}).recheck is False
    # the planning envelope's final flag wins
    assert observation({**base, "correct": True, "weight": 1.0, "planning_recheck": True}).recheck is True


def test_an_operation_is_one_time_and_its_states_stay_in_memory():
    t = "2026-09-01T09:00:00+00:00"
    obs = [observation({
        "id": f"e{i}", "node_id": "n", "created_at": t, "channel": "free_response", "correct": True,
        "assisted": False, "max_rung": 0, "weight": 1.0, "reason": "evidence:free_response",
        "retention": 0.9, "same_session_recheck": False, "propagated_to": [], "evidence_seq": i,
    }) for i in range(3)]
    assert [len(op) for op in evidence_replay.operations(obs)] == [3]
    rep = replay(obs, user_id="u", edges=[], owned={"n"})
    assert rep.trace["e1"][0] == rep.trace["e0"][1]  # no decay inside one operation
    assert rep.touched_at["n"] == datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)


def test_nothing_replayed_is_the_prior_read_state_answers():
    rep = replay([], user_id="u", edges=[], owned={"n"})
    assert rep.state_rows == {} and rep.mirrors == {}
    assert BKT_L0 == 0.35  # the prior a node with no row reads at (learner_state.read_state)
