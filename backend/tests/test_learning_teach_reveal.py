"""PKG-14 review fix round (owner decision 2026-09-29, spec §13 A86): a teach
turn is served UNCHANGED; the served text is scanned against the student's
course check items, and every item whose answer it states is MARKED REVEALED
through the A23 revealed-hashes machinery (loop_state["revealed"]) — never
selected as a check or a post-test item, and graded with no unassisted credit
if it was already posed. Unreadable items leave a marker that fails closed on
the evidence side until it is resolved."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from learning import params
from learning.checks import CheckItem, RubricItem, WrongReason
from learning.ladder import Rung
from tests import test_learn_loop_routes as _routes
from tests.test_learn_loop_routes import client

gate_on, no_rate_limit, seams = _routes.gate_on, _routes.no_rate_limit, _routes.seams


def _item(qh, final, *, concept="recursion", reference=None):
    return CheckItem(
        id=f"id-{qh}",
        course_id="c1",
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


def test_teach_reveals_names_every_course_item_the_text_states():
    from routes.learn_loop import teach_reveals

    text = "Key idea: At n == 0 it returns 1.\n\nEach frame waits on the call stack.\n\nWhy?"
    assert teach_reveals(text, [BASE, STACK], rung=Rung.H3, given="") == ["qh-base", "qh-stack"]
    assert teach_reveals("A base case stops it.", [BASE, STACK], rung=Rung.H3, given="") == []


def test_a_non_servable_item_is_skipped_never_raises():
    from routes.learn_loop import teach_reveals

    assert teach_reveals("It returns 1.", [LEGACY, BASE], rung=Rung.H3, given="") == ["qh-base"]


def test_an_item_the_check_raises_on_is_marked_revealed_fail_closed():
    from routes.learn_loop import teach_reveals

    with patch("routes.learn_loop.detect_leak", side_effect=ValueError("boom")):
        assert teach_reveals("anything", [BASE], rung=Rung.H3, given="") == ["qh-base"]


# ── the route: served unchanged, marked revealed ─────────────────────────────


def _teach(seams, body, *, items=None, items_error=None):
    seams.store["doc"] = _routes._plan_state()
    reader = (
        MagicMock(side_effect=items_error) if items_error else MagicMock(return_value=items or [])
    )
    agent, seen = _routes._json_agent(body)
    with (
        patch("routes.learn_loop.items_for_course", reader),
        patch("routes.learn_loop.loop_tutor_agent", agent),
        patch("routes.learn_loop.record_agent_usage", side_effect=lambda r, **k: r),
    ):
        out = client.post(
            "/api/learn/loop/chat", json={"session_id": "s1", "user_id": "u1", "message": "explain"}
        ).json()
    return out, reader, seen


def test_a_teach_turn_is_served_unchanged_and_the_stated_items_are_marked_revealed(gate_on, seams):
    out, reader, seen = _teach(seams, "At n == 0 the base case returns 1.", items=[BASE, STACK])
    assert "returns 1" in out["reply"] and out["leak_redacted"] is False
    reader.assert_called_once_with("c1")  # the student's course: every concept, the reserve too
    assert seams.store["doc"]["revealed"] == ["qh-base"]
    assert seen["kw"]["deps"].loop_leak is None  # no retry on account of item answers
    seams.zpd.emit_zpd_leak.assert_not_called()  # zero-leaks counts item turns only
    (call,) = seams.zpd.emit_zpd_teach_reveal.call_args_list
    assert call.kwargs["question_hashes"] == ["qh-base"] and call.kwargs["unscanned"] is False


def test_a_clean_teach_turn_marks_nothing(gate_on, seams):
    out, _, _ = _teach(seams, "A base case stops the recursion.", items=[BASE])
    assert "revealed" not in seams.store["doc"]
    seams.zpd.emit_zpd_teach_reveal.assert_not_called()


def test_unreadable_items_serve_the_turn_and_leave_a_fail_closed_marker(gate_on, seams, caplog):
    out, _, _ = _teach(seams, "At n == 0 it returns 1.", items_error=RuntimeError("down"))
    assert "returns 1" in out["reply"]
    (mark,) = seams.store["doc"]["reveal_unscanned"]
    assert mark["course_id"] == "c1" and mark["at"] == _routes.NOW and "id" in mark
    assert "could not be read" in caplog.text
    assert seams.zpd.emit_zpd_teach_reveal.call_args.kwargs["unscanned"] is True


def test_a_streamed_teach_turn_is_never_cut(gate_on, seams):
    seams.store["doc"] = _routes._plan_state()
    reply = "Key idea: Recursion needs a stop.\n\nThe base case returns 1 there.\n\nWhy?"
    with (
        patch("routes.learn_loop.items_for_course", return_value=[BASE]),
        patch("routes.learn_loop.stream_structured_turn", _routes._fake_stream(reply)),
    ):
        r = client.post(
            "/api/learn/loop/chat/stream",
            json={"session_id": "s1", "user_id": "u1", "message": "go"},
        )
    evs = _routes._sse_events(r.text)
    tokens = "".join(e["data"]["delta"] for e in evs if e["type"] == "token")
    assert "returns 1" in tokens and not [e for e in evs if e["type"] == "retract"]
    assert seams.store["doc"]["revealed"] == ["qh-base"]


# ── the grading floor: an already-posed item that got revealed ───────────────


@pytest.mark.parametrize(
    "revealed,markers,expected",
    [
        (set(), [], 0),
        ({"qh-base"}, [], params.RUNG_NO_CREDIT_MIN),
        (set(), [("s9", {"id": "m", "course_id": "c1", "at": 1.0})], params.RUNG_ASSISTED_MIN),
        (set(), [("s9", {"id": "m", "course_id": "other", "at": 1.0})], 0),
    ],
)
def test_reveal_floor(revealed, markers, expected):
    from routes import learn_loop

    with (
        patch("routes.learn_loop.revealed_hashes", return_value=revealed),
        patch(
            "routes.learn_loop._resolve_reveal_markers",
            return_value={m["course_id"] for _, m in markers},
        ),
    ):
        assert learn_loop._reveal_floor("u1", BASE) == expected


def test_reveal_floor_fails_closed_when_the_revealed_read_fails():
    from routes import learn_loop

    with (
        patch("routes.learn_loop.revealed_hashes", side_effect=RuntimeError("down")),
        patch("routes.learn_loop._resolve_reveal_markers", return_value=set()),
    ):
        assert learn_loop._reveal_floor("u1", BASE) == params.RUNG_ASSISTED_MIN


def test_a_check_graded_after_an_unresolved_marker_is_assisted(gate_on, seams):
    agent_p, usage_p, _ = _routes._feedback_agent()
    with (
        agent_p,
        usage_p,
        patch("routes.learn_loop._reveal_floor", return_value=params.RUNG_ASSISTED_MIN),
    ):
        r = client.post(
            "/api/learn/loop/check/answer", json=_routes._answer(answer="n == 0 returns 1")
        )
    assert r.status_code == 200
    assert seams.grade.call_args.kwargs["max_rung"] >= params.RUNG_ASSISTED_MIN


# ── marker resolution ────────────────────────────────────────────────────────


def test_a_marker_resolves_by_scanning_the_sessions_later_tutor_messages():
    from routes import learn_loop

    saved = {}

    def _update(sid, mutate):
        doc = {"reveal_unscanned": [{"id": "m1", "course_id": "c1", "at": 100.0, "rung": 3}]}
        mutate(doc)
        saved[sid] = doc
        return doc

    msgs = MagicMock()
    msgs.select.return_value = [{"content": "enc"}]
    with (
        patch(
            "routes.learn_loop.unscanned_reveals",
            return_value=[("s9", {"id": "m1", "course_id": "c1", "at": 100.0, "rung": 3})],
        ),
        patch("routes.learn_loop.items_for_course", return_value=[BASE, STACK]),
        patch("routes.learn_loop.table", return_value=msgs),
        patch("routes.learn_loop.decrypt_if_present", return_value="It returns 1."),
        patch("routes.learn_loop._update_loop_state", side_effect=_update),
    ):
        assert learn_loop._resolve_reveal_markers("u1") == set()
    assert saved["s9"]["revealed"] == ["qh-base"] and saved["s9"]["reveal_unscanned"] == []
    filters = msgs.select.call_args.kwargs["filters"]
    assert filters["session_id"] == "eq.s9" and filters["role"] == "eq.assistant"


def test_an_unresolvable_marker_stays_and_names_its_course():
    from routes import learn_loop

    with (
        patch(
            "routes.learn_loop.unscanned_reveals",
            return_value=[("s9", {"id": "m1", "course_id": "c1", "at": 1.0})],
        ),
        patch("routes.learn_loop.items_for_course", side_effect=RuntimeError("down")),
    ):
        assert learn_loop._resolve_reveal_markers("u1") == {"c1"}


def test_a_failed_marker_read_is_unresolved_everywhere():
    from routes import learn_loop

    with patch("routes.learn_loop.unscanned_reveals", side_effect=RuntimeError("down")):
        assert learn_loop._resolve_reveal_markers("u1") == {learn_loop.ANY_COURSE}


# ── the opener (no session row yet): reveals ride the pending session ────────


def test_the_openers_reveals_are_applied_when_the_session_materialises():
    from routes import learn_loop

    learn_loop._PENDING_REVEALS["s7"] = {"user_id": "u1", "hashes": ["qh-base"], "mark": None}
    saved = {}

    def _update(sid, mutate):
        doc = {}
        mutate(doc)
        saved[sid] = doc
        return doc

    with (
        patch("routes.learn_loop._consume_pending") as consume,
        patch("routes.learn_loop._update_loop_state", side_effect=_update),
    ):
        learn_loop._consume_loop_pending("s7", "u1")
    consume.assert_called_once_with("s7", "u1")
    assert saved["s7"]["revealed"] == ["qh-base"] and "s7" not in learn_loop._PENDING_REVEALS


def test_pending_reveals_are_bounded():
    from routes import learn_loop

    learn_loop._PENDING_REVEALS.clear()
    for i in range(learn_loop.PENDING_REVEALS_MAX + 5):
        learn_loop._stash_pending_reveal(f"s{i}", {"user_id": "u", "hashes": ["h"], "mark": None})
    assert len(learn_loop._PENDING_REVEALS) == learn_loop.PENDING_REVEALS_MAX
    assert "s0" not in learn_loop._PENDING_REVEALS  # oldest first
    learn_loop._PENDING_REVEALS.clear()


# ── the store reader and the course item reader ──────────────────────────────


def test_unscanned_reveals_reads_every_sessions_markers():
    from learning import loop_state_store

    handle = MagicMock()
    handle.select_with_count.return_value = (
        [
            {"id": "s1", "marks": [{"id": "m", "course_id": "c1", "at": 1.0}]},
            {"id": "s2", "marks": None},
        ],
        2,
    )
    with patch("learning.loop_state_store.table", return_value=handle):
        assert loop_state_store.unscanned_reveals("u1") == [
            ("s1", {"id": "m", "course_id": "c1", "at": 1.0})
        ]
    kw = handle.select_with_count.call_args.kwargs
    assert kw["filters"]["user_id"] == "eq.u1"


def test_items_for_course_pages_every_concept():
    from services import check_item_service

    handle = MagicMock()
    handle.select_with_count.return_value = ([], 0)
    with patch("services.check_item_service.table", return_value=handle):
        assert check_item_service.items_for_course("c1") == []
    kw = handle.select_with_count.call_args.kwargs
    assert kw["filters"] == {"course_id": "eq.c1"} and kw["order"] == "id"


def test_the_teach_reveal_event_is_in_the_taxonomy_and_plain():
    from learning import zpd_events
    from services import events_service

    assert "zpd.teach_reveal" in events_service.EVENT_TAXONOMY
    captured = []
    with patch.object(
        zpd_events, "log_event", lambda et, **kw: captured.append((et, kw["payload"]))
    ):
        zpd_events.emit_zpd_teach_reveal(
            user_id="u1", request_id="r", question_hashes=["qh-base"], unscanned=False
        )
    assert captured == [
        ("zpd.teach_reveal", {"question_hashes": ["qh-base"], "count": 1, "unscanned": False})
    ]


def test_resolution_is_run_before_every_grading_floor(gate_on, seams):
    """_reveal_floor resolves markers first: a marker whose items are readable
    now becomes concrete revealed hashes rather than a blanket assisted grade."""
    from routes import learn_loop

    calls = []
    with (
        patch(
            "routes.learn_loop._resolve_reveal_markers",
            side_effect=lambda u: calls.append(u) or set(),
        ),
        patch("routes.learn_loop.revealed_hashes", return_value=set()),
    ):
        learn_loop._reveal_floor("u1", BASE)
    assert calls == ["u1"]


def test_a_review_grade_carries_the_reveal_floor_to_grade_answer():
    """A86: an open review item a teach turn revealed grades with no unassisted
    credit; with no floor the call is unchanged (max_rung defaults to 0)."""
    import asyncio
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from learning import review

    item = SimpleNamespace(kind="check", node_id="n1", id="i1")
    out = SimpleNamespace(refused=None, unavailable=True)
    for floor, expected in ((params.RUNG_NO_CREDIT_MIN, params.RUNG_NO_CREDIT_MIN), (0, None)):
        grade = AsyncMock(return_value=out)
        with (
            patch("learning.review.grade_answer", grade),
            patch("learning.review.recheck_after_release", return_value=False),
        ):
            asyncio.run(
                review.grade_review(
                    "u1",
                    item,
                    answer="a",
                    rating=None,
                    session_id="s",
                    loop_state={},
                    now=datetime(2026, 9, 29, tzinfo=timezone.utc),
                    request_id="r",
                    retention=0.9,
                    check_item=BASE,
                    deps=SimpleNamespace(),
                    max_rung=floor,
                )
            )
        assert grade.call_args.kwargs.get("max_rung") == expected


def test_review_answer_passes_the_floor(gate_on, seams):
    import inspect

    from routes import learn_loop

    src = inspect.getsource(learn_loop.review_answer)
    assert "_reveal_floor(" in src and "max_rung=" in src
