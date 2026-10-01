"""PKG-14 re-review fix round (owner 2026-09-29, spec §13 A88, narrowing A86's
scope): a served tutor turn is served UNCHANGED; its served text is scanned
against the student's OPEN, POSED items only — the active check item of an open
loop session, an open review item, an open post-test pose (an item turn's own
active item excluded: its leak check is the item turn's). Every stated item is
recorded in learning_reveals AT SERVE TIME (M2: no in-memory pending map, so no
path can lose it), is never selected again (A23) and grades with no unassisted
credit. Unreadable open items leave an 'unscanned' marker: every item posed at
or before it grades as assisted. A stream that ends without `done` still scans
what it relayed (M1)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from learning import params
from learning.checks import CheckItem, RubricItem, WrongReason
from learning.ladder import Rung
from services.chat_stream import SaplingEvent
from tests import test_learn_loop_routes as _routes
from tests.test_learn_loop_routes import client

gate_on, no_rate_limit, seams = _routes.gate_on, _routes.no_rate_limit, _routes.seams
POSED = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def _item(qh, final, *, concept="recursion", reference=None, course="c1"):
    return CheckItem(
        id=f"id-{qh}",
        course_id=course,
        concept_key=concept,
        format="free",
        difficulty=2,
        prompt="What does factorial(0) return?",
        reference_answer=reference or f"The answer is {final}.",
        final_answer=final,
        canonical_answer=None,
        rubric=[RubricItem(id="r1", text="a"), RubricItem(id="r2", text="b")],
        common_wrong=[WrongReason(key="w", text="wrong")],
        source_chunk_ids=["ch"],
        stepwise=False,
        question_hash=qh,
    )


BASE = _item("qh-base", "returns 1", reference="The base case returns 1 when n is 0.")
STACK = _item(
    "qh-stack", "the call stack", concept="stacks", reference="Frames sit on the call stack."
)
LEGACY = _item("qh-legacy", None)  # no final answer: not servable, skipped


# ── the scan (pure) ──────────────────────────────────────────────────────────


def test_stated_items_names_every_given_item_the_text_states():
    from routes.learn_loop import stated_items

    text = "Key idea: At n == 0 it returns 1.\n\nEach frame waits on the call stack.\n\nWhy?"
    assert stated_items(text, [BASE, STACK], rung=Rung.H0, given="") == ["qh-base", "qh-stack"]
    assert stated_items("A base case stops it.", [BASE, STACK], rung=Rung.H0, given="") == []


def test_a_non_servable_item_is_skipped_never_raises():
    from routes.learn_loop import stated_items

    assert stated_items("It returns 1.", [LEGACY, BASE], rung=Rung.H0, given="") == ["qh-base"]


def test_an_item_the_check_raises_on_counts_as_stated_fail_closed():
    from routes.learn_loop import stated_items

    with patch("routes.learn_loop.detect_leak", side_effect=ValueError("boom")):
        assert stated_items("anything", [BASE], rung=Rung.H0, given="") == ["qh-base"]


# ── posed_items (A93, owner decision 1): every POSED, ungraded item ─────────
# Supersedes A88's "open items only": an ended or closed session's ungraded steps,
# a probe's current item, an EXPIRED pose and the help ledger's 'posed' rows are
# scanned too; graded steps and items with evidence are not.


def _pages(sessions_loop, sessions_review):
    def _page_all(handle, columns, *, filters, order):
        return iter(sessions_review if filters.get("mode") == "eq.review" else sessions_loop)

    return _page_all


def test_posed_items_reads_every_posed_ungraded_source():
    from routes import learn_loop

    now = POSED + timedelta(hours=100)
    loop_rows = [
        {
            "id": "s1",
            "steps": {
                "qh-a": {"check_item_id": "id-a", "first_shown_at": 10.0},
                "qh-g": {"check_item_id": "id-g", "graded_at": 5.0},  # graded: out
            },
        },
        {  # an ENDED session: its ungraded, no-longer-current step is still posed
            "id": "s2",
            "steps": {"qh-e": {"check_item_id": "id-e", "first_shown_at": 12.0}},
            "probe": {"current": {"question_hash": "qh-probe"}},
        },
    ]
    review_rows = [
        {
            "id": "rv",
            "open": {
                "check:qh-r": {"item_id": "id-r", "served_at": 20.0},
                "fc:card-1": {"item_id": "card-1", "served_at": 20.0},  # a flashcard
                "check:qh-done": {"item_id": "id-done", "served_at": 1.0, "graded_at": 2.0},
            },
        }
    ]
    items = {"id-a": _item("qh-a", "x"), "id-r": _item("qh-r", "y"), "id-e": _item("qh-e", "e")}
    poses_tbl = MagicMock()
    poses_tbl.select.return_value = [
        {"course_id": "c1", "question_hash": "qh-p", "posed_at": POSED.isoformat()},  # expired: in
        {"course_id": "c9", "question_hash": "qh-q", "posed_at": POSED.isoformat()},
    ]
    by_hash = [
        _item("qh-p", "z"),
        _item("qh-q", "w", course="c1"),  # another course's item: never the c9 pose's
        _item("qh-probe", "pr"),
        _item("qh-ledger", "l"),
        _item("qh-seen", "s"),
    ]
    ledger = [("qh-ledger", POSED + timedelta(hours=1)), ("qh-seen", POSED)]
    with (
        patch("routes.learn_loop.page_all", side_effect=_pages(loop_rows, review_rows)),
        patch("routes.learn_loop.get_check_item", side_effect=lambda i: items.get(i)),
        patch("routes.learn_loop.table", return_value=poses_tbl),
        patch("routes.learn_loop.items_by_hash", return_value=by_hash) as ibh,
        patch("routes.learn_loop.ungraded_posed", return_value=ledger) as ug,
        patch("routes.learn_loop.seen_hashes", return_value={"qh-seen"}),
    ):
        got, overflow = learn_loop.posed_items("u1", now=now)
    assert {i.question_hash for i, _ in got} == {"qh-a", "qh-e", "qh-r", "qh-p", "qh-probe", "qh-ledger"}
    assert overflow is None
    assert ibh.call_args.args[0] == ["qh-ledger", "qh-p", "qh-probe", "qh-q"]
    assert ug.call_args.args[1] == params.LOOP_SCAN_POSED_MAX + 1
    filters = poses_tbl.select.call_args.kwargs["filters"]
    assert filters == {"user_id": "eq.u1", "answered_at": "is.null"}  # no TTL cut (A93)


def test_posed_items_beyond_the_window_report_the_overflow_edge(monkeypatch):
    from routes import learn_loop

    monkeypatch.setattr(params, "LOOP_SCAN_POSED_MAX", 2)
    monkeypatch.setattr(learn_loop, "LOOP_SCAN_POSED_MAX", 2)
    t = [POSED + timedelta(minutes=m) for m in range(3)]
    ledger = [("qh-2", t[2]), ("qh-1", t[1]), ("qh-0", t[0])]
    poses_tbl = MagicMock()
    poses_tbl.select.return_value = []
    with (
        patch("routes.learn_loop.page_all", side_effect=_pages([], [])),
        patch("routes.learn_loop.table", return_value=poses_tbl),
        patch("routes.learn_loop.items_by_hash", side_effect=lambda hs: [_item(h, h) for h in hs]),
        patch("routes.learn_loop.ungraded_posed", return_value=ledger),
        patch("routes.learn_loop.seen_hashes", return_value=set()),
    ):
        got, overflow = learn_loop.posed_items("u1", now=POSED)
    assert [i.question_hash for i, _ in got] == ["qh-2", "qh-1"]  # newest first, bounded
    assert overflow == t[0]  # the newest item left out: the marker's edge


def test_posed_items_is_none_when_anything_cannot_be_read(caplog):
    from routes import learn_loop

    with patch("routes.learn_loop.page_all", side_effect=RuntimeError("down")):
        assert learn_loop.posed_items("u1", now=POSED) is None
    assert "could not be read" in caplog.text


# ── served turns: scanned, recorded at serve time ────────────────────────────


def _chat(seams, body, *, state=None):
    seams.store["doc"] = state if state is not None else _routes._plan_state()
    agent, seen = _routes._json_agent(body)
    with (
        patch("routes.learn_loop.loop_tutor_agent", agent),
        patch("routes.learn_loop.record_agent_usage", side_effect=lambda r, **k: r),
    ):
        out = client.post(
            "/api/learn/loop/chat", json={"session_id": "s1", "user_id": "u1", "message": "explain"}
        ).json()
    return out, seen


def test_a_teach_turn_is_served_unchanged_and_the_stated_open_items_are_recorded(gate_on, seams):
    seams.open_posed.return_value = ([(BASE, POSED), (STACK, POSED)], None)
    out, seen = _chat(seams, "At n == 0 the base case returns 1.")
    assert "returns 1" in out["reply"] and out["leak_redacted"] is False
    seams.record_reveals.assert_called_once_with("u1", ["qh-base"], session_id="s1", source="teach")
    assert "revealed" not in seams.store["doc"]  # durable in learning_reveals: no fallback
    assert seen["kw"]["deps"].loop_leak is None  # never withheld or retried on this account
    seams.zpd.emit_zpd_leak.assert_not_called()
    (call,) = seams.zpd.emit_zpd_reveal.call_args_list
    assert call.kwargs["question_hashes"] == ["qh-base"] and call.kwargs["unscanned"] is False
    assert call.kwargs["phase"] == "teach" and call.kwargs["session_id"] == "s1"


def test_an_item_nobody_posed_is_never_scanned(gate_on, seams):
    """A88's scope: open posed items only — the course's other items are not
    read at all (the model never saw them: the precondition, HANDOFF-14)."""
    seams.open_posed.return_value = ([], None)
    _chat(seams, "At n == 0 the base case returns 1.")
    seams.record_reveals.assert_not_called()
    seams.zpd.emit_zpd_reveal.assert_not_called()


def test_a_clean_teach_turn_records_nothing(gate_on, seams):
    seams.open_posed.return_value = ([(BASE, POSED)], None)
    _chat(seams, "A base case stops the recursion.")
    seams.record_reveals.assert_not_called()
    seams.record_unscanned.assert_not_called()


def test_unreadable_open_items_serve_the_turn_and_record_an_unscanned_marker(gate_on, seams):
    seams.open_posed.return_value = None
    out, _ = _chat(seams, "At n == 0 it returns 1.")
    assert "returns 1" in out["reply"]
    (call,) = seams.record_unscanned.call_args_list
    assert call.args == ("u1",) and call.kwargs["session_id"] == "s1"
    assert call.kwargs["at"] == datetime.fromtimestamp(_routes.NOW, timezone.utc)
    assert seams.zpd.emit_zpd_reveal.call_args.kwargs["unscanned"] is True


def test_an_item_turn_is_scanned_against_the_other_open_items_not_its_own(gate_on, seams):
    """The active item's leak is the item turn's own check (redacted before it
    is served); every OTHER open item is scanned in the served text."""
    seams.open_posed.return_value = ([(_routes.ITEM, POSED), (STACK, POSED)], None)
    agent_p, usage_p, _ = _routes._feedback_agent("Right. And each frame sits on the call stack.")
    with agent_p, usage_p:
        r = client.post("/api/learn/loop/check/answer", json=_routes._answer(answer="returns 1"))
    assert r.status_code == 200, r.text
    seams.record_reveals.assert_called_once()
    assert seams.record_reveals.call_args.args[1] == ["qh-stack"]
    assert seams.record_reveals.call_args.kwargs["source"] == "feedback"


def test_a_failed_reveal_write_falls_back_to_loop_state_in_the_same_save(gate_on, seams):
    seams.open_posed.return_value = ([(BASE, POSED)], None)
    seams.record_reveals.side_effect = RuntimeError("down")
    _chat(seams, "At n == 0 the base case returns 1.")
    assert seams.store["doc"]["revealed"] == ["qh-base"]


def test_a_failed_marker_write_falls_back_to_a_loop_state_marker(gate_on, seams):
    seams.open_posed.return_value = None
    seams.record_unscanned.side_effect = RuntimeError("down")
    _chat(seams, "At n == 0 it returns 1.")
    (mark,) = seams.store["doc"]["reveal_unscanned"]
    assert mark["at"] == _routes.NOW


# ── the opener: no session row, recorded at serve time (M2) ─────────────────


def _open():
    agent, _ = _routes._json_agent("Welcome. At n == 0 the base case returns 1. Ready?")
    topic_p, offering_p, graph_p = _routes._opener_patches()
    with (
        patch("routes.learn_loop.loop_tutor_agent", agent),
        patch("routes.learn_loop.record_agent_usage", side_effect=lambda r, **k: r),
        topic_p,
        offering_p,
        graph_p,
    ):
        return client.post("/api/learn/loop/start-session", json={"user_id": "u1", "topic": "R"})


def test_the_openers_reveals_are_durable_before_the_session_row_exists(gate_on, seams):
    from routes import learn_loop

    seams.open_posed.return_value = ([(BASE, POSED)], None)
    r = _open()
    assert r.status_code == 200
    sid = r.json()["session_id"]
    seams.record_reveals.assert_called_once_with("u1", ["qh-base"], session_id=sid, source="teach")
    learn_loop.PENDING_SESSIONS.pop(sid, None)
    assert not hasattr(learn_loop, "_PENDING_REVEALS")  # no in-memory pending map at all
    assert not hasattr(learn_loop, "_consume_loop_pending")


def test_an_opener_whose_reveals_cannot_be_recorded_is_not_served(gate_on, seams):
    """No session row to fall back to: the opener fails (nothing served, no
    pending session) rather than serve a reveal it cannot record."""
    from routes import learn_loop

    seams.open_posed.return_value = ([(BASE, POSED)], None)
    seams.record_reveals.side_effect = RuntimeError("down")
    before = set(learn_loop.PENDING_SESSIONS)
    r = _open()
    assert r.status_code >= 500
    assert set(learn_loop.PENDING_SESSIONS) == before


def _store_tables(reveal_rows):
    """loop_state_store's reads: no evidence, no session lists, these
    learning_reveals rows."""

    class _T:
        def __init__(self, name="node_mastery_events"):
            self.name = name

        def select_with_count(self, columns="*", filters=None, **kw):
            rows = reveal_rows if self.name == "learning_reveals" else []
            return rows, len(rows)

        def select(self, columns="*", filters=None, **kw):
            return []

    return _T


@pytest.mark.parametrize(
    "path", ["reveal_floor", "posttest_excluded", "check_activation", "review_selection"]
)
def test_every_consumer_reads_the_persisted_reveal_with_nothing_consumed(path):
    """M2's loss paths — an end_session early return, /close, /review/*,
    /posttest/*, a restart — each had to consume an in-memory pending map
    first. Now nothing is pending: each reader sees the learning_reveals row
    directly, through loop_state_store.revealed_hashes."""
    from learning import loop_state_store, review
    from routes import learn_loop

    rows = [{"id": "r1", "question_hash": "qh-base"}]
    with (
        patch("learning.loop_state_store.table", _store_tables(rows)),
        patch("learning.loop_state_store._MasteryEventsRead", _store_tables([])),
    ):
        if path == "reveal_floor":
            with patch("routes.learn_loop.unscanned_since", return_value=False):
                assert learn_loop._reveal_floor("u1", BASE, POSED) == params.RUNG_NO_CREDIT_MIN
        elif path == "posttest_excluded":
            assert "qh-base" in learn_loop._posttest_excluded("u1")
        elif path == "check_activation":
            # _activate_next_item excludes revealed_hashes (its own route test)
            assert learn_loop.revealed_hashes is loop_state_store.revealed_hashes
            assert "qh-base" in learn_loop.revealed_hashes("u1")
        else:
            assert "qh-base" in review.revealed_hashes("u1")


# ── the grading floor ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "revealed,unscanned,expected",
    [
        (set(), False, 0),
        ({"qh-base"}, False, params.RUNG_NO_CREDIT_MIN),
        (set(), True, params.RUNG_ASSISTED_MIN),
    ],
)
def test_reveal_floor(revealed, unscanned, expected):
    from routes import learn_loop

    with (
        patch("routes.learn_loop.revealed_hashes", return_value=revealed),
        patch("routes.learn_loop.unscanned_since", return_value=unscanned) as since,
    ):
        assert learn_loop._reveal_floor("u1", BASE, POSED) == expected
    if not revealed:
        since.assert_called_once_with("u1", POSED)


def test_reveal_floor_fails_closed_when_a_read_fails():
    """A93 (minor 8): a failed read is NO credit (RUNG_NO_CREDIT_MIN), not
    merely assisted — the floor it could not read may have been H4–H6."""
    from routes import learn_loop

    with patch("routes.learn_loop.revealed_hashes", side_effect=RuntimeError("down")):
        assert learn_loop._reveal_floor("u1", BASE, POSED) == params.RUNG_NO_CREDIT_MIN
    with (
        patch("routes.learn_loop.revealed_hashes", return_value=set()),
        patch("routes.learn_loop.unscanned_since", side_effect=RuntimeError("down")),
    ):
        assert learn_loop._reveal_floor("u1", BASE, POSED) == params.RUNG_NO_CREDIT_MIN
    with patch("routes.learn_loop.max_help", side_effect=RuntimeError("down")):
        assert learn_loop._reveal_floor("u1", BASE, POSED) == params.RUNG_NO_CREDIT_MIN


def test_a_check_is_floored_from_when_it_was_first_shown(gate_on, seams):
    agent_p, usage_p, _ = _routes._feedback_agent()
    with (
        agent_p,
        usage_p,
        patch("routes.learn_loop._reveal_floor", return_value=params.RUNG_ASSISTED_MIN) as floor,
    ):
        r = client.post(
            "/api/learn/loop/check/answer", json=_routes._answer(answer="n == 0 returns 1")
        )
    assert r.status_code == 200
    assert seams.grade.call_args.kwargs["max_rung"] >= params.RUNG_ASSISTED_MIN
    assert floor.call_args.args[2] == datetime.fromtimestamp(_routes.T0, timezone.utc)


# ── M1: a stream that ends without `done` still scans what it relayed ────────


def _turn():
    turn = MagicMock()
    turn.tier, turn.paused = "standard", False
    turn.pre_events.return_value = []
    return turn


def _stream_with(events, *, then=None):
    async def fake(**kwargs):
        for ev in events:
            yield ev
        if then is not None:
            raise then

    return fake


def _tok(text):
    return SaplingEvent(type="token", step="reply", message="", data={"delta": text})


async def _drain(gen, *, stop_after=None):
    got = []
    try:
        async for chunk in gen:
            got.append(chunk)
            if stop_after is not None and len(got) >= stop_after:
                await gen.aclose()  # the client disconnected
                break
    except (RuntimeError, asyncio.CancelledError):
        pass
    return got


@pytest.mark.parametrize(
    "then,stop_after",
    [(RuntimeError("model died"), None), (asyncio.CancelledError(), None), (None, 1)],
    ids=["raises", "cancelled", "disconnected"],
)
def test_an_unfinished_stream_scans_and_records_the_relayed_text(then, stop_after):
    from routes import learn_loop

    turn = _turn()
    events = [_tok("At n == 0 "), _tok("it returns 1.")]
    with (
        patch("routes.learn_loop.ai_budget"),
        patch("routes.learn_loop.stream_structured_turn", _stream_with(events, then=then)),
    ):
        asyncio.run(_drain(learn_loop._stream_turn(turn), stop_after=stop_after))
    turn.touch_served_at.assert_called_once()  # A85: the anchor moves on a disconnect too
    # A93 (M3): scanned as it is relayed (the sentence end) AND at the end
    relayed = turn.record_relayed.call_args.args[0]
    assert relayed.startswith("At n == 0 ")
    if stop_after is None:
        assert relayed == "At n == 0 it returns 1."
        assert [c.args[0] for c in turn.record_relayed.call_args_list] == [
            "At n == 0 it returns 1.",  # mid-stream, before `done`
            "At n == 0 it returns 1.",  # the unfinished stream's final scan
        ]


def test_a_retract_discards_what_was_relayed_before_it():
    from routes import learn_loop

    turn = _turn()
    events = [_tok("old"), SaplingEvent(type="retract", step="reply", message=""), _tok("new")]
    with (
        patch("routes.learn_loop.ai_budget"),
        patch(
            "routes.learn_loop.stream_structured_turn", _stream_with(events, then=RuntimeError())
        ),
    ):
        asyncio.run(_drain(learn_loop._stream_turn(turn)))
    assert turn.record_relayed.call_args.args[0] == "new"


def test_a_finished_stream_is_scanned_once_by_complete_not_again():
    from routes import learn_loop

    turn = _turn()
    done = SaplingEvent(type="done", step="reply", message="Complete.", data={})
    with (
        patch("routes.learn_loop.ai_budget"),
        patch("routes.learn_loop.stream_structured_turn", _stream_with([_tok("x"), done])),
    ):
        asyncio.run(_drain(learn_loop._stream_turn(turn)))
    turn.record_relayed.assert_not_called()
    turn.touch_served_at.assert_not_called()


def test_persist_reveals_falls_back_to_loop_state_then_logs(caplog):
    from routes import learn_loop

    saved = {}

    def _update(sid, mutate):
        doc = {}
        mutate(doc)
        saved[sid] = doc
        return doc

    with (
        patch("routes.learn_loop.record_reveals", side_effect=RuntimeError("down")),
        patch("routes.learn_loop._update_loop_state", side_effect=_update),
    ):
        learn_loop._persist_reveals("u1", "s1", ["qh-base"], unscanned=False, source="x", at=POSED)
    assert saved["s1"]["revealed"] == ["qh-base"]
    with (
        patch("routes.learn_loop.record_unscanned", side_effect=RuntimeError("down")),
        patch("routes.learn_loop._update_loop_state", side_effect=_update),
    ):
        learn_loop._persist_reveals("u1", "s2", [], unscanned=True, source="x", at=POSED)
    assert saved["s2"]["reveal_unscanned"] == [{"at": POSED.timestamp(), "source": "x"}]
    with patch("routes.learn_loop.record_reveals", side_effect=RuntimeError("down")):
        learn_loop._persist_reveals("u1", None, ["qh-base"], unscanned=False, source="x", at=POSED)
    assert "LOST" in caplog.text


def _relay_turn(learn_loop):
    turn = MagicMock(spec=learn_loop._LoopTurn)
    turn.user_id, turn.session_id, turn.phase, turn.tier = "u1", "s1", "teach", "standard"
    turn.item, turn.given = None, ""
    turn.reveal_hashes, turn.reveal_unscanned = [], False
    turn._scan_served = lambda text: learn_loop._LoopTurn._scan_served(turn, text)
    return turn


def _real_relay_turn(learn_loop):
    turn = _relay_turn(learn_loop)
    turn._record_served = lambda: learn_loop._LoopTurn._record_served(turn)
    turn._scan_set = lambda: learn_loop._LoopTurn._scan_set(turn)
    turn.reveal_overflow, turn.reveal_fallback = None, None
    return turn


def test_record_relayed_scans_the_open_items_and_persists(gate_on, seams):
    from routes import learn_loop

    turn = _real_relay_turn(learn_loop)
    seams.open_posed.return_value = ([(BASE, POSED)], None)
    with (
        patch("routes.learn_loop.record_reveals") as rec,
        patch("routes.learn_loop._persist_reveals") as persist,
    ):
        learn_loop._LoopTurn.record_relayed(turn, "At n == 0 it returns 1.")
        learn_loop._LoopTurn.record_relayed(turn, "At n == 0 it returns 1. More.")
    (call,) = rec.call_args_list  # A93: recorded once per turn, however often scanned
    assert call.args[:2] == ("u1", ["qh-base"]) and call.kwargs["session_id"] == "s1"
    persist.assert_not_called()  # the primary store worked: no fallback
    assert seams.open_posed.call_count == 1  # the scan set is read once per turn


def test_record_relayed_falls_back_to_loop_state_when_the_store_fails(gate_on, seams):
    from routes import learn_loop

    turn = _real_relay_turn(learn_loop)
    seams.open_posed.return_value = ([(BASE, POSED)], None)
    with (
        patch("routes.learn_loop.record_reveals", side_effect=RuntimeError("down")),
        patch("routes.learn_loop._persist_reveals") as persist,
    ):
        learn_loop._LoopTurn.record_relayed(turn, "At n == 0 it returns 1.")
    (call,) = persist.call_args_list
    assert call.args[:3] == ("u1", "s1", ["qh-base"]) and call.kwargs["source"] == "teach:relayed"
    turn._emit_reveal.assert_called_once()


def test_record_relayed_never_raises(gate_on, seams, caplog):
    from routes import learn_loop

    turn = _relay_turn(learn_loop)
    seams.open_posed.side_effect = RuntimeError("boom")
    learn_loop._LoopTurn.record_relayed(turn, "text")
    assert "could not be scanned" in caplog.text


# ── the store ────────────────────────────────────────────────────────────────


def test_record_reveals_and_unscanned_insert_hash_only_rows():
    from learning import reveal_store

    handle = MagicMock()
    with patch("learning.reveal_store.table", return_value=handle):
        reveal_store.record_reveals("u1", ["b", "a", "a"], session_id="s1", source="teach")
        reveal_store.record_reveals("u1", [], session_id="s1", source="teach")
        reveal_store.record_unscanned("u1", session_id=None, source="teach", at=POSED)
    first, second = handle.insert.call_args_list
    assert [r["question_hash"] for r in first.args[0]] == ["a", "b"]
    assert {r["kind"] for r in first.args[0]} == {"reveal"}
    assert second.args[0] == {
        "user_id": "u1",
        "kind": "unscanned",
        "question_hash": None,
        "session_id": None,
        "source": "teach",
        "at": POSED.isoformat(),
    }


def test_unscanned_since_reads_markers_at_or_after_the_pose_in_both_stores():
    from learning import reveal_store

    handle = MagicMock()
    handle.select.return_value = []
    with (
        patch("learning.reveal_store.table", return_value=handle),
        patch(
            "learning.reveal_store.unscanned_reveals",
            return_value=[("s1", {"at": POSED.timestamp() - 1}), ("s2", {"at": "junk"})],
        ),
    ):
        assert reveal_store.unscanned_since("u1", POSED) is False  # before the pose
        assert handle.select.call_args.kwargs["filters"]["at"] == f"gte.{POSED.isoformat()}"
        assert reveal_store.unscanned_since("u1", POSED - timedelta(seconds=5)) is True
        assert reveal_store.unscanned_since("u1", None) is True  # unknown pose: any marker
    handle.select.return_value = [{"id": "m"}]
    with patch("learning.reveal_store.table", return_value=handle):
        assert reveal_store.unscanned_since("u1", POSED) is True


def test_revealed_hashes_includes_learning_reveals_rows():
    from learning import loop_state_store

    with (
        patch(
            "learning.loop_state_store.table", _store_tables([{"id": "r", "question_hash": "q"}])
        ),
        patch("learning.loop_state_store._MasteryEventsRead", _store_tables([])),
    ):
        assert loop_state_store.revealed_hashes("u1") == {"q"}


def test_items_by_hash_batches_the_in_filter():
    from services import check_item_service

    handle = MagicMock()
    handle.select.return_value = []
    hashes = [f"h{i:03d}" for i in range(check_item_service._HASH_BATCH + 1)]
    with patch("services.check_item_service.table", return_value=handle):
        assert check_item_service.items_by_hash(hashes + [None, "h000"]) == []
    assert handle.select.call_count == 2
    assert handle.select.call_args_list[1].kwargs["filters"] == {
        "question_hash": f"in.({check_item_service.pg_quote_value(hashes[-1])})"
    }


def test_the_reveal_event_is_in_the_taxonomy_and_plain():
    from learning import zpd_events
    from services import events_service

    assert "zpd.reveal" in events_service.EVENT_TAXONOMY
    assert "zpd.teach_reveal" not in events_service.EVENT_TAXONOMY
    captured = []
    with patch.object(
        zpd_events, "log_event", lambda et, **kw: captured.append((et, kw["payload"]))
    ):
        zpd_events.emit_zpd_reveal(
            user_id="u1",
            request_id="r",
            session_id="s1",
            question_hashes=["qh-base"],
            unscanned=False,
            phase="teach",
        )
    assert captured == [
        (
            "zpd.reveal",
            {
                "question_hashes": ["qh-base"],
                "count": 1,
                "unscanned": False,
                "phase": "teach",
                "session_id": "s1",
            },
        )
    ]


def test_unscanned_reveals_reads_every_sessions_fallback_markers():
    from learning import reveal_store

    handle = MagicMock()
    handle.select_with_count.return_value = (
        [{"id": "s1", "marks": [{"at": 1.0}, "junk"]}, {"id": "s2", "marks": None}],
        2,
    )
    with patch("learning.reveal_store.table", return_value=handle):
        assert reveal_store.unscanned_reveals("u1") == [("s1", {"at": 1.0})]
    assert handle.select_with_count.call_args.kwargs["filters"]["user_id"] == "eq.u1"


def test_the_reveals_migration_is_backend_only_and_hash_only():
    import pathlib

    sql = (
        pathlib.Path(__file__).resolve().parents[1]
        / "db/migrations/20260930031644_learning_reveals.sql"
    ).read_text()
    assert "ENABLE ROW LEVEL SECURITY" in sql and "REVOKE ALL ON TABLE learning_reveals" in sql
    assert "CHECK ((kind = 'reveal') = (question_hash IS NOT NULL))" in sql
    body = sql.split("CREATE TABLE", 1)[1].split(");", 1)[0]
    assert "text " in body and "prompt" not in body and "content" not in body
