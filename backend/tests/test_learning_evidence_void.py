"""Spec §13 A123: a staff retire VOIDS the item's evidence and recomputes the
state through the single graph writer — hermetic half (the SQL functions run
for real in tests/integration/test_learning_evidence_void_db.py).

- after `apply_graph_update(user, {"void_evidence": ...}, course)` every
  learner_state row and graph mirror equals what the REAL incremental writer
  stores for the same history with the item's evidence never written (same
  clock, same retention targets) — the from-scratch replay;
- the journal is untouched (append-only): the void is a row per evidence id;
- a re-run writes nothing (same plan, no version moves);
- a grade on a retired item is refused at commit and writes nothing;
- a void of an item staff have not retired is refused;
- a stale snapshot (evidence journaled between the read and the commit) is
  re-read and re-planned;
- a misconception whose every supporting attempt is void is closed.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from evidence_journal_fakes import _same_state
from learning import evidence_void
from learning.evidence import PlanningPersistenceUnavailable
from learning.evidence_transaction import EvidenceItemRetired, EvidenceVoidRefused
from learning.params import BKT_L0
from test_learning_evidence_replay import COURSE, NODES, USER, history, run

PRIOR = {
    "p_known": BKT_L0, "n_strong_unassisted": 0, "streak_unassisted": 0,
    "max_streak_unassisted": 0, "opps": 0, "fsrs_d": None, "fsrs_s": None,
    "fsrs_last_review_at": None, "fsrs_due_at": None, "last_evidence_at": None,
}


def _void(user=USER, course=COURSE, qh="q3"):
    from services.graph_service import apply_graph_update

    return apply_graph_update(user, {"void_evidence": {"question_hash": qh}}, course)


@pytest.mark.parametrize("seed", range(30))
def test_a_staff_retire_recomputes_the_state_a_history_without_the_item_gives(monkeypatch, seed):
    ops = history(seed)
    qh = f"q{seed % 14}"
    voided = lambda ev: ev["question_hash"] == qh  # noqa: E731
    db, _ = run(monkeypatch, ops)
    journal_before = deepcopy(db.journal)
    item_rows = [r for r in db.journal if r["question_hash"] == qh]
    db.retire(COURSE, qh)
    _void(qh=qh)
    expected, _ = run(monkeypatch, ops, skip=voided)  # the from-scratch run without the item

    assert db.journal == journal_before  # append-only: no journal row edited or removed
    assert sorted(db.voids) == sorted(r["id"] for r in item_rows)
    assert {v["reason"] for v in db.voids.values()} <= {evidence_void.VOID_REASON}
    for node in NODES:
        got, want = db.state(USER, node), expected.state(USER, node)
        if want is not None:
            assert got is not None and _same_state(got, want), node
            assert db.nodes[node]["mastery_score"] == expected.nodes[node]["mastery_score"], node
        elif got is not None:
            # every evidence that reached it was void: back at the BKT prior
            assert {k: got[k] for k in PRIOR} == PRIOR, node
            assert db.nodes[node]["mastery_score"] == BKT_L0
            assert db.nodes[node]["mastery_tier"] == "learning"


def test_re_running_a_void_writes_nothing(monkeypatch):
    db, _ = run(monkeypatch, history(3))
    db.retire(COURSE, "q5")
    _void(qh="q5")
    states = {n: db.state(USER, n) for n in NODES}
    versions = {n: db.nodes[n]["evidence_version"] for n in NODES}
    first = db.void_commits[-1]
    assert first["voided"] > 0
    _void(qh="q5")
    assert db.void_commits[-1] == {
        "status": "committed", "voided": 0, "states": 0, "mirrors": 0, "misconceptions": 0,
    }
    assert {n: db.state(USER, n) for n in NODES} == states
    assert {n: db.nodes[n]["evidence_version"] for n in NODES} == versions
    plans = [p for name, p in db.calls if name == "learning_evidence_void_commit"]
    assert plans[-1]["p_plan"] == {**plans[-2]["p_plan"], "states_expected": plans[-1]["p_plan"]["states_expected"],
                                   "nodes": plans[-1]["p_plan"]["nodes"]}  # same rows, fresh versions


def test_voiding_a_correct_answer_takes_back_its_propagation(monkeypatch):
    """The voided check on n-b propagated to its prerequisite n-a; the later
    valid check on n-a (correct: it moves n-a's own prerequisites, none) is
    replayed from the corrected belief, and n-b, which only the voided check
    reached, is back at the prior."""
    ops = [
        (3600.0, None, [{"node_id": "n-b", "channel": "free_response", "correct": True,
                         "question_hash": "q-broken", "check_item_id": "ci-broken"}]),
        (86_400.0, None, [{"node_id": "n-a", "channel": "mc_reasoned", "correct": True,
                           "question_hash": "q-ok", "check_item_id": "ci-ok"}]),
    ]
    db, _ = run(monkeypatch, ops)
    assert db.journal[0]["propagated_to"] == ["n-a"]
    db.retire(COURSE, "q-broken")
    changes = _void(qh="q-broken")
    expected, _ = run(monkeypatch, ops, skip=lambda ev: ev["question_hash"] == "q-broken")
    assert _same_state(db.state(USER, "n-a"), expected.state(USER, "n-a"))
    assert {k: db.state(USER, "n-b")[k] for k in PRIOR} == PRIOR
    assert {c["concept"] for c in changes} == {"Concept n-a", "Concept n-b"}


def test_a_grade_on_a_retired_item_is_refused_and_writes_nothing(monkeypatch):
    """The race, hermetic half: the commit refuses a batch grading a retired
    item (under the item's lock in SQL), so no non-void row can follow a
    retire. The evidence path raises a superseded-kind error, never retries."""
    from services.graph_service import apply_graph_update

    db, _ = run(monkeypatch, history(5, ops=6))
    db.retire(COURSE, "q-late")
    rows, states = deepcopy(db.journal), {n: db.state(USER, n) for n in NODES}
    before = len(db.calls)
    with pytest.raises(EvidenceItemRetired):
        apply_graph_update(USER, {"evidence": [
            {"node_id": "n-a", "channel": "free_response", "correct": True,
             "question_hash": "q-late", "check_item_id": "ci-late"},
        ]}, COURSE)
    assert db.journal == rows and {n: db.state(USER, n) for n in NODES} == states
    commits = [n for n, _ in db.calls[before:] if n == "learning_evidence_commit"]
    assert len(commits) == 1  # refused once, not retried
    # a quiz question is never a check item: no check_item_id, never refused
    apply_graph_update(USER, {"evidence": [
        {"node_id": "n-a", "channel": "mc", "correct": True, "question_hash": "q-late"},
    ]}, COURSE)
    assert len(db.journal) == len(rows) + 1


def test_a_void_of_an_item_staff_have_not_retired_is_refused(monkeypatch):
    db, _ = run(monkeypatch, history(7, ops=8))
    for status in (None, "quarantined", "approved"):
        if status:
            db.retire(COURSE, "q2", status=status)
        with pytest.raises(EvidenceVoidRefused):
            _void(qh="q2")
    assert db.voids == {} and not [n for n, _ in db.calls if n == "learning_evidence_void_commit"]


def test_a_stale_void_snapshot_is_read_again(monkeypatch):
    """Evidence journaled between the void's read and its commit moves a
    version: the commit answers stale and the void re-reads and re-plans."""
    from services.graph_service import apply_graph_update

    db, clock = run(monkeypatch, history(11, ops=10))
    db.retire(COURSE, "q4")
    real = db.rpc
    raced = {"done": False}

    def rpc(name, params):
        if name == "learning_evidence_void_commit" and not raced["done"]:
            # another grade on a recomputed node lands between read and commit
            raced["done"] = True
            clock.advance(seconds=30)
            late = params["p_plan"]["nodes"][0]["id"]
            apply_graph_update(
                USER, {"evidence": [{"node_id": late, "channel": "chat_turn", "correct": True}]}, COURSE
            )
        return real(name, params)

    from learning import evidence_transaction as tx
    from test_learning_evidence_replay import _journal, _replay

    monkeypatch.setattr(tx, "rpc", rpc)
    _void(qh="q4")
    statuses = [out["status"] for out in db.void_commits]
    assert raced["done"] and statuses == ["committed"]  # the first commit answered stale
    assert len([n for n, _ in db.calls if n == "learning_evidence_void_commit"]) == 2
    # what was committed is the replay of the journal INCLUDING the late row
    expected = _replay(db, [r for r in _journal(db) if not r["void"]])
    for node, row in expected.state_rows.items():
        assert _same_state(db.state(USER, node), row), node


def test_the_void_branch_is_applied_alone_in_a_course(monkeypatch):
    from services.graph_service import apply_graph_update

    db, _ = run(monkeypatch, [])
    for payload, course in (
        ({"void_evidence": {"question_hash": "q"}, "evidence": []}, COURSE),
        ({"void_evidence": {"question_hash": "q"}, "new_nodes": []}, COURSE),
        ({"void_evidence": {"question_hash": "q"}}, None),
        ({"void_evidence": {"question_hash": ""}}, COURSE),
        ({"void_evidence": "q"}, COURSE),
    ):
        with pytest.raises(ValueError):
            apply_graph_update(USER, payload, course)
    assert db.calls == []


def test_a_void_failure_surfaces_and_writes_nothing(monkeypatch):
    db, _ = run(monkeypatch, history(13, ops=8))
    db.retire(COURSE, "q1")
    real = db.rpc

    def down(name, params):
        if name == "learning_evidence_void_commit":
            raise ConnectionError("store down")
        return real(name, params)

    from learning import evidence_transaction as tx

    monkeypatch.setattr(tx, "rpc", down)
    with pytest.raises(PlanningPersistenceUnavailable):
        _void(qh="q1")
    assert db.voids == {}


# ── misconceptions: closed when every supporting attempt is void ────────────


def _misconception(db, mid, node, count, *, check_item_id, attempts):
    db.misconceptions[mid] = {
        "user_id": USER, "node_id": node, "count": count, "check_item_id": check_item_id,
        "resolved_at": None, "resolved_reason": None,
    }
    db.attempts += [{"misconception_id": mid, **a} for a in attempts]


def test_misconceptions_supported_only_by_void_attempts_are_closed(monkeypatch):
    ops = [
        (60.0, None, [{"node_id": "n-c", "channel": "mc_reasoned", "correct": False,
                       "question_hash": "q-bad", "check_item_id": "ci-bad"}]),
        (60.0, None, [{"node_id": "n-c", "channel": "mc_reasoned", "correct": False,
                       "question_hash": "q-good", "check_item_id": "ci-good"}]),
    ]
    db, _ = run(monkeypatch, ops)
    bad = {"course_id": COURSE, "question_hash": "q-bad", "check_item_id": "ci-bad"}
    good = {"course_id": COURSE, "question_hash": "q-good", "check_item_id": "ci-good"}
    unknown = {"course_id": COURSE, "question_hash": None, "check_item_id": "ci-bad"}
    _misconception(db, "m-only-bad", "n-c", 2, check_item_id="ci-bad", attempts=[bad, bad])
    _misconception(db, "m-mixed", "n-c", 2, check_item_id="ci-bad", attempts=[good, bad])
    _misconception(db, "m-unknown", "n-c", 1, check_item_id="ci-bad", attempts=[unknown])
    _misconception(db, "m-legacy-one", "n-c", 1, check_item_id="ci-bad", attempts=[])
    _misconception(db, "m-legacy-many", "n-c", 3, check_item_id="ci-bad", attempts=[])
    _misconception(db, "m-partly-recorded", "n-c", 2, check_item_id="ci-bad", attempts=[bad])
    db.retire(COURSE, "q-bad")
    _void(qh="q-bad")
    closed = {m for m, row in db.misconceptions.items() if row["resolved_at"]}
    assert closed == {"m-only-bad", "m-legacy-one"}
    assert {db.misconceptions[m]["resolved_reason"] for m in closed} == {"evidence_void"}
    assert db.void_commits[-1]["misconceptions"] == 2


def test_closable_misconceptions_rule():
    rule = evidence_void.closable_misconceptions
    v1 = {"course_id": "c", "question_hash": "h1", "check_item_id": "i1"}
    v2 = {"course_id": "c", "question_hash": "h2", "check_item_id": "i2"}
    live = {"course_id": "c", "question_hash": "h3", "check_item_id": "i3"}
    other_course = {"course_id": "c2", "question_hash": "h1", "check_item_id": "i1"}
    rows = [
        {"id": "a", "count": 2, "check_item_id": "i2", "attempts": [v1, v2]},  # two retired items
        {"id": "b", "count": 2, "check_item_id": "i1", "attempts": [v1, live]},
        {"id": "c", "count": 1, "check_item_id": "i1", "attempts": [other_course]},
        {"id": "d", "count": 1, "check_item_id": "i1", "attempts": []},
        {"id": "e", "count": 1, "check_item_id": "i3", "attempts": []},
        {"id": "f", "count": 0, "check_item_id": "i1", "attempts": []},
        {"id": "g", "count": True, "check_item_id": "i1", "attempts": []},
    ]
    out = rule(rows, course_id="c", retired_hashes={"h1", "h2"}, retired_check_ids={"i1", "i2"})
    assert out == [{"id": "a", "count": 2}, {"id": "d", "count": 1}]


def test_the_void_rule_on_rows_and_poses():
    retired = {("c1", "h1")}
    assert evidence_void.is_void_row({"check_item_id": "i", "question_hash": "h1", "course_id": "c1"}, retired)
    assert evidence_void.is_void_row(
        {"check_item_id": "i", "question_hash": "h1", "graph_nodes": {"course_id": "c1"}}, retired
    )
    assert evidence_void.is_void_row({"check_item_id": "i", "question_hash": "h1"}, retired, "c1")
    assert not evidence_void.is_void_row({"check_item_id": None, "question_hash": "h1", "course_id": "c1"}, retired)
    assert not evidence_void.is_void_row({"check_item_id": "i", "question_hash": "h1", "course_id": "c2"}, retired)
    assert not evidence_void.is_void_row({"check_item_id": "i", "question_hash": "h1"}, retired)
    assert evidence_void.pose_is_void({"course_id": "c1", "question_hash": "h1"}, retired)
    assert not evidence_void.pose_is_void({"course_id": "c1", "question_hash": "h2"}, retired)
    assert not evidence_void.pose_is_void({"course_id": None, "question_hash": "h1"}, retired)
