"""PKG-14 rung 3: tool-removed, delayed post-test (spec §10; research §"Measure
learning…"; A16, A23, A33).

Below the route: the REAL grade_answer builds the Evidence (the grader call it
makes, agents.tools.check._rubric_grade / _reason_grade, is patched) and the
REAL flush_pending persists it through the patched apply_graph_update."""

from __future__ import annotations

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
    t = {"learner_state": [], "graph_nodes": [], "check_items": [], "poses": {}, "claims": []}

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

    def _nodes(user_id, course_id):
        from services.graph_service import _normalize_concept

        return {
            r["id"]: _normalize_concept(r["concept_name"])
            for r in t["graph_nodes"]
            if r.get("course_id") == course_id and user_id == "u"
        }

    # spec §13 A87: posttest_poses, in memory, with the route helpers' semantics
    def _read(user_id, course_id):
        return {
            n: dict(p)
            for (u, n), p in t["poses"].items()
            if u == user_id and p["course_id"] == course_id
        }

    def _record(rows):
        for r in rows:
            t["poses"][(r["user_id"], r["node_id"])] = dict(r)

    def _claim(user_id, node_id, qh, claim, now):
        p = t["poses"].get((user_id, node_id))
        t["claims"].append((user_id, node_id, qh))
        if not p or p["question_hash"] != qh or p.get("answered_at") or p.get("claim"):
            return False
        p["claim"] = claim
        return True

    def _settle(user_id, node_id, claim, *, answered):
        p = t["poses"].get((user_id, node_id))
        if p and p.get("claim") == claim:
            p["claim"] = None
            if answered is not None:
                p["answered_at"] = answered.isoformat()

    with (
        patch("routes.learn_loop.states_last_evidence_before", side_effect=_states),
        patch("routes.learn_loop.items_for_concepts", side_effect=_items),
        patch("routes.learn_loop.table", side_effect=_table),
        patch("routes.learn_loop.read_states", return_value={}),
        patch("routes.learn_loop._course_nodes", side_effect=_nodes),
        patch("routes.learn_loop._read_poses", side_effect=_read),
        patch("routes.learn_loop._record_poses", side_effect=_record),
        patch("routes.learn_loop._claim_pose", side_effect=_claim),
        patch("routes.learn_loop._settle_pose", side_effect=_settle),
    ):
        yield t


def _pose(t, node="n1", qh="q1", course="c", answered=None):
    t["poses"][("u", node)] = {
        "user_id": "u",
        "node_id": node,
        "course_id": course,
        "question_hash": qh,
        "answered_at": answered,
        "claim": None,
    }


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


def test_both_posttest_routes_are_rate_limited():
    """A87: /posttest/start writes a pose now, so it carries the A20 limit too."""
    from routes import learn_loop

    deps = {r.path: {d.call for d in r.dependant.dependencies} for r in learn_loop.router.routes}
    assert ai_budget.enforce_rate_limit in deps["/posttest/answer"]
    assert ai_budget.enforce_rate_limit in deps["/posttest/start"]


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


