"""Spec §13 A131: empirical item statistics for staff.

The math of learning/item_stats.py against hand-computed fixtures — the
p-value, its Wilson interval, the corrected item–rest discrimination, the
flags and their minimum n — and the loop's definitions it reuses: the FIRST
attempt only, unassisted after the help floor, no re-check after a release,
an idk scored wrong, void rows and quiz rows left out. Then the admin route
(`GET /api/admin/check-items/stats`): admin only, read-only, the "flagged by
data" view, the approval rule, the scan cap and the 503."""

from __future__ import annotations

import math

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from learning import item_reports, params
from learning.item_audit import wilson
from learning.item_stats import (
    empty_stats,
    first_unassisted,
    flags_for,
    item_statistics,
    recheck,
    unassisted,
)

COURSE = "c1"
_SEQ = iter(range(1, 1_000_000))


def _row(user, item, correct, *, at=None, node=None, course=COURSE, **over):
    """One evidence journal row as the statistics read it: an unassisted,
    full-weight, rung-0 first attempt unless `over` says otherwise."""
    seq = next(_SEQ)
    row = {
        "id": f"ev-{seq:06d}",
        "node_id": node or f"node-{user}",
        "question_hash": item,
        "check_item_id": f"ci-{item}",
        "channel": "free_response",
        "reason": "evidence:free_response",
        "correct": correct,
        "assisted": False,
        "max_rung": 0,
        "weight": 1.0,
        "confidence": 0.9,
        "same_session_recheck": False,
        "planning_recheck": None,
        "created_at": at or f"2026-11-01T00:{seq // 60 % 60:02d}:{seq % 60:02d}+00:00",
        "evidence_seq": seq,
        "graph_nodes": {"user_id": user, "course_id": course},
    }
    row.update(over)
    return row


# ── the hand-computed fixture ────────────────────────────────────────────────
#
# One concept, three items, five students (1 right, 0 wrong):
#
#          A  B  C
#    s1    1  1  1
#    s2    1  1  0
#    s3    0  0  1
#    s4    0  0  0
#    s5    1  .  .     (s5 answered A only: no rest score)
#
# A: n 5, correct 3, p 0.6. Discrimination over s1..s4: x = (1, 1, 0, 0),
#    rest = mean(B, C) = (1, 0.5, 0.5, 0); mean x = mean rest = 0.5;
#    Sxy = 0.25 + 0 + 0 + 0.25 = 0.5, Sxx = 1, Syy = 0.5 → r = 0.5/√0.5 = 1/√2.
# B: n 4, p 0.5; rest = mean(A, C) = (1, 0.5, 0.5, 0) against x = (1, 1, 0, 0)
#    → r = 1/√2 again.
# C: n 4, p 0.5; x = (1, 0, 1, 0), rest = mean(A, B) = (1, 1, 0, 0)
#    → Sxy = 0.25 − 0.25 − 0.25 + 0.25 = 0 → r = 0.

TABLE = {
    "s1": {"A": True, "B": True, "C": True},
    "s2": {"A": True, "B": True, "C": False},
    "s3": {"A": False, "B": False, "C": True},
    "s4": {"A": False, "B": False, "C": False},
    "s5": {"A": True},
}


def _fixture_rows():
    return [_row(user, item, ok) for user, answers in TABLE.items() for item, ok in answers.items()]


def test_the_hand_computed_fixture():
    stats = item_statistics(_fixture_rows())
    a, b, c = (stats[(COURSE, k)] for k in "ABC")
    assert (a["n"], a["correct"], a["p_value"]) == (5, 3, 0.6)
    assert (a["p_ci_low"], a["p_ci_high"]) == wilson(3, 5)
    assert a["discrimination_n"] == 4 and a["discrimination"] == pytest.approx(1 / math.sqrt(2))
    assert (b["n"], b["p_value"], b["discrimination_n"]) == (4, 0.5, 4)
    assert b["discrimination"] == pytest.approx(1 / math.sqrt(2))
    assert (c["n"], c["p_value"]) == (4, 0.5) and c["discrimination"] == pytest.approx(0.0)
    # far below ITEM_STATS_MIN_N: numbers, never a flag
    assert a["flags"] == b["flags"] == c["flags"] == []


