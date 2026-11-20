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

from db.migration_units import MIGRATION_UNITS
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from evidence_journal_fakes import _same_state
from learning import evidence_void
from learning.evidence import PlanningPersistenceUnavailable
from learning.evidence_transaction import EvidenceItemRetired, EvidenceVoidRefused
from learning.params import BKT_L0
from learning.bkt import tier_for_stored
from learning.learner_state import state_row, unmeasured_state
from test_learning_evidence_replay import COURSE, NODES, SCORES, USER, history, run

PRIOR = {
    "p_known": BKT_L0, "n_strong_unassisted": 0, "streak_unassisted": 0,
    "max_streak_unassisted": 0, "opps": 0, "fsrs_d": None, "fsrs_s": None,
    "fsrs_last_review_at": None, "fsrs_due_at": None, "last_evidence_at": None,
}


def _void(user=USER, course=COURSE, qh="q3"):
    from services.graph_service import apply_graph_update

    return apply_graph_update(user, {"void_evidence": {"question_hash": qh}}, course)


def _start(node: str, score: float) -> dict:
    """The learner_state columns a node starts from (spec §13 A150)."""
    row = state_row(unmeasured_state(USER, node, score), datetime.now(timezone.utc))
    return {k: row[k] for k in PRIOR}


@pytest.mark.parametrize("scores", [None, SCORES], ids=["never-studied", "stored-scores"])
@pytest.mark.parametrize("seed", range(30))
def test_a_staff_retire_recomputes_the_state_a_history_without_the_item_gives(monkeypatch, seed, scores):
    ops = history(seed)
    qh = f"q{seed % 14}"
    voided = lambda ev: ev["question_hash"] == qh  # noqa: E731
    db, _ = run(monkeypatch, ops, scores=scores)
    journal_before = deepcopy(db.journal)
    item_rows = [r for r in db.journal if r["question_hash"] == qh]
    db.retire(COURSE, qh)
    _void(qh=qh)
    # the from-scratch run without the item
    expected, _ = run(monkeypatch, ops, skip=voided, scores=scores)

    assert db.journal == journal_before  # append-only: no journal row edited or removed
    assert sorted(db.voids) == sorted(r["id"] for r in item_rows)
    assert {v["reason"] for v in db.voids.values()} <= {evidence_void.VOID_REASON}
    for node in NODES:
        got, want = db.state(USER, node), expected.state(USER, node)
        if want is not None:
            assert got is not None and _same_state(got, want), node
            assert db.nodes[node]["mastery_score"] == expected.nodes[node]["mastery_score"], node
        elif got is not None:
            # every evidence that reached it was void: back where it started
            # (A150: its stored score, else the prior), the mirror its belief —
            # off the map again for a never-studied concept (K22)
            score = (scores or {}).get(node, 0.0)
            start = _start(node, score)
            shown = start["p_known"] if score > 0 else 0.0
            assert {k: got[k] for k in PRIOR} == start, node
            assert db.nodes[node]["mastery_score"] == shown
            assert db.nodes[node]["mastery_tier"] == tier_for_stored(shown)


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


def _check(node, qh, correct=True, channel="free_response"):
    return {"node_id": node, "channel": channel, "correct": correct,
            "question_hash": qh, "check_item_id": f"ci-{qh}"}


def _assert_as_without(db, expected, nodes):
    for node in nodes:
        assert _same_state(db.state(USER, node), expected.state(USER, node)), node
        assert db.nodes[node]["mastery_score"] == expected.nodes[node]["mastery_score"], node


def test_voiding_the_first_answer_on_a_stored_score_replays_from_that_score(monkeypatch):
    """Spec §13 A150: n-a's 82% is its starting belief. The first answer on it
    (the one that started it and journaled the seed) is voided; the replay of
    the second starts from 82% exactly as a history without the first does —
    not from the 0.35 prior."""
    ops = [
        (3600.0, None, [_check("n-a", "q-broken", correct=False)]),
        (86_400.0, None, [_check("n-a", "q-ok", correct=True, channel="mc")]),
    ]
    db, _ = run(monkeypatch, ops, scores={"n-a": 0.82})
    # the wrong answer also reached n-a's never-studied dependents
    assert db.journal[0]["seeds"] == {"n-a": 0.82, "n-b": 0.0, "n-d": 0.0}
    assert db.journal[1]["seeds"] is None
    db.retire(COURSE, "q-broken")
    _void(qh="q-broken")
    expected, _ = run(monkeypatch, ops, skip=lambda ev: ev["question_hash"] == "q-broken",
                      scores={"n-a": 0.82})
    _assert_as_without(db, expected, ["n-a"])
    [kept] = [r for r in expected.journal]
    assert kept["p_before"] == pytest.approx(0.82)  # the history without starts from the score


