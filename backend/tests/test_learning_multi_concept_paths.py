"""Multi-concept items on every item path (learning-loop spec §13 A141): the
void (A123), the hold (A124/A123), the report (A113), the item statistics
(A131), the alignment and key backfills, course_has_items, and the admin
report and queue. A multi-concept item is one check_items row per course item
(course_id, question_hash) — the identity every one of these paths keys on —
and its evidence is ordinary evidence on its apex at WEIGHT_MULTI_CONCEPT, so
each path handles it through the rule it already has; these tests pin that.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from learning import params
from learning.multi_concept import combo_key
from tests.test_learning_check_items import _cached_tables

APEX, PRE = "learning rate", "gradient descent"
KEY = combo_key([APEX, PRE])


# ── the void (A123) ──────────────────────────────────────────────────────────


def test_a_staff_retire_of_a_combination_voids_its_apex_evidence_exactly(monkeypatch):
    """The combination's answers are partial-weight rows on its apex (n-b here,
    whose prerequisite is n-a): the journal keeps the weight, the replay reads
    it, and a void recomputes the state the writer would have stored had the
    item never been answered — the propagation to n-a taken back too."""
    from test_learning_evidence_replay import (
        COURSE,
        NODES,
        USER,
        _assert_replay_matches,
        _journal,
        _replay,
        run,
    )

    from evidence_journal_fakes import _same_state
    from test_learning_evidence_void import PRIOR, _void

    combo = {
        "node_id": "n-b", "channel": "free_response", "question_hash": "q-combo",
        "check_item_id": "ci-combo", "multi_concept": True,
    }
    ops = [
        (3600.0, None, [{**combo, "correct": True}]),
        (7200.0, None, [{"node_id": "n-b", "channel": "mc_reasoned", "correct": True,
                         "question_hash": "q-ok", "check_item_id": "ci-ok"}]),
        (86_400.0, None, [{**combo, "correct": False}]),
    ]
    db, _ = run(monkeypatch, ops)
    combo_rows = [r for r in db.journal if r["question_hash"] == "q-combo"]
    assert [r["weight"] for r in combo_rows] == [params.WEIGHT_MULTI_CONCEPT] * 2
    # the journal says which rows a combination graded; every other row names no flag
    assert [r.get("multi_concept") for r in combo_rows] == [True, True]
    assert all("multi_concept" not in r for r in db.journal if r["question_hash"] != "q-combo")
    assert combo_rows[0]["propagated_to"] == ["n-a"]  # a correct apex answer credits its prerequisite
    _assert_replay_matches(db, _replay(db, _journal(db)))  # the replay reads the journaled weight

    db.retire(COURSE, "q-combo")
    _void(qh="q-combo")
    expected, _ = run(monkeypatch, ops, skip=lambda ev: ev["question_hash"] == "q-combo")
    assert sorted(db.voids) == sorted(r["id"] for r in combo_rows)
    for node in NODES:
        got, want = db.state(USER, node), expected.state(USER, node)
        if want is not None:
            assert got is not None and _same_state(got, want), node
        elif got is not None:
            assert {k: got[k] for k in PRIOR} == PRIOR, node


# ── the hold (A124 / A123) and the report (A113) ─────────────────────────────


def _row(qh, concept_key=KEY, **over):
    from services.encryption import encrypt_if_present

    return {
        "id": f"id-{qh}", "course_id": "c1", "concept_key": concept_key, "question_hash": qh,
        "format": "free", "difficulty": params.MULTI_CONCEPT_DIFFICULTY,
        "prompt": encrypt_if_present("Pick a rate for this descent run."),
        "reference_answer": encrypt_if_present("Because. Final answer: 0.1."),
        "final_answer": encrypt_if_present("0.1"),
        "rubric_json": encrypt_if_present('[{"id": "r1", "text": "x"}]'),
        "common_wrong_json": encrypt_if_present("[]"),
        "source_chunk_ids": [], "canonical_verified": True, "lint_flags": [],
        **over,
    }


@pytest.mark.parametrize("flags", [["key_disputed"], ["reports_threshold"], ["staff_retired"]])
def test_a_held_combination_is_never_served(monkeypatch, flags):
    from services.check_item_service import multi_concept_items

    factory, _ = _cached_tables(
        {"check_items": [_row("ok"), _row("held", lint_flags=flags, canonical_verified=False)]}
    )
    with patch("services.check_item_service.table", side_effect=factory):
        assert [i.question_hash for i in multi_concept_items("c1", APEX)] == ["ok"]


def test_a_report_quarantine_holds_a_combination_like_any_item():
    """The report path keys on (course_id, question_hash): a combination's
    quarantine code is a staff hold whatever its key (checks.held)."""
    from learning.checks import held_flags

    assert held_flags(["reports_threshold"], True)
    assert not held_flags([], True)


def test_a_reported_combination_is_never_posed_again(monkeypatch):
    """The pick excludes everything the student met — reported included (the
    activation's `excluded` set carries loop_state_store.reported_hashes)."""
    from tests.test_learning_varied_serving import _combo, _pick

    assert _pick(monkeypatch, [_combo("pair")], excluded={"pair"}) is None


def test_course_has_items_never_counts_a_combination(monkeypatch):
    from services.check_item_service import course_has_items

    only_combos = [{"id": "a", "concept_key": KEY, "lint_flags": [], "canonical_verified": True}]
    factory, _ = _cached_tables({"check_items": only_combos})
    with patch("services.check_item_service.table", side_effect=factory):
        assert course_has_items("c1") is False
    single = [*only_combos, {"id": "b", "concept_key": APEX, "lint_flags": [], "canonical_verified": True}]
    factory, _ = _cached_tables({"check_items": single})
    with patch("services.check_item_service.table", side_effect=factory):
        assert course_has_items("c1") is True


# ── the re-check after a release (A76) ───────────────────────────────────────


def test_a_combinations_isomorph_class_names_its_combination():
    from learning.multi_concept import isomorph_class

    assert isomorph_class("free", 3, APEX) == ("free", 3)  # a concept's own item: as always
    assert isomorph_class("free", 3, KEY) == ("free", 3, KEY)
    assert isomorph_class(None, None, None) == (None, None)  # unreadable: A76 fails closed on it


@pytest.mark.parametrize(
    "released,graded,owed",
    [
        # a released combination never makes the apex's own (free, 3) a re-check
        (("free", 3, KEY), ("free", 3), False),
        # nor a released single-concept item the combination
        (("free", 3), ("free", 3, KEY), False),
        # the same combination's class-mates are re-checks, as any class's
        (("free", 3, KEY), ("free", 3, KEY), True),
        # another combination of the same apex is another construct
        (("free", 3, combo_key([APEX, PRE, "loss"])), ("free", 3, KEY), False),
        # an unreadable released item still owes on every class (R5-3)
        (None, ("free", 3, KEY), True),
    ],
)
def test_a_release_owes_only_its_own_construct(released, graded, owed):
    from learning.misconceptions import owed_isomorph

    rows = [{"question_hash": "r", "released": True, "shape": released}]
    assert owed_isomorph(rows, graded) is owed


def test_the_journal_read_and_the_decision_carry_the_combination(monkeypatch):
    """recent_evidence tags a combination's row with its key; the grade of
    the apex's own (free, 3) after a released combination is no re-check,
    and the grade of the combination after a released (free, 3) of the apex
    is none either — while a released combination's class-mate is one."""
    from learning import loop_state_store as store
    from learning import misconceptions
    from tests.test_learning_misconceptions import _FakeJournal

    monkeypatch.setattr(misconceptions, "_prequestion_owes", lambda *a, **k: False)
    now = datetime.now(timezone.utc)

    def decide(journal, items, item):
        with patch.object(store, "table", side_effect=_FakeJournal(journal, items)):
            return misconceptions.recheck_after_release("u1", "n-apex", {}, now=now, item=item)

    items = [
        {"id": "ci-x", "format": "free", "difficulty": 3, "concept_key": KEY},
        {"id": "ci-a", "format": "free", "difficulty": 3, "concept_key": APEX},
        {"id": "ci-b", "format": "teachback", "difficulty": 3, "concept_key": APEX},
    ]
    combo_released = [
        {"check_item_id": "ci-x", "question_hash": "x", "correct": False, "max_rung": 0},
        {"check_item_id": "ci-b", "question_hash": "b", "correct": True, "max_rung": 0},
    ]
    single = MagicMock(question_hash="a2", format="free", difficulty=3, concept_key=APEX)
    twin = MagicMock(question_hash="x2", format="free", difficulty=3, concept_key=KEY)
    assert decide(combo_released, items, single) is False
    assert decide(combo_released, items, twin) is True
    single_released = [
        {"check_item_id": "ci-a", "question_hash": "a", "correct": False, "max_rung": 0},
        {"check_item_id": "ci-b", "question_hash": "b", "correct": True, "max_rung": 0},
    ]
    assert decide(single_released, items, twin) is False
    assert decide(single_released, items, single) is True
    with patch.object(store, "table", side_effect=_FakeJournal(combo_released, items)):
        rows = store.recent_evidence("u1", "n-apex", since="2026-11-01T00:00:00+00:00")
    assert [r["shape"] for r in rows] == [("free", 3, KEY), ("teachback", 3)]


# ── the item statistics (A131) ───────────────────────────────────────────────


T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)


