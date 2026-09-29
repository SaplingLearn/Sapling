"""PKG-14 rung 3: tool-removed, delayed post-test (spec §10; research §"Measure
learning…"; A16, A23, A33).

Below the route: the REAL grade_answer builds the Evidence (the grader call it
makes, agents.tools.check._rubric_grade / _reason_grade, is patched) and the
REAL flush_pending persists it through the patched apply_graph_update."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agents.grader import GradeResult
from learning import params
from learning.checks import CheckItem, Option, RubricItem, WrongReason
from main import app
from services import ai_budget

client = TestClient(app)

NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)
OLD = (NOW - timedelta(days=params.POSTTEST_MIN_AGE_DAYS + 1)).isoformat()
EDGE = (NOW - timedelta(days=params.POSTTEST_MIN_AGE_DAYS)).isoformat()  # exactly due
FRESH = (NOW - timedelta(hours=1)).isoformat()
MID = params.CHECK_ITEM_DIFFICULTIES[1]
START = "/api/learn/loop/posttest/start"
ANSWER = "/api/learn/loop/posttest/answer"


def item(key, qh, fmt="free", difficulty=MID, *, final_answer="its lexical scope"):
    options = None
    correct = None
    if fmt == "mc_reason":
        options = [
            Option(letter="A", text="its lexical scope"),
            Option(letter="B", text="a loop", wrong_key="loop"),
            Option(letter="C", text="a class", wrong_key="klass"),
            Option(letter="D", text="a module", wrong_key="mod"),
        ]
        correct = "A"
    return CheckItem(
        id=f"id-{qh}",
        course_id="c",
        concept_key=key,
        format=fmt,
        difficulty=difficulty,
        prompt="What is a closure?",
        reference_answer="A closure is a function with its lexical scope.",
        final_answer=final_answer,
        rubric=[
            RubricItem(id="r1", text="names the function"),
            RubricItem(id="r2", text="its scope"),
        ],
        common_wrong=[WrongReason(key="loop", text="a loop")],
        options=options,
        correct_option=correct,
        source_chunk_ids=["ch"],
        question_hash=qh,
    )


class _Fake:
    def __init__(self, rows):
        self.rows = rows

    def select(self, cols="*", filters=None, order=None, limit=None, **kw):
        out = list(self.rows)
        for col, cond in (filters or {}).items():
            op, _, val = cond.partition(".")
            assert op == "eq", cond
            out = [r for r in out if str(r.get(col)) == val]
        return out[:limit] if limit else out


@pytest.fixture(autouse=True)
def no_rate_limit():
    app.dependency_overrides[ai_budget.enforce_rate_limit] = lambda: None
    yield
    app.dependency_overrides.pop(ai_budget.enforce_rate_limit, None)


@pytest.fixture
def gate_on():
    with patch("routes.learn_loop.learning_loop_for_request", return_value=True) as g:
        yield g


@pytest.fixture
def gate_off():
    with patch("routes.learn_loop.learning_loop_for_request", return_value=False) as g:
        yield g


@pytest.fixture
def tables():
    """learner_state / graph_nodes rows (user "u") and CheckItem models, served
    to every read the route makes."""
    t = {"learner_state": [], "graph_nodes": [], "check_items": []}

    def _states(user_id, cutoff):  # the route re-applies the cutoff itself
        return [
            {"node_id": r["node_id"], "last_evidence_at": r["last_evidence_at"]}
            for r in t["learner_state"]
            if r["user_id"] == user_id
        ]

    def _items(course_id, keys):
        keys = list(keys)
        return {
            k: [i for i in t["check_items"] if i.course_id == course_id and i.concept_key == k]
            for k in keys
        }

    def _table(name):
        rows = [{"user_id": "u", **r} for r in t["graph_nodes"]] if name == "graph_nodes" else []
        return _Fake(rows)

    with (
        patch("routes.learn_loop.states_last_evidence_before", side_effect=_states),
        patch("routes.learn_loop.items_for_concepts", side_effect=_items),
        patch("routes.learn_loop.table", side_effect=_table),
        patch("routes.learn_loop.read_states", return_value={}),
    ):
        yield t


@pytest.fixture
def freeze_now():
    patches = []

    def _freeze(now):
        p = patch("routes.learn_loop._posttest_now", return_value=now)
        p.start()
        patches.append(p)

    yield _freeze
    for p in patches:
        p.stop()


@pytest.fixture
def seen_revealed():
    state = {"seen": set(), "revealed": set()}
    with (
        patch("routes.learn_loop.seen_hashes", side_effect=lambda u: set(state["seen"])),
        patch("routes.learn_loop.revealed_hashes", side_effect=lambda u: set(state["revealed"])),
    ):

        def _set(seen=None, revealed=None):
            if seen is not None:
                state["seen"] = set(seen)
            if revealed is not None:
                state["revealed"] = set(revealed)

        yield _set


@pytest.fixture
def grader_calls():
    return []


@pytest.fixture
def grader_says(grader_calls):
    active = []

    def _set(*, correct, confidence):
        async def _grade(item, **kw):
            grader_calls.append(kw)
            return GradeResult(all_yes=correct, confidence=confidence, backend="gemini"), "gemini"

        for name in ("_rubric_grade", "_reason_grade"):
            p = patch(f"agents.tools.check.{name}", side_effect=_grade)
            p.start()
            active.append(p)
        p = patch("agents.tools.check.match_wrong_key", return_value=None)
        p.start()
        active.append(p)

    yield _set
    for p in active:
        p.stop()


@pytest.fixture
def grader_unavailable(grader_calls):
    async def _grade(item, **kw):
        grader_calls.append(kw)
        return GradeResult(unavailable=True), None

    with patch("agents.tools.check._rubric_grade", side_effect=_grade):
        yield


@pytest.fixture
def applied():
    calls = []

    def _apply(user_id, graph_update, course_id=None, **kw):
        calls.append({"user_id": user_id, "graph_update": graph_update, "course_id": course_id})
        return [{"concept": "k1", "before": 0.35, "after": 0.71}]

    with patch("services.graph_service.apply_graph_update", side_effect=_apply):
        yield calls


@pytest.fixture
def captured_events():
    events = []
    with patch(
        "learning.zpd_events.log_event",
        side_effect=lambda et, **kw: events.append({"event_type": et, **kw}),
    ):
        yield events


def _due(*nodes, at=OLD):
    return [{"user_id": "u", "node_id": n, "last_evidence_at": at} for n in nodes]


def _answer(**kw):
    return {"user_id": "u", "node_id": "n1", "question_hash": "q1", **kw}


# ── the gate ─────────────────────────────────────────────────────────────────


def test_posttest_404_when_gate_false(gate_off):
    r = client.post(START, json={"course_id": "c", "user_id": "u"})
    assert r.status_code == 404 and r.json()["detail"] == "learning loop not enabled"
    r = client.post(
        ANSWER, json={"node_id": "n", "question_hash": "q", "answer": "x", "user_id": "u"}
    )
    assert r.status_code == 404 and r.json()["detail"] == "learning loop not enabled"


def test_answer_is_rate_limited_start_is_not():
    from routes import learn_loop

    deps = {r.path: {d.call for d in r.dependant.dependencies} for r in learn_loop.router.routes}
    assert ai_budget.enforce_rate_limit in deps["/posttest/answer"]
    assert ai_budget.enforce_rate_limit not in deps["/posttest/start"]


# ── /posttest/start ──────────────────────────────────────────────────────────


def test_start_serves_only_concepts_taught_long_enough_ago(
    gate_on, tables, freeze_now, seen_revealed
):
    freeze_now(NOW)
    tables["learner_state"] = [
        *_due("n-old"),
        *_due("n-edge", at=EDGE),
        *_due("n-fresh", at=FRESH),
        {"user_id": "u", "node_id": "n-none", "last_evidence_at": None},
    ]
    tables["graph_nodes"] = [
        {"id": "n-old", "course_id": "c", "concept_name": "old"},
        {"id": "n-edge", "course_id": "c", "concept_name": "edge"},
        {"id": "n-fresh", "course_id": "c", "concept_name": "fresh"},
        {"id": "n-none", "course_id": "c", "concept_name": "none"},
    ]
    tables["check_items"] = [
        item("old", "q-old"),
        item("edge", "q-edge"),
        item("fresh", "q-fresh"),
        item("none", "q-none"),
    ]
    r = client.post(START, json={"course_id": "c", "user_id": "u"})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["node_id"] for i in items] == ["n-old", "n-edge"]
    assert items[0]["prompt"] == "What is a closure?"
    assert set(items[0]) == {
        "node_id",
        "question_hash",
        "format",
        "difficulty",
        "prompt",
        "options",
    }
    assert items[0]["options"] is None  # free item


def test_start_skips_nodes_of_another_course(gate_on, tables, freeze_now, seen_revealed):
    freeze_now(NOW)
    tables["learner_state"] = _due("n1", "n2")
    tables["graph_nodes"] = [
        {"id": "n1", "course_id": "c", "concept_name": "k1"},
        {"id": "n2", "course_id": "other", "concept_name": "k2"},
    ]
    tables["check_items"] = [item("k1", "q1"), item("k2", "q2")]
    items = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert [i["node_id"] for i in items] == ["n1"]


def test_start_serves_the_reserve_and_never_a_seen_or_revealed_item(
    gate_on, tables, freeze_now, seen_revealed
):
    freeze_now(NOW)
    tables["learner_state"] = _due("n1", "n2", "n3", "n4")
    tables["graph_nodes"] = [
        {"id": f"n{i}", "course_id": "c", "concept_name": f"k{i}"} for i in (1, 2, 3, 4)
    ]
    tables["check_items"] = [
        item("k1", "a-res"),
        item("k1", "b-other"),  # reserve a-res unseen
        item("k2", "c-res"),
        item("k2", "d-other"),  # reserve revealed → d-other
        item("k3", "e-res"),  # only item seen → skipped
        item("k4", "f-res"),
        item("k4", "g-mc", fmt="mc_reason"),  # no free left → † lowest other
    ]
    seen_revealed(seen={"e-res", "f-res"}, revealed={"c-res"})
    items = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert sorted((i["node_id"], i["question_hash"]) for i in items) == [
        ("n1", "a-res"),
        ("n2", "d-other"),
        ("n4", "g-mc"),
    ]


def test_start_never_serves_an_item_without_a_final_answer(
    gate_on, tables, freeze_now, seen_revealed
):
    """A34: an item without a structured final answer is not servable — not even
    as the † fallback."""
    freeze_now(NOW)
    tables["learner_state"] = _due("n1")
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c", "concept_name": "k1"}]
    tables["check_items"] = [item("k1", "q1", final_answer=None)]
    assert client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"] == []


def test_start_serves_mc_reason_options_without_keys(gate_on, tables, freeze_now, seen_revealed):
    freeze_now(NOW)
    tables["learner_state"] = _due("n1")
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c", "concept_name": "k1"}]
    tables["check_items"] = [item("k1", "q1", fmt="mc_reason")]
    (served,) = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert served["options"] and all(set(o) == {"letter", "text"} for o in served["options"])
    assert "correct_option" not in served and "reference_answer" not in served


def test_start_caps_items_oldest_first(gate_on, tables, freeze_now, seen_revealed):
    freeze_now(NOW)
    n = params.POSTTEST_MAX_ITEMS + 2
    tables["learner_state"] = [
        {
            "user_id": "u",
            "node_id": f"n{i}",
            "last_evidence_at": (
                NOW - timedelta(days=params.POSTTEST_MIN_AGE_DAYS + i)
            ).isoformat(),
        }
        for i in range(n)
    ]
    tables["graph_nodes"] = [
        {"id": f"n{i}", "course_id": "c", "concept_name": f"k{i}"} for i in range(n)
    ]
    tables["check_items"] = [item(f"k{i}", f"q{i}") for i in range(n)]
    items = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert len(items) == params.POSTTEST_MAX_ITEMS
    assert items[0]["node_id"] == f"n{n - 1}"  # oldest evidence first


def test_start_writes_nothing_and_runs_no_model(
    gate_on, tables, freeze_now, seen_revealed, applied, captured_events
):
    freeze_now(NOW)
    tables["learner_state"] = _due("n1")
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c", "concept_name": "k1"}]
    tables["check_items"] = [item("k1", "q1")]
    with (
        patch("routes.learn_loop.grade_answer") as grade,
        patch("routes.learn_loop.retrieve_chunks") as rag,
        patch("routes.learn_loop.store_brief") as brief,
    ):
        assert client.post(START, json={"course_id": "c", "user_id": "u"}).status_code == 200
    grade.assert_not_called()
    rag.assert_not_called()
    brief.assert_not_called()
    assert applied == [] and captured_events == []


# ── /posttest/answer ─────────────────────────────────────────────────────────


@pytest.fixture
def one_item(tables, freeze_now, seen_revealed):
    freeze_now(NOW)
    tables["learner_state"] = _due("n1")
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c", "concept_name": "k1"}]
    tables["check_items"] = [item("k1", "q1")]
    return tables


def test_answer_grades_through_grade_answer_and_records_unassisted_evidence(
    gate_on, one_item, grader_says, applied, captured_events
):
    grader_says(correct=True, confidence=0.9)
    r = client.post(ANSWER, json=_answer(answer="a function with its lexical scope"))
    assert r.status_code == 200 and r.json() == {"correct": True, "confidence": 0.9}
    (call,) = applied
    assert call["course_id"] == "c" and call["user_id"] == "u"
    (ev,) = call["graph_update"]["evidence"]
    assert ev["assisted"] is False and ev["max_rung"] == 0 and ev["session_id"] is None
    assert ev["channel"] == "free_response" and ev["question_hash"] == "q1"
    assert ev["grader_backend"] == "gemini"  # set by grade_answer (A22)
    (step,) = [e for e in captured_events if e["event_type"] == "zpd.step"]
    p = step["payload"]
    assert p["phase"] == "posttest" and p["ceiling"] == 0 and p["ceiling_reason"] == "posttest"
    assert p["max_rung_used"] == 0 and p["assisted"] is False and p["n_attempts"] == 1
    assert p["grader_backend"] == "gemini" and p["variant"] == "A"
    assert p["p_known_after"] == pytest.approx(0.71)
    assert "tier" not in p  # no tutor turn ran: omitted, never zeroed


def test_answer_idk_is_incorrect_idk_evidence(
    gate_on, one_item, grader_says, grader_calls, applied
):
    grader_says(correct=True, confidence=0.9)  # must not be consulted
    r = client.post(ANSWER, json=_answer(answer="", idk=True))
    assert r.status_code == 200 and r.json()["correct"] is False
    assert grader_calls == []
    (ev,) = applied[0]["graph_update"]["evidence"]
    assert ev["idk"] is True and ev["correct"] is False and ev["channel"] == "free_response"  # A1


def test_answer_mc_reason_uses_the_option_and_the_reason(
    gate_on, tables, freeze_now, seen_revealed, grader_says, grader_calls, applied
):
    freeze_now(NOW)
    tables["learner_state"] = _due("n1")
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c", "concept_name": "k1"}]
    tables["check_items"] = [item("k1", "q1", fmt="mc_reason")]
    grader_says(correct=True, confidence=0.8)
    r = client.post(ANSWER, json=_answer(selected_option="A", reason="it keeps its scope"))
    assert r.status_code == 200 and r.json()["correct"] is True
    assert (
        grader_calls[0]["selected_option"] == "A"
        and grader_calls[0]["reason"] == "it keeps its scope"
    )
    (ev,) = applied[0]["graph_update"]["evidence"]
    assert ev["channel"] == "mc_reasoned"


def test_answer_mc_reason_without_an_option_is_422(
    gate_on, tables, freeze_now, seen_revealed, applied
):
    freeze_now(NOW)
    tables["learner_state"] = _due("n1")
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c", "concept_name": "k1"}]
    tables["check_items"] = [item("k1", "q1", fmt="mc_reason")]
    assert client.post(ANSWER, json=_answer(reason="why")).status_code == 422
    assert applied == []


@pytest.mark.parametrize("correct_attempt", [True, False])
def test_answer_grader_unavailable_is_503_and_writes_nothing(
    gate_on, one_item, grader_unavailable, applied, captured_events, correct_attempt
):
    answer = "a function with its lexical scope" if correct_attempt else "a loop"
    r = client.post(ANSWER, json=_answer(answer=answer))
    assert r.status_code == 503 and r.json()["detail"] == "grader unavailable"
    assert applied == [] and not [
        e for e in captured_events if e["event_type"] == "zpd.step"
    ]  # symmetric (inv 28)


def test_answer_refused_asks_again_and_records_nothing(
    gate_on, one_item, applied, captured_events, monkeypatch
):
    """Spec §13 A33 (CodeRabbit PR #673 round 3): a refusal records nothing and is never an
    idk here — no session counts refusals, and a post-test item may be left unanswered."""
    import routes.learn_loop as ll
    from types import SimpleNamespace

    async def _refused(*a, **kw):
        return SimpleNamespace(
            unavailable=True,
            refused="addresses_grader",
            correct=None,
            confidence=None,
            evidence=None,
            grader_backend=None,
        )

    monkeypatch.setattr(ll, "grade_answer", _refused)
    for _ in range(3):  # asked again every time; never turned into an idk
        r = client.post(ANSWER, json=_answer(answer="a loop"))
        assert r.status_code == 200 and r.json() == {"graded": False, "refused": True}
    assert applied == [] and not [e for e in captured_events if e["event_type"] == "zpd.step"]


def test_answer_over_the_length_bound_is_422(gate_on, one_item, applied):
    long = "a loop" + " " * params.GRADER_ANSWER_MAX_CHARS
    r = client.post(ANSWER, json=_answer(answer=long))
    assert r.status_code == 422 and applied == []


def test_answer_to_a_seen_item_is_409_and_never_graded(
    gate_on, one_item, seen_revealed, grader_says, grader_calls, applied
):
    """An answered post-test item is seen: a second submit never grades or flushes."""
    grader_says(correct=True, confidence=0.9)
    seen_revealed(seen={"q1"})
    r = client.post(ANSWER, json=_answer(answer="its lexical scope"))
    assert r.status_code == 409 and r.json()["detail"] == "not a post-test item"
    assert grader_calls == [] and applied == []


def test_answer_to_a_concept_taught_too_recently_is_409(gate_on, one_item, grader_says, applied):
    grader_says(correct=True, confidence=0.9)
    one_item["learner_state"] = _due("n1", at=FRESH)
    assert client.post(ANSWER, json=_answer(answer="x y z")).status_code == 409
    assert applied == []


def test_answer_to_an_item_that_is_not_the_concepts_posttest_item_is_409(
    gate_on, one_item, grader_says, applied
):
    """The reserve is unseen, so another item of the concept is not the post-test item."""
    grader_says(correct=True, confidence=0.9)
    one_item["check_items"] = [
        item("k1", "a-res"),
        item("k1", "q1", difficulty=params.CHECK_ITEM_DIFFICULTIES[0]),
    ]
    assert client.post(ANSWER, json=_answer(answer="x y z")).status_code == 409
    assert applied == []


def test_answer_to_another_students_node_is_404(gate_on, one_item, applied):
    r = client.post(ANSWER, json=_answer(user_id="someone-else", answer="x"))
    assert r.status_code == 404 and applied == []


def test_answer_unknown_item_is_404(gate_on, one_item, applied):
    assert client.post(ANSWER, json=_answer(question_hash="nope", answer="x")).status_code == 404


def test_concurrent_submits_of_one_item_flush_once(gate_on, one_item, seen_revealed, applied):
    """Two submits race: the per-(student, item) lock holds the eligibility check,
    the grade and the flush together; the second sees the item seen and is a 409."""
    import routes.learn_loop as ll
    from types import SimpleNamespace

    seen = set()
    seen_revealed(seen=set())

    async def _slow_grade(item, answer, *, deps, node_id, max_rung, **kw):
        await asyncio.sleep(0.05)
        deps.pending_evidence.append({"node_id": node_id, "question_hash": item.question_hash})
        return SimpleNamespace(
            unavailable=False,
            refused=None,
            correct=True,
            confidence=0.9,
            evidence={"channel": "free_response"},
            grader_backend="gemini",
        )

    def _flush(deps, course_id):
        seen.add("q1")
        seen_revealed(seen=seen)
        deps.pending_evidence.clear()
        applied.append({"flush": course_id})
        return []

    async def _run():
        body = ll.PosttestAnswerBody(**_answer(answer="its lexical scope"))

        class _Req:
            class state:
                pass

            headers: dict = {}

        async def one():
            try:
                return await ll.posttest_answer(body, _Req())
            except Exception as exc:  # noqa: BLE001 — the loser's 409
                return exc

        return await asyncio.gather(one(), one())

    with (
        patch("routes.learn_loop.grade_answer", side_effect=_slow_grade),
        patch("routes.learn_loop.flush_pending", side_effect=_flush),
        patch("routes.learn_loop.require_self", return_value=None),
        patch("routes.learn_loop._request_id", return_value="rid"),
        patch("routes.learn_loop.zpd_events"),
        patch("routes.learn_loop._arm_for", return_value=None),
    ):
        results = asyncio.run(_run())
    assert len(applied) == 1
    assert sum(1 for r in results if isinstance(r, dict)) == 1
    (loser,) = [r for r in results if not isinstance(r, dict)]
    assert getattr(loser, "status_code", None) == 409


# ── the phase value ──────────────────────────────────────────────────────────


def test_posttest_is_a_step_phase_value_not_a_close_phase():
    import glob
    from pathlib import Path

    mig = Path(__file__).resolve().parents[1] / "db" / "migrations"
    sql = "".join(open(p).read() for p in glob.glob(str(mig / "*_learning_session_close.sql")))
    assert sql and "posttest" not in sql
    from routes import learn_loop

    assert "posttest" in learn_loop.STEP_PHASES
    assert "posttest" not in params.CLOSE_PHASES
