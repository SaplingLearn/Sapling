"""PKG-14 review fix round, owner decision 1 (spec §13 A93): the per-student HELP
LEDGER. Every unit of help on (student, item) is recorded as it is served; every
grade's floor is the MAX help ever recorded for that pair, across sessions and
surfaces, re-read inside the grading claim right before the one evidence write.

The critical finding this closes (hint laundering): the same check item open in
two loop sessions (or a loop session and review) — H6 in session A, then an
unassisted grade in session B."""

from __future__ import annotations

from collections import defaultdict
from unittest.mock import MagicMock, patch

import pytest

from learning import params
from learning.checks import CheckItem
from learning.ladder import Rung
from tests import test_learn_loop_routes as _routes
from tests import test_learning_probe_planner as _probe
from tests import test_learning_posttest as _post
from tests.test_learn_loop_routes import client

gate_on, no_rate_limit, seams = _routes.gate_on, _routes.no_rate_limit, _routes.seams
probe, _no_rate_limit = _probe.probe, _probe._no_rate_limit
one_item, grader_says, applied, tables, freeze_now = (
    _post.one_item,
    _post.grader_says,
    _post.applied,
    _post.tables,
    _post.freeze_now,
)
seen_revealed, grader_calls = _post.seen_revealed, _post.grader_calls


# ── the store (learning/help_ledger.py) ─────────────────────────────────────


def test_record_help_and_posed_insert_hash_and_rung_rows_only():
    from learning import help_ledger

    handle = MagicMock()
    with patch("learning.help_ledger.table", return_value=handle):
        help_ledger.record_help("u1", "qh", 6, source="loop", session_id="s1")
        help_ledger.record_help("u1", "qh", 0, source="loop")  # H0 is no help: no row
        help_ledger.record_posed("u1", "qh", source="probe", session_id="s2")
    (help_row,), (posed_row,) = (c.args for c in handle.insert.call_args_list)
    assert {k: help_row[k] for k in ("user_id", "kind", "question_hash", "rung", "session_id", "source")} == {
        "user_id": "u1", "kind": "help", "question_hash": "qh", "rung": 6, "session_id": "s1", "source": "loop",
    }
    assert posed_row["kind"] == "posed" and "rung" not in posed_row and posed_row["source"] == "probe"
    # "quiz": the quiz-ask session's help row (spec §13 A99, services/quiz_ask.py)
    assert set(help_ledger.SOURCES) == {"loop", "review", "posttest", "probe", "scan", "quiz"}


def test_max_help_is_the_highest_rung_and_a_reveal_counts_as_no_credit():
    from learning import help_ledger

    handle = MagicMock()
    handle.select.return_value = [
        {"kind": "help", "rung": 2},
        {"kind": "help", "rung": 3},
        {"kind": "reveal", "rung": None},
    ]
    with patch("learning.help_ledger.table", return_value=handle):
        assert help_ledger.max_help("u1", "qh") == params.RUNG_NO_CREDIT_MIN
        handle.select.return_value = [{"kind": "help", "rung": 5}, {"kind": "reveal", "rung": None}]
        assert help_ledger.max_help("u1", "qh") == 5
        handle.select.return_value = []
        assert help_ledger.max_help("u1", "qh") == 0
    filters = handle.select.call_args.kwargs["filters"]
    assert filters == {"user_id": "eq.u1", "question_hash": "eq.qh", "kind": "in.(help,reveal)"}


def test_ungraded_posed_is_distinct_newest_first_and_bounded():
    from learning import help_ledger

    handle = MagicMock()
    handle.select.return_value = [
        {"question_hash": "c", "at": "2026-09-30T03:00:00Z"},
        {"question_hash": "b", "at": "2026-09-30T02:00:00Z"},
        {"question_hash": "c", "at": "2026-09-30T01:00:00Z"},  # c first posed earlier
        {"question_hash": "a", "at": "2026-09-30T00:00:00Z"},
    ]
    with patch("learning.help_ledger.table", return_value=handle):
        got = help_ledger.ungraded_posed("u1", 2)
    assert [h for h, _ in got] == ["c", "b"]
    assert got[0][1].hour == 1  # the item's FIRST ungraded pose
    kw = handle.select.call_args.kwargs
    assert kw["filters"] == {"user_id": "eq.u1", "kind": "eq.posed", "graded_at": "is.null"}
    assert kw["order"] == "at.desc"


def test_mark_graded_closes_only_the_items_ungraded_posed_rows():
    from learning import help_ledger

    handle = MagicMock()
    with patch("learning.help_ledger.table", return_value=handle):
        help_ledger.mark_graded("u1", "qh")
    (data,), kw = handle.update.call_args
    assert set(data) == {"graded_at"}
    assert kw["filters"] == {
        "user_id": "eq.u1", "kind": "eq.posed", "question_hash": "eq.qh", "graded_at": "is.null",
    }