def test_the_wilson_interval_by_hand():
    """3 of 5, z = 1.96: center (0.6 + 0.3841) / 1.7683 = 0.5565, half-width
    1.96·√(0.048 + 0.0384)/1.7683 = 0.3258 → (0.2307, 0.8824)."""
    low, high = wilson(3, 5)
    assert low == pytest.approx(0.2307, abs=1e-4) and high == pytest.approx(0.8824, abs=1e-4)


def test_no_variance_means_no_discrimination():
    rows = [_row(u, "A", True) for u in ("s1", "s2")] + [_row(u, "B", u == "s1") for u in ("s1", "s2")]
    stats = item_statistics(rows)
    assert stats[(COURSE, "A")]["discrimination"] is None  # everyone right on A
    assert stats[(COURSE, "B")]["discrimination"] is None  # the rest (A) does not vary


def test_the_rest_score_is_the_same_students_items_on_the_same_concept():
    """s1's other concept never enters A's rest score: items are per concept,
    and the concept is the student's node."""
    rows = [
        _row("s1", "A", True), _row("s1", "B", True), _row("s1", "Z", False, node="node-s1-other"),
        _row("s2", "A", False), _row("s2", "B", False),
    ]
    a = item_statistics(rows)[(COURSE, "A")]
    assert a["discrimination_n"] == 2 and a["discrimination"] == pytest.approx(1.0)


# ── first attempts, unassisted, re-checks ────────────────────────────────────


def test_only_the_first_attempt_counts():
    """A student whose first attempt was helped contributes nothing — a later
    unassisted answer is not a first attempt."""
    rows = [
        _row("s1", "A", True, assisted=True, max_rung=2, at="2026-11-01T00:00:01+00:00"),
        _row("s1", "A", True, at="2026-11-02T00:00:00+00:00"),
        _row("s2", "A", False, at="2026-11-01T00:00:00+00:00"),
        _row("s2", "A", True, at="2026-11-03T00:00:00+00:00"),  # a later right answer: not first
    ]
    a = item_statistics(rows)[(COURSE, "A")]
    assert (a["n"], a["correct"]) == (1, 0)


def test_the_journal_order_decides_the_first_attempt():
    same = "2026-11-01T00:00:00+00:00"
    rows = [
        _row("s1", "A", True, at=same, evidence_seq=2, id="ev-b"),
        _row("s1", "A", False, at=same, evidence_seq=1, id="ev-c"),
        _row("s2", "A", True, at=same, evidence_seq=None, id="ev-a"),  # before A36: after any seq
        _row("s2", "A", False, at=same, evidence_seq=5, id="ev-z"),
    ]
    obs = {(o["user_id"]): o["outcome"] for o in first_unassisted(rows)}
    assert obs == {"s1": 0, "s2": 0}


def test_a_pair_with_an_unreadable_time_is_left_out():
    rows = [_row("s1", "A", True, at="yesterday"), _row("s1", "A", False), _row("s2", "A", True)]
    assert {o["user_id"] for o in first_unassisted(rows)} == {"s2"}


@pytest.mark.parametrize(
    "over,expected",
    [
        ({}, True),
        ({"assisted": True, "max_rung": 1}, False),  # a hint
        ({"assisted": None}, False),  # unknown help is never unassisted
        ({"max_rung": 4}, False),  # the help floor raised the rung (a reveal, an outside-AI row)
        ({"max_rung": True}, False),
        ({"same_session_recheck": True, "weight": 0.5}, False),  # A76: a re-check after a release
    ],
)
def test_unassisted_is_the_loops_definition(over, expected):
    assert unassisted(_row("s1", "A", True, **over)) is expected


@pytest.mark.parametrize(
    "over,expected",
    [
        # pre-A123 rows: no journaled flag — the planning envelope's, else the weight's
        ({"same_session_recheck": None, "planning_recheck": True, "weight": 1.0}, True),
        ({"same_session_recheck": None, "planning_recheck": False, "weight": 0.5}, False),
        ({"same_session_recheck": None, "weight": 1.0}, False),
        ({"same_session_recheck": None, "weight": 0.5}, True),
        ({"same_session_recheck": None, "weight": 0.5, "confidence": 0.3}, False),  # low grader confidence
        ({"same_session_recheck": None, "weight": 0.25, "confidence": 0.3}, True),
        ({"same_session_recheck": None, "weight": 0.7}, None),  # no flag gives it: undecidable
        ({"same_session_recheck": None, "weight": None}, None),
    ],
)
def test_the_recheck_flag_of_an_older_row(over, expected):
    assert recheck(_row("s1", "A", True, **over)) is expected
    assert unassisted(_row("s1", "A", True, **over)) is (expected is False)