def _ev(user, node, qh, correct, minute, check="ci"):
    return {
        "id": f"{user}-{qh}", "node_id": node, "question_hash": qh, "check_item_id": f"{check}-{qh}",
        "correct": correct, "assisted": False, "max_rung": 0, "same_session_recheck": False,
        "weight": 1.0, "channel": "free_response", "reason": "evidence:free_response",
        "created_at": (T0.replace(minute=minute)).isoformat(),
        "graph_nodes": {"user_id": user, "course_id": "c1"},
    }


def test_multi_concept_rests_are_the_components_own_items():
    from learning.item_stats import multi_concept_rests

    stored = [
        {"course_id": "c1", "concept_key": APEX, "question_hash": "a1"},
        {"course_id": "c1", "concept_key": PRE, "question_hash": "p1"},
        {"course_id": "c1", "concept_key": "momentum", "question_hash": "m1"},
        {"course_id": "c1", "concept_key": KEY, "question_hash": "x1"},
    ]
    assert multi_concept_rests(stored) == {("c1", "x1"): frozenset({("c1", "a1"), ("c1", "p1")})}
    assert multi_concept_rests(stored[:3]) == {}


def test_a_combinations_discrimination_reads_its_components_and_a_concepts_leaves_it_out():
    from learning.item_stats import item_statistics, multi_concept_rests

    stored = [
        {"course_id": "c1", "concept_key": APEX, "question_hash": "a1"},
        {"course_id": "c1", "concept_key": APEX, "question_hash": "a2"},
        {"course_id": "c1", "concept_key": PRE, "question_hash": "p1"},
        {"course_id": "c1", "concept_key": KEY, "question_hash": "x1"},
    ]
    rows = []
    # u1 strong on the components and right on the combination; u2 weak and wrong;
    # u3 mixed and right. The combination's evidence sits on the apex node.
    for user, (a1, a2, p1, x1) in {
        "u1": (True, True, True, True),
        "u2": (False, False, False, False),
        "u3": (True, False, True, True),
    }.items():
        rows += [
            _ev(user, f"{user}-apex", "a1", a1, 1),
            _ev(user, f"{user}-apex", "a2", a2, 2),
            _ev(user, f"{user}-pre", "p1", p1, 3),
            _ev(user, f"{user}-apex", "x1", x1, 4),
        ]
    multi = multi_concept_rests(stored)
    stats = item_statistics(rows, multi=multi)
    plain = item_statistics(rows)
    # the combination: its rest is a1, a2 AND p1 (another node), not the apex alone
    x1 = stats[("c1", "x1")]
    assert x1["n"] == 3 and x1["discrimination_n"] == 3
    rests = {"u1": 1.0, "u2": 0.0, "u3": 2 / 3}
    outcomes = {"u1": 1.0, "u2": 0.0, "u3": 1.0}
    from learning.item_stats import _pearson

    assert x1["discrimination"] == _pearson([(outcomes[u], rests[u]) for u in ("u1", "u2", "u3")])
    # a concept's item leaves the combination out of its rest score
    a1 = stats[("c1", "a1")]
    assert a1["discrimination"] == _pearson([(1.0, 1.0), (0.0, 0.0), (1.0, 0.0)])
    assert plain[("c1", "a1")]["discrimination"] != a1["discrimination"]  # before: x1 counted
    # with no combination stored, the numbers are exactly the A131 ones
    singles = [r for r in rows if r["question_hash"] != "x1"]
    assert item_statistics(singles, multi=None) == item_statistics(singles)