# ── the floor: max help across sessions and surfaces ────────────────────────


@pytest.fixture
def ledger(monkeypatch):
    """An in-memory help ledger at the route seam: (user, hash) → rungs."""
    import routes.learn_loop as ll

    rows: dict = defaultdict(list)
    monkeypatch.setattr(ll, "record_help", lambda u, h, r, **kw: rows[(u, h)].append(int(r)))
    monkeypatch.setattr(ll, "max_help", lambda u, h: max(rows[(u, h)], default=0))
    monkeypatch.setattr(ll, "earliest_open_pose", lambda u, h: None)
    monkeypatch.setattr(ll, "revealed_hashes", lambda u: set())
    monkeypatch.setattr(ll, "unscanned_since", lambda u, p: False)
    return rows


def _item(i, qh, fmt="free", d=2):
    return CheckItem(
        id=f"id{i}", course_id="c1", concept_key="k", format=fmt, difficulty=d,
        prompt=f"What is {i}?", reference_answer=f"answer {i} is 4{i}",
        rubric=[], common_wrong=[], source_chunk_ids=[], question_hash=qh,
        final_answer=f"4{i}", created_at=f"2026-01-0{i}",
    )


ITEMS = [_item(1, "a" * 64), _item(2, "b" * 64), _item(3, "c" * 64), _item(4, "d" * 64, "mc_reason")]


def _hint_turn(ll, item, rung, *, h6=False, sibling=None, paused=False):
    turn = MagicMock(spec=ll._LoopTurn)
    turn.user_id, turn.session_id, turn.phase, turn.item = "u", "sA", "hint", item
    turn.rung, turn.served_as_h6, turn.revealed_hash, turn.paused = rung, h6, sibling, paused
    turn.text, turn.tier = "payload", "none"
    return turn


def test_an_h6_in_session_a_floors_the_same_item_graded_in_session_b(monkeypatch, ledger):
    """The critical finding, as a real test (the adversarial reviewer's scratch case):
    the SAME item is active in two open sessions; H6 in A is recorded on the
    student, so B's grade of it carries no unassisted credit."""
    import routes.learn_loop as ll

    monkeypatch.setattr(ll, "seen_hashes", lambda u: set())
    monkeypatch.setattr(ll, "_concept_key_for_node", lambda u, n: "k")
    monkeypatch.setattr(ll, "list_items", lambda c, k: list(ITEMS))
    monkeypatch.setattr(ll, "_band_for", lambda u, n: ("develop", 0.5))
    a, b = {"concept": "n1", "teach_turns": 2}, {"concept": "n1", "teach_turns": 2}
    qa = ll._activate_next_item("u", "c1", a, now=1.0)
    qb = ll._activate_next_item("u", "c1", b, now=2.0)
    assert qa == qb  # the same item is open in both sessions
    item = next(i for i in ITEMS if i.question_hash == qa)
    assert ll._reveal_floor("u", item, None) == 0  # before any help
    ll._LoopTurn._record_planned_help(_hint_turn(ll, item, Rung.H6))  # the H6 payload, in A
    assert ll._reveal_floor("u", item, None) == int(Rung.H6)  # B's grade: no credit
    assert ll._reveal_floor("u", item, None) >= params.RUNG_NO_CREDIT_MIN


def test_a_lower_hint_elsewhere_floors_the_grade_as_assisted(ledger):
    import routes.learn_loop as ll

    item = ITEMS[0]
    ll._LoopTurn._record_planned_help(_hint_turn(ll, item, Rung.H2))
    assert ll._reveal_floor("u", item, None) == int(Rung.H2)


def test_an_h4_sibling_payload_is_help_on_the_sibling_and_a_paused_turn_is_none(ledger):
    import routes.learn_loop as ll

    item, sibling = ITEMS[0], ITEMS[1]
    ll._LoopTurn._record_planned_help(_hint_turn(ll, item, Rung.H4, sibling=sibling.question_hash))
    assert ledger[("u", item.question_hash)] == [int(Rung.H4)]
    assert ledger[("u", sibling.question_hash)] == [params.RUNG_NO_CREDIT_MIN]
    ll._LoopTurn._record_planned_help(_hint_turn(ll, ITEMS[2], Rung.H3, paused=True))
    assert ledger[("u", ITEMS[2].question_hash)] == []  # nothing was served


def test_a_leaking_payload_served_as_h6_is_recorded_as_h6(ledger):
    import routes.learn_loop as ll

    ll._LoopTurn._record_planned_help(_hint_turn(ll, ITEMS[0], Rung.H4, h6=True))
    assert ledger[("u", ITEMS[0].question_hash)] == [int(Rung.H6)]