def test_an_incorrect_recheck_is_read_from_its_weight_too():
    wrong = _row("s1", "A", False, same_session_recheck=None, weight=0.5, confidence=None)
    assert recheck(wrong) is True and not unassisted(wrong)


def test_an_idk_is_a_wrong_answer():
    idk = _row("s1", "A", False, reason="evidence:free_response:idk", confidence=None)
    (ob,) = first_unassisted([idk])
    assert ob["outcome"] == 0


def test_void_and_quiz_rows_are_left_out_everywhere():
    """A123: an item staff retired is void — no statistics of its own and no
    part of any rest score. A quiz row names no check item."""
    rows = _fixture_rows() + [_row("s9", "Q", True, check_item_id=None)]
    retired = {(COURSE, "C")}
    stats = item_statistics(rows, retired=retired)
    assert (COURSE, "C") not in stats and (COURSE, "Q") not in stats
    # without C, A's rest score is B alone: x = (1, 1, 0, 0) against rest (1, 1, 0, 0)
    assert stats[(COURSE, "A")]["discrimination"] == pytest.approx(1.0)


def test_numbers_changed_at_is_the_newest_attempt_its_numbers_count():
    rows = [
        _row("s1", "A", True, at="2026-11-01T00:00:00+00:00"),
        _row("s2", "A", True, at="2026-11-05T00:00:00+00:00"),
        _row("s1", "A", False, at="2026-11-09T00:00:00+00:00"),  # a later attempt: not counted
    ]
    assert item_statistics(rows)[(COURSE, "A")]["numbers_changed_at"] == "2026-11-05T00:00:00+00:00"


def test_a_new_answer_on_the_concepts_other_items_changes_the_numbers():
    """The discrimination reads the same students' other items, so a first
    attempt there changes the item's numbers without a new attempt on it."""
    rows = [
        _row("s1", "A", True, at="2026-11-01T00:00:00+00:00"),
        _row("s2", "A", False, at="2026-11-01T00:00:01+00:00"),
        _row("s1", "B", True, at="2026-11-06T00:00:00+00:00"),
        _row("s2", "B", False, at="2026-11-07T00:00:00+00:00"),
        _row("s3", "B", True, at="2026-11-08T00:00:00+00:00"),  # no answer on A: not in its numbers
    ]
    a = item_statistics(rows)[(COURSE, "A")]
    assert a["discrimination_n"] == 2 and a["numbers_changed_at"] == "2026-11-07T00:00:00+00:00"


def test_a_retire_that_voids_a_rest_score_attempt_changes_the_numbers():
    """A staff retire takes its item's attempts out of every rest score the
    moment it is decided (the void rule reads the decision), so its decision
    time is a change of the other items' numbers."""
    from datetime import datetime, timezone

    rows = [
        _row("s1", "A", True, at="2026-11-01T00:00:00+00:00"),
        _row("s1", "C", True, at="2026-11-02T00:00:00+00:00"),
        _row("s2", "A", False, at="2026-11-01T00:00:01+00:00"),
        _row("s2", "B", False, at="2026-11-02T00:00:01+00:00"),
    ]
    decided = datetime(2026, 11, 20, tzinfo=timezone.utc)
    stats = item_statistics(rows, retired={(COURSE, "C"): decided})
    a = stats[(COURSE, "A")]
    assert (COURSE, "C") not in stats and a["discrimination_n"] == 1  # s1 lost its only other item
    assert a["numbers_changed_at"] == decided.isoformat()
    # without a decision time (a plain set) the void rule still holds, with no time to report
    assert item_statistics(rows, retired={(COURSE, "C")})[(COURSE, "A")]["numbers_changed_at"] == (
        "2026-11-02T00:00:01+00:00"
    )