def test_voiding_the_answer_that_seeded_a_propagated_neighbour_replays_from_its_score(monkeypatch):
    """The voided correct answer on n-b propagated to n-a (stored 60%) and
    journaled n-a's seed on ITS row; a later valid answer on n-b propagates
    to n-a again. The replay starts n-a from 60%, as a history without the
    voided answer does."""
    ops = [
        (3600.0, None, [_check("n-b", "q-broken")]),
        (86_400.0, None, [_check("n-b", "q-ok")]),
    ]
    scores = {"n-a": 0.6, "n-b": 0.4}
    db, _ = run(monkeypatch, ops, scores=scores)
    assert db.journal[0]["seeds"] == {"n-b": 0.4, "n-a": 0.6}
    db.retire(COURSE, "q-broken")
    _void(qh="q-broken")
    expected, _ = run(monkeypatch, ops, skip=lambda ev: ev["question_hash"] == "q-broken",
                      scores=scores)
    _assert_as_without(db, expected, ["n-a", "n-b"])


def test_a_never_studied_concept_still_starts_at_the_prior(monkeypatch):
    from learning import bkt

    ops = [
        (3600.0, None, [_check("n-c", "q-broken", correct=False)]),
        (86_400.0, None, [_check("n-c", "q-ok")]),
    ]
    db, _ = run(monkeypatch, ops)
    assert db.journal[0]["seeds"] == {"n-c": 0.0}
    assert db.journal[0]["p_before"] == BKT_L0
    db.retire(COURSE, "q-broken")
    _void(qh="q-broken")
    expected, _ = run(monkeypatch, ops, skip=lambda ev: ev["question_hash"] == "q-broken")
    _assert_as_without(db, expected, ["n-c"])
    assert expected.journal[0]["p_before"] == BKT_L0
    assert db.state(USER, "n-c")["p_known"] == bkt.update(BKT_L0, "free_response", True)


def test_a_void_of_the_only_answer_puts_a_stored_score_back(monkeypatch):
    """No non-void row reaches n-a any more: it is back at its starting state
    and its 82% is back on the map, so the next answer starts from 82% as it
    would have with the voided answer never given."""
    from services.graph_service import apply_graph_update

    ops = [(3600.0, None, [_check("n-a", "q-broken", correct=False)])]
    db, _ = run(monkeypatch, ops, scores={"n-a": 0.82})
    db.retire(COURSE, "q-broken")
    _void(qh="q-broken")
    assert {k: db.state(USER, "n-a")[k] for k in PRIOR} == _start("n-a", 0.82)
    assert db.nodes["n-a"]["mastery_score"] == 0.82
    assert db.nodes["n-a"]["mastery_tier"] == tier_for_stored(0.82)
    apply_graph_update(USER, {"evidence": [_check("n-a", "q-next", channel="mc")]}, COURSE)
    assert db.journal[-1]["p_before"] == 0.82


def test_a_void_of_the_only_answer_puts_a_never_studied_concept_back_off_the_map(monkeypatch):
    """K22 on the void path: n-c and its prerequisite n-b were never studied
    (map score 0). The only answer, a correct one on n-c, is voided: both are
    back at 0, 'unexplored', and n-c's state is its starting state, as if the
    answer had never been given."""
    ops = [(3600.0, None, [_check("n-c", "q-broken", correct=True)])]
    db, _ = run(monkeypatch, ops)
    assert db.journal[0]["seeds"] == {"n-c": 0.0, "n-b": 0.0}
    assert db.nodes["n-c"]["mastery_score"] > 0.0  # the answer put it on the map
    db.retire(COURSE, "q-broken")
    _void(qh="q-broken")
    assert {k: db.state(USER, "n-c")[k] for k in PRIOR} == _start("n-c", 0.0)
    for node in ("n-c", "n-b"):
        assert db.nodes[node]["mastery_score"] == 0.0, node
        assert db.nodes[node]["mastery_tier"] == "unexplored", node