def test_the_floor_reads_the_first_ungraded_pose_for_the_unscanned_rule(monkeypatch, ledger):
    """An item first posed long ago and re-posed today: a marker between the two
    still floors it (the earliest ungraded pose anchors the rule)."""
    import routes.learn_loop as ll
    from datetime import datetime, timezone

    first = datetime(2026, 9, 1, tzinfo=timezone.utc)
    today = datetime(2026, 9, 30, tzinfo=timezone.utc)
    seen = {}
    monkeypatch.setattr(ll, "earliest_open_pose", lambda u, h: first)
    monkeypatch.setattr(ll, "unscanned_since", lambda u, p: seen.setdefault("anchor", p) <= first)
    assert ll._reveal_floor("u", ITEMS[0], today) == params.RUNG_ASSISTED_MIN
    assert seen["anchor"] == first


def test_refloor_raises_the_pending_evidence_of_the_item_only(monkeypatch):
    import routes.learn_loop as ll

    monkeypatch.setattr(ll, "_reveal_floor", lambda u, i, p: 4)
    rows = [
        {"question_hash": ITEMS[0].question_hash, "max_rung": 0, "assisted": False},
        {"question_hash": "other", "max_rung": 0, "assisted": False},
    ]
    assert ll._refloor(rows, "u", ITEMS[0], None, 1) == 4
    assert rows[0] == {"question_hash": ITEMS[0].question_hash, "max_rung": 4, "assisted": True}
    assert rows[1]["max_rung"] == 0
    monkeypatch.setattr(ll, "_reveal_floor", lambda u, i, p: 0)
    assert ll._refloor(rows, "u", ITEMS[0], None, 2) == 2  # never lowers


# ── wiring: every surface records, every grade re-reads inside its claim ────


def test_the_hint_route_records_the_granted_rung(gate_on, seams):
    seams.store["doc"] = _routes._state(offered=True, attempted_at=[_routes.T0 + 10])
    with patch("routes.learn_loop.record_help") as rec:
        r = _routes.client.post("/api/learn/loop/hint", json=_routes._hint())
    assert r.json()["rung"] == 2
    rec.assert_called_once()
    assert rec.call_args.args == ("u1", "qh-1", 2)
    assert rec.call_args.kwargs == {"source": "loop", "session_id": "s1"}


def _grade_appends(seams, rung_seen: list):
    async def grade(item, answer, *, deps, node_id, max_rung=0, **kw):
        rung_seen.append(max_rung)
        deps.pending_evidence.append(
            {"question_hash": answer.question_hash, "max_rung": max_rung, "assisted": max_rung > 0}
        )
        return _routes.CORRECT

    seams.grade.side_effect = grade


def test_the_check_route_rereads_the_floor_inside_the_claim_before_the_write(gate_on, seams):
    """A93 (M3): help recorded WHILE the grade ran (a hint in another session, a
    reveal streaming meanwhile) is seen: the floor is read again right before the
    flush, and the pending Evidence carries it."""
    seams.store["doc"] = _routes._state(attempted_at=[_routes.T0 + 10])
    rung_seen: list = []
    _grade_appends(seams, rung_seen)
    written: list = []
    seams.flush.side_effect = lambda deps, course: written.append([dict(e) for e in deps.pending_evidence]) or []
    agent_p, usage_p, _ = _routes._feedback_agent()
    with (
        agent_p,
        usage_p,
        patch("routes.learn_loop._reveal_floor", side_effect=[0, params.RUNG_NO_CREDIT_MIN]),
        patch("routes.learn_loop.mark_graded") as graded,
    ):
        r = client.post("/api/learn/loop/check/answer", json=_routes._answer(answer="n == 0 returns 1"))
    assert r.status_code == 200, r.text
    assert rung_seen and rung_seen[0] < params.RUNG_NO_CREDIT_MIN  # graded with what was known …
    ((ev,),) = written  # … written with what is known right before the write
    assert ev["max_rung"] == params.RUNG_NO_CREDIT_MIN and ev["assisted"] is True
    graded.assert_called_once_with("u1", "qh-1")


def test_the_probe_grades_with_the_help_floor_and_rereads_it(probe):
    """M2: probe submissions had max_rung=0 and no floor."""
    _probe._answer_doc(probe)
    with (
        patch("routes.learn_loop._reveal_floor", side_effect=[int(Rung.H2), params.RUNG_NO_CREDIT_MIN]),
        patch("routes.learn_loop.mark_graded") as graded,
    ):
        r = client.post(f"{_probe.LOOP}/probe/answer", json=_probe._answer(answer="because"))
    assert r.status_code == 200, r.text
    assert probe.grade.await_args.kwargs["max_rung"] == int(Rung.H2)
    (ev,) = probe.agu.call_args.args[1]["evidence"]
    assert ev["max_rung"] == params.RUNG_NO_CREDIT_MIN
    graded.assert_called_once()