@pytest.mark.parametrize("students,right,out_of", [(37, 9, 10), (41, 1, 5), (35, 1, 3)])
def test_a_constant_rest_score_has_no_discrimination(students, right, out_of):
    """Every student's rest score is the same fraction: r is undefined, never
    float noise. A variance computed from a mean of 0.9 over 37 students is
    ~1e-32, not 0, and its "r" (≈ −5e-17) would have read as negative
    discrimination; over 41 students at 0.2, as low discrimination."""
    rows = []
    for i in range(students):
        rows.append(_row(f"s{i}", "K", i % 2 == 0))
        rows += [_row(f"s{i}", f"O{j}", j < right) for j in range(out_of)]
    k = item_statistics(rows)[(COURSE, "K")]
    assert k["discrimination"] is None and k["flags"] == []


# ── the flags ────────────────────────────────────────────────────────────────


def test_the_constants():
    assert params.ITEM_STATS_MIN_N == 30
    assert (params.ITEM_STATS_EASY_P, params.ITEM_STATS_HARD_P, params.ITEM_STATS_LOW_DISCRIMINATION) == (
        0.90, 0.20, 0.20,
    )
    assert params.ITEM_STATS_FLAGS == ("too_easy", "too_hard", "low_discrimination", "negative_discrimination")
    assert empty_stats()["flags"] == [] and empty_stats()["n"] == 0


def test_flags_need_their_own_minimum_n():
    n = params.ITEM_STATS_MIN_N
    assert flags_for(n, 0.95, n, -0.1) == ["too_easy", "negative_discrimination"]
    assert flags_for(n - 1, 0.95, n - 1, -0.1) == []
    assert flags_for(n, 0.10, n - 1, 0.05) == ["too_hard"]  # r has fewer students behind it
    assert flags_for(n - 1, 0.10, n, 0.05) == ["low_discrimination"]
    assert flags_for(n, 0.5, n, None) == []


def test_flag_boundaries_are_strict():
    n = params.ITEM_STATS_MIN_N
    assert flags_for(n, params.ITEM_STATS_EASY_P, n, 0.5) == []
    assert flags_for(n, params.ITEM_STATS_HARD_P, n, 0.5) == []
    assert flags_for(n, 0.5, n, params.ITEM_STATS_LOW_DISCRIMINATION) == []
    assert flags_for(n, 0.5, n, 0.0) == ["low_discrimination"]  # 0 ≤ r < 0.20
    assert flags_for(n, 0.5, n, -1e-9) == ["negative_discrimination"]


def test_thirty_students_flag_an_item_everyone_gets_right():
    n = params.ITEM_STATS_MIN_N
    rows = [_row(f"s{i}", "E", True) for i in range(n)]
    assert item_statistics(rows)[(COURSE, "E")]["flags"] == ["too_easy"]
    assert item_statistics(rows[:-1])[(COURSE, "E")]["flags"] == []


def test_a_miskeyed_item_shows_negative_discrimination():
    """The students who do well on the concept's other items get the item
    wrong, the weak ones right — what a wrong key looks like."""
    rows = []
    for i in range(params.ITEM_STATS_MIN_N):
        strong = i % 2 == 0
        rows += [
            _row(f"s{i}", "K", not strong),
            _row(f"s{i}", "O1", strong),
            _row(f"s{i}", "O2", strong or i % 3 == 0),
        ]
    k = item_statistics(rows)[(COURSE, "K")]
    assert k["discrimination"] < 0 and "negative_discrimination" in k["flags"]


# ── the route ────────────────────────────────────────────────────────────────

ADMIN = "/api/admin/check-items"


def _stored(item_id, qh, *, course=COURSE, flags=None, verified=False):
    return {
        "id": item_id, "course_id": course, "concept_key": "k1", "question_hash": qh,
        "format": "free", "difficulty": 2, "lint_flags": flags, "canonical_verified": verified,
    }


@pytest.fixture
def stats_client(monkeypatch):
    import routes.admin_check_items as admin

    monkeypatch.setattr(admin, "require_admin", lambda request: None)
    monkeypatch.setattr(admin.item_reports, "report_counts", lambda: {})
    monkeypatch.setattr(admin.item_reports, "reviews", lambda: {})
    monkeypatch.setattr(admin, "items_by_ids", lambda ids: [])
    writes = []
    monkeypatch.setattr(admin, "log_event", lambda *a, **k: writes.append(a))
    from main import app

    client = TestClient(app)
    client.writes = writes
    return client


def _many(item, n, *, correct):
    return [_row(f"u{i}", item, correct(i)) for i in range(n)]