def test_start_runs_no_model_writes_no_evidence_and_records_the_pose(
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
    pose = tables["poses"][("u", "n1")]
    assert pose["question_hash"] == "q1" and pose["answered_at"] is None  # A87: committed


def test_a_repeat_start_returns_the_same_item_never_a_fresh_one(
    gate_on, tables, freeze_now, seen_revealed
):
    """A87: no shopping — the open pose is returned even after the item was
    revealed or seen since (its grade then carries no unassisted credit)."""
    freeze_now(NOW)
    tables["learner_state"] = _due("n1")
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c", "concept_name": "k1"}]
    tables["check_items"] = [item("k1", "a-res"), item("k1", "b-other")]
    first = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert [i["question_hash"] for i in first] == ["a-res"]
    seen_revealed(revealed={"a-res"})
    again = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert [i["question_hash"] for i in again] == ["a-res"]


def test_an_open_pose_stays_posed_when_the_node_is_no_longer_due(
    gate_on, tables, freeze_now, seen_revealed
):
    freeze_now(NOW)
    tables["learner_state"] = _due("n1", at=FRESH)
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c", "concept_name": "k1"}]
    tables["check_items"] = [item("k1", "q1")]
    _pose(tables)
    items = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert [i["question_hash"] for i in items] == ["q1"]


def test_an_answered_node_is_posed_again_only_when_due_again(
    gate_on, tables, freeze_now, seen_revealed
):
    freeze_now(NOW)
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c", "concept_name": "k1"}]
    tables["check_items"] = [item("k1", "q1"), item("k1", "q2")]
    _pose(tables, answered=FRESH)
    tables["learner_state"] = _due("n1", at=FRESH)  # the post-test answer was its last evidence
    assert client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"] == []
    tables["learner_state"] = _due("n1")  # old enough again
    seen_revealed(seen={"q1"})
    items = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert [i["question_hash"] for i in items] == ["q2"]
    assert tables["poses"][("u", "n1")]["answered_at"] is None


# ── /posttest/answer ─────────────────────────────────────────────────────────


@pytest.fixture
def one_item(tables, freeze_now, seen_revealed):
    freeze_now(NOW)
    tables["learner_state"] = _due("n1")
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c", "concept_name": "k1"}]
    tables["check_items"] = [item("k1", "q1")]
    _pose(tables)  # A87: the answer grades the open pose
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
    _pose(tables)
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


def test_an_answer_without_an_open_pose_is_409_and_never_graded(
    gate_on, one_item, grader_says, grader_calls, applied
):
    grader_says(correct=True, confidence=0.9)
    one_item["poses"].clear()
    r = client.post(ANSWER, json=_answer(answer="its lexical scope"))
    assert r.status_code == 409 and r.json()["detail"] == "not a post-test item"
    assert grader_calls == [] and applied == []


def test_an_answered_pose_is_never_graded_twice(gate_on, one_item, grader_says, applied):
    grader_says(correct=True, confidence=0.9)
    assert client.post(ANSWER, json=_answer(answer="its lexical scope")).status_code == 200
    assert one_item["poses"][("u", "n1")]["answered_at"] is not None
    assert client.post(ANSWER, json=_answer(answer="its lexical scope")).status_code == 409
    assert len(applied) == 1


def test_an_answer_to_another_item_of_the_concept_is_409(gate_on, one_item, grader_says, applied):
    grader_says(correct=True, confidence=0.9)
    one_item["check_items"].append(item("k1", "q2"))
    assert client.post(ANSWER, json=_answer(question_hash="q2", answer="x y z")).status_code == 409
    assert applied == []


@pytest.mark.parametrize("seen,revealed", [({"q1"}, set()), (set(), {"q1"})])
def test_an_open_pose_revealed_or_seen_since_grades_with_no_unassisted_credit(
    gate_on, one_item, seen_revealed, grader_says, applied, captured_events, seen, revealed
):
    """A86/A87: the committed item is still graded, like a released item."""
    grader_says(correct=True, confidence=0.9)
    seen_revealed(seen=seen, revealed=revealed)
    with patch("routes.learn_loop.revealed_hashes", side_effect=lambda u: set(revealed)):
        r = client.post(ANSWER, json=_answer(answer="its lexical scope"))
    assert r.status_code == 200
    (ev,) = applied[0]["graph_update"]["evidence"]
    assert ev["max_rung"] == params.RUNG_NO_CREDIT_MIN and ev["assisted"] is True
    (step,) = [e for e in captured_events if e["event_type"] == "zpd.step"]
    assert step["payload"]["assisted"] is True
    assert (
        step["payload"]["max_rung_used"] == step["payload"]["ceiling"] == params.RUNG_NO_CREDIT_MIN
    )


def test_a_refusal_or_an_outage_releases_the_claim(gate_on, one_item, grader_unavailable, applied):
    assert client.post(ANSWER, json=_answer(answer="a loop")).status_code == 503
    pose = one_item["poses"][("u", "n1")]
    assert pose["claim"] is None and pose["answered_at"] is None  # the student may answer again


def test_p_known_after_is_read_when_the_flush_does_not_say(
    gate_on, one_item, grader_says, captured_events
):
    grader_says(correct=True, confidence=0.9)
    with (
        patch("services.graph_service.apply_graph_update", return_value=[]),
        patch("routes.learn_loop._band_for", return_value=("profic", 0.93)),
    ):
        assert client.post(ANSWER, json=_answer(answer="its lexical scope")).status_code == 200
    (step,) = [e for e in captured_events if e["event_type"] == "zpd.step"]
    assert step["payload"]["p_known_after"] == pytest.approx(0.93)


def test_no_step_when_p_known_after_cannot_be_read(gate_on, one_item, grader_says, captured_events):
    grader_says(correct=True, confidence=0.9)
    calls = {"n": 0}

    def _band(user, node):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("down")
        return ("profic", 0.9)

    with (
        patch("services.graph_service.apply_graph_update", return_value=[]),
        patch("routes.learn_loop._band_for", side_effect=_band),
    ):
        assert client.post(ANSWER, json=_answer(answer="its lexical scope")).status_code == 200
    assert not [e for e in captured_events if e["event_type"] == "zpd.step"]  # never a None


def test_answer_to_another_students_node_is_404(gate_on, one_item, applied):
    r = client.post(ANSWER, json=_answer(user_id="someone-else", answer="x"))
    assert r.status_code == 404 and applied == []


def test_answer_unknown_item_is_404(gate_on, one_item, applied):
    assert client.post(ANSWER, json=_answer(question_hash="nope", answer="x")).status_code == 404


def test_a_second_submit_while_the_first_holds_the_claim_is_409(gate_on, one_item, applied):
    """A87: the claim is one conditional UPDATE in the database, so two
    submissions — in one process or many — never both grade."""
    one_item["poses"][("u", "n1")]["claim"] = "someone-else"
    assert client.post(ANSWER, json=_answer(answer="its lexical scope")).status_code == 409
    assert applied == []


# ── the pose helpers against the table seam ──────────────────────────────────


def test_claim_pose_is_one_conditional_update():
    from unittest.mock import MagicMock

    from routes import learn_loop

    handle = MagicMock()
    handle.update.return_value = [{"node_id": "n1"}]
    with patch("routes.learn_loop.table", return_value=handle) as tbl:
        assert learn_loop._claim_pose("u", "n1", "q1", "c-1", NOW) is True
    tbl.assert_called_with("posttest_poses")
    (data,) = handle.update.call_args.args[:1]
    filters = handle.update.call_args.kwargs["filters"]
    assert data["claim"] == "c-1"
    assert filters["answered_at"] == "is.null" and filters["question_hash"] == "eq.q1"
    assert filters["or"].startswith("(claim.is.null,claimed_at.lt.") and "+" not in filters["or"]
    handle.update.return_value = []
    with patch("routes.learn_loop.table", return_value=handle):
        assert learn_loop._claim_pose("u", "n1", "q1", "c-2", NOW) is False


def test_settle_and_record_poses():
    from unittest.mock import MagicMock

    from routes import learn_loop

    handle = MagicMock()
    with patch("routes.learn_loop.table", return_value=handle):
        learn_loop._settle_pose("u", "n1", "c-1", answered=NOW)
        learn_loop._record_poses([{"user_id": "u", "node_id": "n1"}])
        learn_loop._record_poses([])
    data = handle.update.call_args.args[0]
    assert data["answered_at"] == NOW.isoformat() and data["claim"] is None
    assert handle.update.call_args.kwargs["filters"]["claim"] == "eq.c-1"
    handle.upsert.assert_called_once_with(
        [{"user_id": "u", "node_id": "n1"}], on_conflict="user_id,node_id"
    )


def test_course_nodes_are_paged():
    from unittest.mock import MagicMock

    from routes import learn_loop

    handle = MagicMock()
    handle.select_with_count.return_value = ([{"id": "n1", "concept_name": "Recursion"}], 1)
    with patch("routes.learn_loop.table", return_value=handle):
        assert learn_loop._course_nodes("u", "c") == {"n1": "recursion"}
    assert handle.select_with_count.call_args.kwargs["order"] == "id"


def test_the_pose_migration_is_backend_only():
    import pathlib

    (mig,) = sorted(
        (pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations").glob(
            "*_learning_posttest_poses.sql"
        )
    )
    sql = mig.read_text()
    assert "PRIMARY KEY (user_id, node_id)" in sql and "ENABLE ROW LEVEL SECURITY" in sql


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


def test_answer_decides_the_recheck_through_the_one_helper(gate_on, one_item, grader_says, applied):
    """A76: every grading caller passes recheck_after_release's decision to
    grade_answer as same_session_recheck — the post-test with no session log."""
    grader_says(correct=True, confidence=0.9)
    with patch("routes.learn_loop.recheck_after_release", return_value=True) as rc:
        r = client.post(ANSWER, json=_answer(answer="its lexical scope"))
    assert r.status_code == 200
    args, kw = rc.call_args
    assert args[:3] == ("u", "n1", None) and kw["now"] == NOW and kw["item"].question_hash == "q1"
    (ev,) = applied[0]["graph_update"]["evidence"]
    assert ev["same_session_recheck"] is True