def test_the_writer_journals_each_starting_score_once(monkeypatch):
    """The first row to reach a node with no learner_state row carries its
    score (0 for a never-studied concept), own node or propagated neighbour;
    no later row repeats it."""
    ops = [
        (60.0, None, [_check("n-b", "q1"), _check("n-a", "q2"), _check("n-c", "q3", correct=False)]),
        (60.0, None, [_check("n-b", "q4")]),
    ]
    db, _ = run(monkeypatch, ops, scores={"n-a": 0.82, "n-b": 1.0})
    assert [r["seeds"] for r in db.journal] == [
        {"n-b": 1.0, "n-a": 0.82}, None, {"n-c": 0.0}, None,
    ]


def test_a_journaled_seed_the_replay_cannot_read_fails_closed():
    from learning.evidence_replay import ReplayError, journaled_seeds

    assert journaled_seeds([{"seeds": None}, {"seeds": {"n": 0.5}}, {"seeds": {"n": 0.9}}]) == {"n": 0.5}
    for broken in ("n", ["n"], {"": 0.5}, {"n": 1.5}, {"n": -0.1}, {"n": "0.5"}, {"n": True}):
        with pytest.raises(ReplayError):
            journaled_seeds([{"seeds": broken}])


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


def test_the_backend_holds_select_and_insert_only_on_both_records():
    """Supabase's default privileges grant service_role ALL on a new public
    table, so A123's GRANT SELECT, INSERT alone changed nothing there.
    20261108115157 revokes everything from service_role on both append-only
    records and grants back exactly SELECT and INSERT, guarded (a plain
    Postgres has no service_role). The real-DB half:
    tests/integration/test_learning_evidence_void_db.py."""
    import re

    migrations = MIGRATION_UNITS
    (grants,) = sorted(migrations.glob("*_learning_evidence_void_grants.sql"))
    (a123,) = sorted(migrations.glob("*_learning_evidence_void.sql"))
    assert grants.name > a123.name, "must sort after A123's migration"
    ddl = "\n".join(
        line for line in grants.read_text().splitlines() if not line.lstrip().startswith("--")
    )
    guard = "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN"
    assert guard in ddl
    for table in ("learning_evidence_voids", "misconception_attempts"):
        revoke = f"REVOKE ALL ON TABLE {table} FROM service_role;"
        grant = f"GRANT SELECT, INSERT ON TABLE {table} TO service_role;"
        assert ddl.index(guard) < ddl.index(revoke) < ddl.index(grant)
    granted = re.findall(r"GRANT ([^;]*?) ON TABLE \w+ TO service_role;", ddl)
    assert granted == ["SELECT, INSERT", "SELECT, INSERT"]


@pytest.mark.parametrize("function", ["learning_evidence_snapshot", "learning_evidence_void_snapshot"])
def test_the_snapshots_the_writer_plans_from_return_exact_floats(function):
    """The Supabase image sets extra_float_digits = 0, so to_jsonb() rounds a
    float8 to 15 significant digits. The writer planned from rounded states
    while its replay (A123) read them exactly, and a recompute differed from
    the writer's own state (20261108115720). The last migration statement that
    defines or alters each snapshot function must set extra_float_digits = 3:
    a CREATE OR REPLACE replaces every SET clause, so a later re-creation
    carries it itself."""
    import re

    migrations = MIGRATION_UNITS
    head = re.compile(
        rf"(CREATE\s+OR\s+REPLACE\s+FUNCTION|ALTER\s+FUNCTION)\s+(?:public\.)?{function}\s*\(", re.I
    )
    statements = []
    for path in sorted(migrations.glob("*.sql")):
        sql = re.sub(r"--[^\n]*", "", path.read_text())
        for m in head.finditer(sql):
            if m.group(1).upper().startswith("CREATE"):
                end = re.compile(r"\$[A-Za-z_]*\$").search(sql, m.end()).start()  # up to the body
            else:
                end = sql.index(";", m.end())
            statements.append((path.name, sql[m.start() : end]))
    assert statements, function
    name, last = statements[-1]
    assert re.search(r"SET\s+extra_float_digits\s*=\s*3\b", last), (function, name)