def test_the_report_lists_every_stored_item_and_the_data_flagged_ones(stats_client, monkeypatch):
    import routes.admin_check_items as admin

    n = params.ITEM_STATS_MIN_N
    evidence = _many("easy", n, correct=lambda i: True) + _many("ok", n, correct=lambda i: i % 2 == 0)
    monkeypatch.setattr(admin, "_course_evidence", lambda c: (evidence, False))
    monkeypatch.setattr(
        admin,
        "course_item_rows",
        lambda c: [_stored("i-easy", "easy"), _stored("i-ok", "ok"), _stored("i-new", "new")],
    )
    body = stats_client.get(f"{ADMIN}/stats", params={"course_id": COURSE}).json()
    assert body["min_n"] == n and body["rows_scanned"] == 2 * n and body["truncated"] is False
    by_id = {i["id"]: i for i in body["items"]}
    assert by_id["i-easy"]["p_value"] == 1.0 and by_id["i-easy"]["flags"] == ["too_easy"]
    assert by_id["i-ok"]["flags"] == [] and by_id["i-new"]["n"] == 0  # no attempt yet
    (entry,) = body["flagged"]
    assert entry["id"] == "i-easy" and entry["stats"]["flags"] == ["too_easy"]
    assert entry["reports"]["total"] == 0 and entry["held"] is False and "prompt" in entry
    assert body["flagged_count"] == 1
    assert stats_client.writes == []  # read-only: no event, no decision, nothing stored


def test_an_approval_on_these_numbers_clears_the_data_flag_until_a_newer_attempt(stats_client, monkeypatch):
    import routes.admin_check_items as admin

    n = params.ITEM_STATS_MIN_N
    evidence = [_row(f"u{i}", "easy", True, at=f"2026-11-01T00:00:{i:02d}+00:00") for i in range(n)]
    monkeypatch.setattr(admin, "_course_evidence", lambda c: (evidence, False))
    monkeypatch.setattr(admin, "course_item_rows", lambda c: [_stored("i-easy", "easy")])

    def decided(at):
        monkeypatch.setattr(
            admin.item_reports,
            "reviews",
            lambda: {(COURSE, "easy"): {"status": "approved", "reviewed_at": at}},
        )
        return stats_client.get(f"{ADMIN}/stats", params={"course_id": COURSE}).json()

    assert decided("2026-11-02T00:00:00+00:00")["flagged"] == []  # approved after every attempt
    assert len(decided("2026-11-01T00:00:10+00:00")["flagged"]) == 1  # newer attempts since


def test_an_approval_before_the_concepts_newer_answers_does_not_hide_the_item(stats_client, monkeypatch):
    """Staff approved K on day 1; its own attempts are older, but the same
    students then answered the concept's other item, which turned K's
    discrimination negative — K is back in the flagged view."""
    import routes.admin_check_items as admin

    n = params.ITEM_STATS_MIN_N
    evidence = []
    for i in range(n):
        strong = i % 2 == 0
        evidence.append(_row(f"u{i}", "K", not strong, at="2026-11-01T00:00:00+00:00"))
        evidence.append(_row(f"u{i}", "O", strong, at="2026-11-03T00:00:00+00:00"))
    monkeypatch.setattr(admin, "_course_evidence", lambda c: (evidence, False))
    monkeypatch.setattr(admin, "course_item_rows", lambda c: [_stored("i-k", "K"), _stored("i-o", "O")])
    monkeypatch.setattr(
        admin.item_reports,
        "reviews",
        lambda: {(COURSE, "K"): {"status": "approved", "reviewed_at": "2026-11-02T00:00:00+00:00"}},
    )
    body = stats_client.get(f"{ADMIN}/stats", params={"course_id": COURSE}).json()
    k = next(e for e in body["flagged"] if e["id"] == "i-k")
    assert "negative_discrimination" in k["stats"]["flags"]
    assert k["stats"]["numbers_changed_at"] == "2026-11-03T00:00:00+00:00"