def test_probe_next_records_a_newly_posed_item_once(probe):
    with patch("routes.learn_loop.record_posed") as posed:
        first = client.post(f"{_probe.LOOP}/probe/next", json=_probe.NEXT).json()
        again = client.post(f"{_probe.LOOP}/probe/next", json=_probe.NEXT).json()
    assert first["question_hash"] == again["question_hash"]  # served again until answered
    posed.assert_called_once()
    assert posed.call_args.args == (_probe.UID, first["question_hash"])
    assert posed.call_args.kwargs["source"] == "probe"


def test_the_posttest_rereads_the_floor_inside_the_claim(gate_on, one_item, grader_says, applied):
    grader_says(correct=True, confidence=0.9)
    with (
        patch("routes.learn_loop._reveal_floor", side_effect=[0, params.RUNG_NO_CREDIT_MIN]),
        patch("routes.learn_loop.mark_graded") as graded,
    ):
        r = client.post(_post.ANSWER, json=_post._answer(answer="a function with its lexical scope"))
    assert r.status_code == 200, r.text
    (call,) = applied
    (ev,) = call["graph_update"]["evidence"]
    assert ev["max_rung"] == params.RUNG_NO_CREDIT_MIN and ev["assisted"] is True
    graded.assert_called_once()


def test_an_expired_pose_keeps_its_item_bound_to_the_node(gate_on, one_item):
    """A93 (minor 6): letting a pose expire never buys a fresh item — the re-pose
    renews the SAME item (a new posed_at); only an answer frees the node."""
    from datetime import timedelta

    one_item["check_items"] = [_post.item("k1", "q1"), _post.item("k1", "q2")]
    _post._pose(
        one_item, qh="q2", posed=_post.NOW - timedelta(hours=params.POSTTEST_POSE_TTL_HOURS + 1)
    )
    with patch("routes.learn_loop.record_posed") as posed:
        items = client.post(_post.START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert [i["question_hash"] for i in items] == ["q2"]
    pose = one_item["poses"][("u", "n1")]
    assert pose["question_hash"] == "q2" and pose["posed_at"] == _post.NOW.isoformat()
    posed.assert_called_once_with("u", "q2", source="posttest")


def test_a_retracted_attempt_is_scanned_too():
    """A93 (M4): a retract no longer forgets what the student already saw."""
    import asyncio

    import routes.learn_loop as ll
    from tests import test_learning_teach_reveal as _tr

    turn = _tr._turn()
    events = [_tr._tok("old text"), _tr.SaplingEvent(type="retract", step="reply", message=""), _tr._tok("new")]
    with (
        patch("routes.learn_loop.ai_budget"),
        patch("routes.learn_loop.stream_structured_turn", _tr._stream_with(events, then=RuntimeError())),
    ):
        asyncio.run(_tr._drain(ll._stream_turn(turn)))
    scanned = [c.args[0] for c in turn.record_relayed.call_args_list]
    assert "old text" in scanned and scanned[-1] == "new"


from tests import test_learning_review as _rv  # noqa: E402

store = _rv.store


def test_grade_review_applies_the_refloor_right_before_its_one_write(monkeypatch, store):
    """A93: review's grade takes the route's help-floor re-read as a callback,
    applied to the Evidence right before grade_review's one apply_graph_update."""
    import inspect

    from learning import review
    import routes.learn_loop as ll

    grade, _calls = _rv._grade(correct=True)
    monkeypatch.setattr(review, "grade_answer", grade)
    order: list = []
    monkeypatch.setattr(
        review,
        "apply_graph_update",
        lambda uid, gu, course_id=None, **kw: order.append(("write", dict(gu["evidence"][0]))) or [],
    )
    factory, _handles = _rv._tables({"learner_state": []})
    monkeypatch.setattr(review, "table", factory)
    monkeypatch.setattr(review, "log_event", lambda et, **kw: None)
    item = _rv._item("check", 0.4, id="ci-qh-1", node_id="n-due", question_hash="qh-1", format="free", difficulty=3)
    loop_state = {
        "sr": {"n-due": {"correct": 0, "target": params.SR_INITIAL_CRITERION, "served": 1}},
        "review": {"spent_s": 0, "retention": params.FSRS_RETENTION_DEFAULT},
    }

    def refloor(ev):
        order.append(("refloor", ev.get("max_rung")))
        ev["max_rung"], ev["assisted"] = params.RUNG_NO_CREDIT_MIN, True

    _rv._grade_check(item, _rv._check_item("n-due", "qh-1"), loop_state, answer="x", refloor=refloor)
    assert [k for k, _ in order] == ["refloor", "write"]
    assert order[1][1]["max_rung"] == params.RUNG_NO_CREDIT_MIN
    route = inspect.getsource(ll.review_answer)
    assert "refloor=" in route and "_refloor(" in route and "mark_graded" in route