def _combo_rows():
    """u1..u3 on the apex's own a1 and a2 and the combination x1, whose rows
    the journal flags (its evidence sits on the apex node)."""
    rows = []
    for user, (a1, a2, x1) in {
        "u1": (True, True, True),
        "u2": (False, False, False),
        "u3": (True, False, False),
    }.items():
        rows += [
            _ev(user, f"{user}-apex", "a1", a1, 1),
            _ev(user, f"{user}-apex", "a2", a2, 2),
            {**_ev(user, f"{user}-apex", "x1", x1, 4), "multi_concept": True},
        ]
    return rows


def test_a_withdrawn_combination_stays_out_of_the_apex_items_rest_scores():
    """A23: consent withdrawal deletes the combination's row, so the stored
    rows no longer name it; the journal still does, and the apex's own items
    keep reading only each other — their numbers are the ones they had while
    it was stored."""
    from learning.item_stats import item_statistics, journaled_combinations, multi_concept_rests

    rows = _combo_rows()
    assert journaled_combinations(rows) == {("c1", "x1")}
    stored = [
        {"course_id": "c1", "concept_key": APEX, "question_hash": "a1"},
        {"course_id": "c1", "concept_key": APEX, "question_hash": "a2"},
        {"course_id": "c1", "concept_key": KEY, "question_hash": "x1"},
    ]
    while_stored = item_statistics(rows, multi=multi_concept_rests(stored))
    withdrawn = item_statistics(rows, multi=multi_concept_rests(stored[:2]) or None)
    for item in (("c1", "a1"), ("c1", "a2")):
        assert withdrawn[item] == while_stored[item]
    # the same rows with no journal flag read x1 as an apex item: what A141 forbids
    unflagged = [{k: v for k, v in r.items() if k != "multi_concept"} for r in rows]
    assert item_statistics(unflagged)[("c1", "a1")] != while_stored[("c1", "a1")]