def test_the_route_voids_a_retired_items_attempts_and_dates_the_change(stats_client, monkeypatch):
    """The retired items come from the review decisions the route reads anyway
    (status 'retired', the void rule's key), with their decision time."""
    import routes.admin_check_items as admin

    evidence = [_row("s1", "A", True), _row("s1", "R", True), _row("s2", "A", False), _row("s2", "B", False)]
    monkeypatch.setattr(admin, "_course_evidence", lambda c: (evidence, False))
    monkeypatch.setattr(admin, "course_item_rows", lambda c: [_stored("i-a", "A")])
    monkeypatch.setattr(
        admin.item_reports,
        "reviews",
        lambda: {(COURSE, "R"): {"status": "retired", "reviewed_at": "2026-12-01T00:00:00+00:00"}},
    )
    (a,) = stats_client.get(f"{ADMIN}/stats", params={"course_id": COURSE}).json()["items"]
    assert a["discrimination_n"] == 1 and a["numbers_changed_at"] == "2026-12-01T00:00:00+00:00"


def test_held_and_retire_pending_items_lead_the_flagged_view(stats_client, monkeypatch):
    import routes.admin_check_items as admin

    n = params.ITEM_STATS_MIN_N
    evidence = _many("a", n, correct=lambda i: True) + _many("b", n, correct=lambda i: i % 10 == 0)
    monkeypatch.setattr(admin, "_course_evidence", lambda c: (evidence, False))
    monkeypatch.setattr(
        admin,
        "course_item_rows",
        lambda c: [_stored("i-a", "a"), _stored("i-b", "b"), _stored("i-c", "a2", flags=["key_disputed"])],
    )
    body = stats_client.get(f"{ADMIN}/stats", params={"course_id": COURSE}).json()
    # too_hard (b: p 0.1) is worse than too_easy (a: p 1.0); i-c has no attempts: not flagged by data
    assert [e["id"] for e in body["flagged"]] == ["i-b", "i-a"]


def test_a_failed_read_is_a_503(stats_client, monkeypatch):
    import routes.admin_check_items as admin

    def boom(_c):
        raise RuntimeError("db down")

    monkeypatch.setattr(admin, "course_item_rows", lambda c: [])
    monkeypatch.setattr(admin, "_course_evidence", boom)
    r = stats_client.get(f"{ADMIN}/stats", params={"course_id": COURSE})
    assert r.status_code == 503


def test_the_stats_endpoint_is_admin_only(monkeypatch):
    import routes.admin_check_items as admin

    def deny(request):
        raise HTTPException(status_code=403, detail="Admin access required")

    monkeypatch.setattr(admin, "require_admin", deny)
    touched = []
    monkeypatch.setattr(admin, "course_item_rows", lambda c: touched.append(c) or [])
    from main import app

    r = TestClient(app).get(f"{ADMIN}/stats", params={"course_id": COURSE})
    assert r.status_code == 403 and touched == []


def test_the_evidence_read_is_one_course_in_journal_order_and_capped(monkeypatch):
    import routes.admin_check_items as admin

    seen = {}

    class _Table:
        def __init__(self, name):
            seen["table"] = name

    def page_all(handle, columns, *, filters, order, **_kw):
        seen.update(columns=columns, filters=filters, order=order)
        yield from ({"id": f"r{i}"} for i in range(5))

    monkeypatch.setattr(admin, "table", _Table)
    monkeypatch.setattr(admin, "page_all", page_all)
    rows, truncated = admin._course_evidence(COURSE)
    assert len(rows) == 5 and truncated is False
    assert seen["table"] == "node_mastery_events"
    assert seen["filters"] == {
        "graph_nodes.course_id": f"eq.{COURSE}",
        "event_type": "eq.evidence",
        "check_item_id": "not.is.null",
    }
    assert seen["order"] == "created_at.asc,evidence_seq.asc.nullslast,id.asc"
    for column in ("same_session_recheck", "planning_recheck:planning_observation->same_session_recheck",
                   "graph_nodes!inner(user_id,course_id)", "weight", "confidence", "max_rung", "assisted"):
        assert column in seen["columns"]
    monkeypatch.setattr(admin, "STATS_SCAN_CAP", 3)
    rows, truncated = admin._course_evidence(COURSE)
    assert len(rows) == 3 and truncated is True


def test_review_entry_is_the_queue_entry_without_the_membership_rule():
    """queue_entries keeps its rule; the A131 view reads the same entry shape."""
    row = _stored("i1", "q1")
    entry = item_reports.review_entry(row, {}, {})
    assert entry["reports"]["total"] == 0 and entry["lint_flags"] == [] and not entry["held"]
    assert item_reports.queue_entries([row], {}, {}) == []  # nothing to review: not queued