def test_a_retired_combination_changes_no_apex_items_numbers():
    """A123: a staff retire of a combination voids its rows on the apex; the
    apex's own items never counted them, so their numbers_changed_at stays —
    an item staff approved on its numbers does not come back as flagged."""
    from learning.item_stats import item_statistics

    rows = _combo_rows()
    before = item_statistics(rows)
    decided = T0.replace(hour=5)
    after = item_statistics(rows, retired={("c1", "x1"): decided})
    for item in (("c1", "a1"), ("c1", "a2")):
        assert after[item] == before[item]
        assert after[item]["numbers_changed_at"] < decided.isoformat()
    # a single-concept item's retire still dates its siblings' change, as A131 does
    after_single = item_statistics(rows, retired={("c1", "a2"): decided})
    assert after_single[("c1", "a1")]["numbers_changed_at"] == decided.isoformat()


def test_the_stats_route_names_a_combinations_components(monkeypatch):
    from routes import admin_check_items as route

    stored = [
        {"id": "i-a", "course_id": "c1", "concept_key": APEX, "question_hash": "a1", "format": "free",
         "difficulty": 2, "lint_flags": [], "canonical_verified": True},
        {"id": "i-x", "course_id": "c1", "concept_key": KEY, "question_hash": "x1", "format": "free",
         "difficulty": 3, "lint_flags": [], "canonical_verified": True},
    ]
    monkeypatch.setattr(route, "require_admin", lambda request: "admin")
    monkeypatch.setattr(route, "course_item_rows", lambda course: stored)
    monkeypatch.setattr(route, "_course_evidence", lambda course: ([], False))
    monkeypatch.setattr(route.item_reports, "report_counts", lambda: {})
    monkeypatch.setattr(route.item_reports, "reviews", lambda: {})
    out = route.item_statistics_report(MagicMock(), "c1")
    by_id = {i["id"]: i for i in out["items"]}
    assert by_id["i-x"]["components"] == [APEX, PRE]
    assert "components" not in by_id["i-a"]


def test_a_queue_entry_names_a_combinations_components():
    from learning.item_reports import review_entry

    entry = review_entry({"id": "i", "course_id": "c1", "concept_key": KEY, "question_hash": "x"}, {}, {})
    assert entry["components"] == [APEX, PRE]
    single = review_entry({"id": "i", "course_id": "c1", "concept_key": APEX, "question_hash": "x"}, {}, {})
    assert "components" not in single


# ── the backfills (A119, A124) ───────────────────────────────────────────────


def test_the_alignment_backfill_checks_a_combination_as_drafted(monkeypatch):
    """A stored combination is checked by the multi-concept check (every
    component needed), never by A119's one-concept question — which could
    re-tag it to one component. A course with none sends A119's requests only."""
    from learning.checks import CheckItem, RubricItem, WrongReason
    from learning.item_alignment import ComponentVerdict
    from services import check_item_service as svc

    def item(qh, key):
        return CheckItem(
            id=f"id-{qh}", course_id="c1", concept_key=key, format="free", difficulty=3,
            prompt="Q?", reference_answer="R", rubric=[RubricItem(id="r1", text="a"), RubricItem(id="r2", text="b")],
            common_wrong=[WrongReason(key="w", text="t")], source_chunk_ids=[], question_hash=qh,
            final_answer="R",
        )

    seen = {}

    def single(subjects, scope, *, deps, flex):
        seen["single"] = [s.prompt for s in subjects]
        return [None for _ in subjects]

    def combo(subjects, *, deps, flex):
        seen["combo"] = [names for _, names in subjects]
        return [ComponentVerdict({"c1": True, "c2": True}, {"k1": True, "k2": False})]

    monkeypatch.setattr(svc, "_verdicts_for", single)
    monkeypatch.setattr(svc, "_combo_verdicts_for", combo)
    out = svc.check_stored_alignment(
        "c1", [item("s", APEX), item("x", KEY)], {APEX: "Learning Rate", PRE: "Gradient Descent"}
    )
    assert seen == {"single": ["Q?"], "combo": [("Learning Rate", "Gradient Descent")]}
    assert out[0].unverified and out[1].reject  # the combination does not need gradient descent
    assert out[1].concept_key == KEY
    seen.clear()
    svc.check_stored_alignment("c1", [item("s", APEX)], {})
    assert set(seen) == {"single"}


def test_the_key_backfill_ranks_a_combinations_passages_as_its_drafting_did(monkeypatch):
    from services import check_item_service as svc

    chunks = [
        {"id": "c1", "chunk_index": 0, "chunk_text": "the learning rate scales each step", "doc_id": "d"},
        {"id": "c2", "chunk_index": 1, "chunk_text": "gradient descent follows the slope", "doc_id": "d"},
    ]
    monkeypatch.setattr(svc, "_source_rows", lambda docs: [{"id": "d"}])
    monkeypatch.setattr(svc, "source_chunks", lambda doc: chunks)
    out = svc.key_check_passages(
        [{"concept_key": KEY, "source_document_ids": ["d"]}],
        {APEX: "Learning Rate", PRE: "Gradient Descent"},
    )
    assert [c["id"] for c in out[KEY]] == ["c1", "c2"]
    out = svc.key_check_passages([{"concept_key": KEY, "source_document_ids": ["d"]}], {})
    assert [c["id"] for c in out[KEY]] == ["c1", "c2"]  # the keys stand in for the names
    gone = [chunks[0]]
    monkeypatch.setattr(svc, "source_chunks", lambda doc: gone)
    assert svc.key_check_passages([{"concept_key": KEY, "source_document_ids": ["d"]}], {})[KEY] == []


# ── the admin report ─────────────────────────────────────────────────────────


def test_the_report_counts_served_and_outcomes_per_course_with_n():
    from learning.multi_concept_report import multi_concept_report

    items = [
        {"id": "x1", "course_id": "c1", "question_hash": "q1", "lint_flags": [], "canonical_verified": True},
        {"id": "x2", "course_id": "c1", "question_hash": "q2", "lint_flags": ["key_disputed"], "canonical_verified": False},
        {"id": "y1", "course_id": "c2", "question_hash": "q3", "lint_flags": [], "canonical_verified": True},
    ]
    served = [{"course_id": "c1", "question_hash": "q1"}] * 3 + [{"course_id": "c2", "question_hash": "q3"}]
    ev = []
    for user, correct, rung in (("u1", True, 0), ("u2", False, 0), ("u1", True, 2)):
        row = _ev(user, f"{user}-apex", "q1", correct, 1)
        row.update(check_item_id="x1", max_rung=rung, assisted=rung > 0)
        ev.append(row)
    ev.append({**_ev("u9", "n", "zz", True, 1), "check_item_id": "single-item"})  # not a combination
    out = multi_concept_report(items, served, ev)
    c1 = next(b for b in out["courses"] if b["course_id"] == "c1")
    assert (c1["items"], c1["held"], c1["served"]) == (2, 1, 3)
    assert (c1["answered"], c1["correct"], c1["unassisted"], c1["unassisted_correct"]) == (3, 2, 2, 1)
    assert c1["students"] == 2 and c1["correct_rate"] == pytest.approx(2 / 3)
    assert c1["correct_ci_low"] < 2 / 3 < c1["correct_ci_high"]
    c2 = next(b for b in out["courses"] if b["course_id"] == "c2")
    assert c2["answered"] == 0 and c2["correct_rate"] is None and c2["correct_ci_low"] is None
    assert out["overall"]["items"] == 3 and out["overall"]["served"] == 4
    assert out["overall"]["answered"] == 3 and out["overall"]["students"] == 2


def test_the_admin_kpis_carry_the_report_and_a_failed_read_leaves_it_none(monkeypatch):
    from fastapi.testclient import TestClient

    from main import app
    from routes import admin_analytics as analytics
    from tests.test_admin_learning_loop_kpis import RANGE, URL, _serve

    _serve(monkeypatch, {"events": [], "node_mastery_events": []})
    client = TestClient(app)
    body = client.get(URL, params=RANGE).json()
    assert body["multi_concept"]["overall"]["items"] == 0
    monkeypatch.setattr(analytics, "_multi_concept", lambda *a: (None, False))
    assert client.get(URL, params=RANGE).json()["multi_concept"] is None


def test_the_admin_report_reads_only_combination_evidence_and_leaves_void_rows_out(monkeypatch):
    from routes import admin_analytics as analytics

    items = [{"id": "x1", "course_id": "c1", "question_hash": "q1", "lint_flags": [], "canonical_verified": True}]
    void = {**_ev("u1", "n", "q1", True, 1), "check_item_id": "x1"}
    kept = {**_ev("u2", "n", "q1", False, 2), "check_item_id": "x1", "id": "kept"}
    scans = []

    def scan(table_name, columns, from_iso, to_iso, extra_filters=None, **kw):
        scans.append((table_name, extra_filters))
        if table_name == "node_mastery_events":
            return [void, kept], False
        return [{"payload": {"course_id": "c1", "question_hash": "q1"}}], False

    monkeypatch.setattr(analytics, "page_all", lambda *a, **k: iter(items))
    monkeypatch.setattr(analytics, "_scan_range", scan)
    report, truncated = analytics._multi_concept("f", "t", {("c1", "q1-retired")})
    assert report.overall.answered == 2 and not truncated
    report, _ = analytics._multi_concept("f", "t", {("c1", "q1")})  # the item staff-retired
    assert report.overall.answered == 0 and report.overall.served == 1
    assert ("node_mastery_events", {"event_type": "eq.evidence", "check_item_id": 'in.("x1")'}) in scans
