"""PKG-14 rung 3: tool-removed, delayed post-test (spec §10; research §"Measure
learning…"; A16, A23, A33), at FIXED follow-up windows since spec §13 A112.

Below the route: the REAL grade_answer builds the Evidence (the grader call it
makes, agents.tools.check._rubric_grade / _reason_grade, is patched) and the
REAL flush_pending persists it through the patched apply_graph_update."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agents.grader import GradeResult
from learning import params
from learning.checks import CheckItem, Option, RubricItem, WrongReason
from learning.loop_state_store import EvidenceSpan
from main import app
from services import ai_budget

client = TestClient(app)

NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)
W1, W2 = params.POSTTEST_WINDOWS_DAYS  # A112: the 1-week and the 4-week window
OLD = NOW - timedelta(days=W1 + 1)  # first evidence: inside the first window
EDGE = NOW - timedelta(days=W1)  # the first window opens exactly now
FRESH = NOW - timedelta(hours=1)
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
    """The journal's evidence spans, graph_nodes rows (user "u") and CheckItem
    models, served to every read the route makes."""
    t = {
        "spans": {},  # A112: node id → EvidenceSpan (its first and last journaled evidence)
        "graph_nodes": [],
        "check_items": [],
        "poses": {},  # (user, node, window) → pose row
        "claims": [],
        "evidence_since": [],  # A89: the node's evidence journaled after the pose
        "skips": [],  # A126: the skip rows /posttest/start recorded
    }

    def _spans(user_id, course_id):  # the route keeps only its course's nodes itself
        return dict(t["spans"]) if user_id == "u" else {}

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

    # spec §13 A87/A112: posttest_poses, in memory — one row per (user, node,
    # window) — with the route helpers' semantics
    def _read(user_id, course_id):
        out: dict = {}
        for (u, n, w), p in t["poses"].items():
            if u == user_id and p["course_id"] == course_id:
                out.setdefault(n, {})[w] = dict(p)
        return out

    def _record(rows):
        for r in rows:
            t["poses"][(r["user_id"], r["node_id"], r["window_days"])] = dict(r)

    def _node_poses(user_id, node_id):
        return [p for (u, n, _), p in t["poses"].items() if (u, n) == (user_id, node_id)]

    def _claim(user_id, node_id, qh, claim, now):
        t["claims"].append((user_id, node_id, qh))
        ttl = now - timedelta(hours=params.POSTTEST_POSE_TTL_HOURS)
        posed = [  # A89: an expired pose is void
            p
            for p in _node_poses(user_id, node_id)
            if p["question_hash"] == qh
            and not p.get("answered_at")
            and datetime.fromisoformat(p["posed_at"]) >= ttl
        ]
        if not posed:
            return None
        p = min(posed, key=lambda p: (p["posed_at"], p["window_days"]))  # the earliest posed
        if p.get("claim"):
            return None
        p["claim"] = claim
        return dict(p)

    def _answer_pose(
        user_id, node_id, claim, now, *, correct, max_rung, latency_s=None, hidden_count=None, hidden_s=None
    ):
        for p in _node_poses(user_id, node_id):
            if p.get("claim") == claim and not p.get("answered_at"):
                p["claim"], p["answered_at"] = None, now.isoformat()
                p["correct"], p["max_rung"] = correct, max_rung
                # A126: what the answer reports beside its outcome
                p["answer_latency_s"], p["hidden_count"], p["hidden_s"] = latency_s, hidden_count, hidden_s
                return True
        return False

    def _release(user_id, node_id, claim):
        for p in _node_poses(user_id, node_id):
            if p.get("claim") == claim and not p.get("answered_at"):
                p["claim"] = None

    with (
        patch("routes.learn_loop.evidence_spans", side_effect=_spans),
        patch("routes.learn_loop.items_for_concepts", side_effect=_items),
        patch("routes.learn_loop.table", side_effect=_table),
        patch("routes.learn_loop.read_states", return_value={}),
        patch("routes.learn_loop._course_nodes", side_effect=_nodes),
        patch("routes.learn_loop._read_poses", side_effect=_read),
        patch("routes.learn_loop._record_poses", side_effect=_record),
        patch("routes.learn_loop._record_skips", side_effect=lambda rows: t["skips"].extend(rows)),
        patch("routes.learn_loop._claim_pose", side_effect=_claim),
        patch("routes.learn_loop._answer_pose", side_effect=_answer_pose),
        patch("routes.learn_loop._release_pose", side_effect=_release),
        patch(
            "routes.learn_loop.recent_evidence",
            side_effect=lambda u, n, *, since: list(t["evidence_since"]),
        ),
        patch("routes.learn_loop.unscanned_since", return_value=False),
    ):
        yield t


def _pose(t, node="n1", qh="q1", course="c", answered=None, posed=None, window=W1):
    t["poses"][("u", node, window)] = {
        "user_id": "u",
        "node_id": node,
        "course_id": course,
        "window_days": window,
        "question_hash": qh,
        "posed_at": (posed or NOW - timedelta(hours=1)).isoformat(),
        "answered_at": answered,
        "claim": None,
    }


def _span(first=OLD, last=None, first_id="ev-first"):
    """A112: a concept's journaled evidence — its first row (the anchor) and its
    last evidence time (the first one when not given)."""
    return EvidenceSpan(first_id, first, last or first)


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


def _due(*nodes, first=OLD, last=None):
    """tables["spans"] for nodes whose first graded evidence was at `first`."""
    return {n: _span(first, last, first_id=f"ev-{n}") for n in nodes}


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


def test_start_serves_only_concepts_whose_first_window_has_opened(
    gate_on, tables, freeze_now, seen_revealed
):
    """A112: due once the first window has opened after the concept's FIRST
    graded evidence; a concept with no journaled evidence is never due."""
    freeze_now(NOW)
    tables["spans"] = {
        **_due("n-old"),
        **_due("n-edge", first=EDGE),
        **_due("n-fresh", first=FRESH),
    }  # n-none: no evidence row at all
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
    tables["spans"] = _due("n1", "n2")
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
    tables["spans"] = _due("n1", "n2", "n3", "n4")
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
    tables["spans"] = _due("n1")
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c", "concept_name": "k1"}]
    tables["check_items"] = [item("k1", "q1", final_answer=None)]
    assert client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"] == []


def test_start_serves_mc_reason_options_without_keys(gate_on, tables, freeze_now, seen_revealed):
    freeze_now(NOW)
    tables["spans"] = _due("n1")
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c", "concept_name": "k1"}]
    tables["check_items"] = [item("k1", "q1", fmt="mc_reason")]
    (served,) = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert served["options"] and all(set(o) == {"letter", "text"} for o in served["options"])
    assert "correct_option" not in served and "reference_answer" not in served


def test_start_caps_items_earliest_opened_window_first(gate_on, tables, freeze_now, seen_revealed):
    freeze_now(NOW)
    n = params.POSTTEST_MAX_ITEMS + 2
    tables["spans"] = {
        f"n{i}": _span(NOW - timedelta(days=W1 + i), first_id=f"ev-{i}") for i in range(n)
    }
    tables["graph_nodes"] = [
        {"id": f"n{i}", "course_id": "c", "concept_name": f"k{i}"} for i in range(n)
    ]
    tables["check_items"] = [item(f"k{i}", f"q{i}") for i in range(n)]
    items = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert len(items) == params.POSTTEST_MAX_ITEMS
    assert items[0]["node_id"] == f"n{n - 1}"  # its window opened longest ago


def test_start_runs_no_model_writes_no_evidence_and_records_the_pose(
    gate_on, tables, freeze_now, seen_revealed, applied, captured_events
):
    freeze_now(NOW)
    tables["spans"] = _due("n1")
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c", "concept_name": "k1"}]
    tables["check_items"] = [item("k1", "q1")]
    with (
        patch("routes.learn_loop.grade_answer") as grade,
        patch("routes.learn_loop.retrieve_chunks_detailed") as rag,
        patch("routes.learn_loop.store_brief") as brief,
    ):
        assert client.post(START, json={"course_id": "c", "user_id": "u"}).status_code == 200
    grade.assert_not_called()
    rag.assert_not_called()
    brief.assert_not_called()
    assert applied == [] and captured_events == []
    pose = tables["poses"][("u", "n1", W1)]
    assert pose["question_hash"] == "q1" and pose["answered_at"] is None  # A87: committed


def test_a_repeat_start_returns_the_same_item_never_a_fresh_one(
    gate_on, tables, freeze_now, seen_revealed
):
    """A87: no shopping — the open pose is returned even after the item was
    revealed or seen since (its grade then carries no unassisted credit)."""
    freeze_now(NOW)
    tables["spans"] = _due("n1")
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
    tables["spans"] = _due("n1", first=FRESH)
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c", "concept_name": "k1"}]
    tables["check_items"] = [item("k1", "q1")]
    _pose(tables)
    items = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert [i["question_hash"] for i in items] == ["q1"]


# ── A112: fixed follow-up windows ────────────────────────────────────────────


@pytest.mark.parametrize(
    "age,window",
    [
        (timedelta(days=W1) - timedelta(seconds=1), None),  # before the first window
        (timedelta(days=W1), W1),  # it opens exactly at anchor + W1 days
        (timedelta(days=W2) - timedelta(seconds=1), W1),  # runs until the next one opens
        (timedelta(days=W2), W2),
        # A126: the last window closes at its bound, never "stays open"
        (timedelta(days=params.POSTTEST_LAST_WINDOW_CLOSE_DAYS) - timedelta(seconds=1), W2),
        (timedelta(days=params.POSTTEST_LAST_WINDOW_CLOSE_DAYS), None),
        (timedelta(days=10 * W2), None),
    ],
)
def test_the_window_is_counted_from_the_fixed_anchor(age, window):
    from routes import learn_loop

    assert learn_loop._posttest_window(NOW - age, NOW) == window


def test_the_windows_are_strictly_increasing_positive_days():
    windows = params.POSTTEST_WINDOWS_DAYS
    assert windows and all(type(w) is int and w > 0 for w in windows)
    assert list(windows) == sorted(set(windows))


def test_practice_never_postpones_a_window(gate_on, tables, freeze_now, seen_revealed):
    """The pre-A112 rule (last evidence ≥ 7 days old) let every review push the
    post-test back. Now the anchor is the FIRST evidence: a concept practised an
    hour ago is still posed in its open window."""
    freeze_now(NOW)
    tables["spans"] = _due("n1", first=OLD, last=FRESH)
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c", "concept_name": "k1"}]
    tables["check_items"] = [item("k1", "q1")]
    items = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert [i["question_hash"] for i in items] == ["q1"]


def test_the_pose_records_its_window_anchor_and_delay(gate_on, tables, freeze_now, seen_revealed):
    """Analysis stratifies on the delay since the concept's LAST evidence (truly
    delayed vs recently practised); the window is counted from its FIRST."""
    freeze_now(NOW)
    last = NOW - timedelta(days=3, hours=12)
    tables["spans"] = {"n1": _span(OLD, last, first_id="ev-anchor")}
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c", "concept_name": "k1"}]
    tables["check_items"] = [item("k1", "q1")]
    client.post(START, json={"course_id": "c", "user_id": "u"})
    pose = tables["poses"][("u", "n1", W1)]
    assert pose["window_days"] == W1
    assert pose["anchor_event_id"] == "ev-anchor" and pose["anchor_at"] == OLD.isoformat()
    assert pose["last_evidence_at"] == last.isoformat()
    assert pose["days_since_evidence"] == pytest.approx(3.5)
    assert pose["correct"] is None and pose["max_rung"] is None  # set when answered


def test_a_window_is_posed_at_most_once_then_the_next_one_opens(
    gate_on, tables, freeze_now, seen_revealed
):
    freeze_now(NOW)
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c", "concept_name": "k1"}]
    tables["check_items"] = [item("k1", "q1"), item("k1", "q2")]
    _pose(tables, answered=FRESH.isoformat())  # the first window, answered
    tables["spans"] = _due("n1", first=OLD, last=FRESH)
    assert client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"] == []
    tables["spans"] = _due("n1", first=NOW - timedelta(days=W2 + 1), last=FRESH)
    seen_revealed(seen={"q1"})  # the first window's answer made its item seen
    items = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert [i["question_hash"] for i in items] == ["q2"]  # a fresh item, never a seen one
    assert tables["poses"][("u", "n1", W2)]["answered_at"] is None
    assert tables["poses"][("u", "n1", W1)]["answered_at"] == FRESH.isoformat()  # kept


def test_a_window_the_student_was_away_for_is_skipped(gate_on, tables, freeze_now, seen_revealed):
    """First seen W2 + 2 days ago and never posed: the first window is over, so
    only the second is posed — never a "1-week" outcome measured weeks late."""
    freeze_now(NOW)
    tables["spans"] = _due("n1", first=NOW - timedelta(days=W2 + 2))
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c", "concept_name": "k1"}]
    tables["check_items"] = [item("k1", "q1")]
    client.post(START, json={"course_id": "c", "user_id": "u"})
    assert list(tables["poses"]) == [("u", "n1", W2)]


def test_an_open_pose_is_returned_across_a_window_boundary(
    gate_on, tables, freeze_now, seen_revealed
):
    """A87: the first window's pose, still open when the second window opens, is
    returned as posed; no second pose of the node until it is answered or void."""
    freeze_now(NOW)
    tables["spans"] = _due("n1", first=NOW - timedelta(days=W2))
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c", "concept_name": "k1"}]
    tables["check_items"] = [item("k1", "q1"), item("k1", "q2")]
    _pose(tables, qh="q2")
    items = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert [i["question_hash"] for i in items] == ["q2"]
    assert list(tables["poses"]) == [("u", "n1", W1)]


def test_an_expired_pose_binds_its_item_into_the_next_window(
    gate_on, tables, freeze_now, seen_revealed
):
    """A93 across windows: letting the first window's pose expire never buys a
    fresh item in the next window; the expired row stays as the missed window."""
    freeze_now(NOW)
    tables["spans"] = _due("n1", first=NOW - timedelta(days=W2 + 1))
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c", "concept_name": "k1"}]
    tables["check_items"] = [item("k1", "q1"), item("k1", "q2")]
    expired = NOW - timedelta(days=W2 - W1)
    _pose(tables, qh="q2", posed=expired)
    items = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert [i["question_hash"] for i in items] == ["q2"]
    assert tables["poses"][("u", "n1", W2)]["posed_at"] == NOW.isoformat()
    missed = tables["poses"][("u", "n1", W1)]
    assert missed["answered_at"] is None and missed["posed_at"] == expired.isoformat()


@pytest.mark.parametrize("stale", ["seen", "revealed"])
def test_a_bound_item_that_is_no_longer_fresh_is_never_reposed(
    gate_on, tables, freeze_now, seen_revealed, stale
):
    """A23 holds for every NEW pose: a bound item answered or revealed since the
    pose expired would grade practice as a delayed outcome, so a fresh item is
    chosen instead (an OPEN pose is still returned as posed, A87)."""
    freeze_now(NOW)
    tables["spans"] = _due("n1")
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c", "concept_name": "k1"}]
    tables["check_items"] = [item("k1", "q1"), item("k1", "q2")]
    _pose(tables, qh="q2", posed=NOW - timedelta(hours=params.POSTTEST_POSE_TTL_HOURS + 1))
    seen_revealed(**{stale: {"q2"}})
    items = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert [i["question_hash"] for i in items] == ["q1"]


def test_evidence_spans_read_the_journal_first_and_last_per_node():
    """The anchor is the journal's FIRST evidence row (read in its total order,
    scoped to the student's course); the last time is its newest row."""
    from unittest.mock import MagicMock

    from learning import loop_state_store

    t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    rows = [
        {"id": "e1", "node_id": "n1", "created_at": t0.isoformat(), "evidence_seq": 0},
        {"id": "e2", "node_id": "n2", "created_at": (t0 + timedelta(days=1)).isoformat()},
        {"id": "e3", "node_id": "n1", "created_at": (t0 + timedelta(days=9)).isoformat()},
        {"id": "e4", "node_id": "n1", "created_at": (t0 + timedelta(days=4)).isoformat()},
    ]
    handle = MagicMock()
    handle.select_with_count.return_value = (rows, len(rows))
    with patch("learning.loop_state_store.table", return_value=handle) as tbl:
        spans = loop_state_store.evidence_spans("u", "c")
    tbl.assert_called_with("node_mastery_events")
    kw = handle.select_with_count.call_args.kwargs
    assert kw["filters"] == {
        "graph_nodes.user_id": "eq.u",
        "graph_nodes.course_id": "eq.c",
        "event_type": "eq.evidence",
    }
    assert kw["order"] == "created_at.asc,evidence_seq.asc.nullslast,id.asc"
    assert spans["n1"] == EvidenceSpan("e1", t0, t0 + timedelta(days=9))
    assert spans["n2"].first_id == "e2" and spans["n2"].first_at == spans["n2"].last_at


# ── /posttest/answer ─────────────────────────────────────────────────────────


@pytest.fixture
def one_item(tables, freeze_now, seen_revealed):
    freeze_now(NOW)
    tables["spans"] = _due("n1")
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


@pytest.mark.parametrize("correct", [True, False])
def test_the_answer_records_the_outcome_on_the_pose(gate_on, one_item, grader_says, applied, correct):
    """A112: the conditional UPDATE that closes the pose records the outcome —
    `correct` and the rung the grade carried (0: an unassisted delayed outcome)."""
    grader_says(correct=correct, confidence=0.9)
    assert client.post(ANSWER, json=_answer(answer="its lexical scope")).status_code == 200
    pose = one_item["poses"][("u", "n1", W1)]
    assert pose["answered_at"] is not None and pose["claim"] is None
    assert pose["correct"] is correct and pose["max_rung"] == 0


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
    tables["spans"] = _due("n1")
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
    tables["spans"] = _due("n1")
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
    assert one_item["poses"][("u", "n1", W1)]["answered_at"] is not None
    assert client.post(ANSWER, json=_answer(answer="its lexical scope")).status_code == 409
    assert len(applied) == 1


def test_an_answer_to_another_item_of_the_concept_is_409(gate_on, one_item, grader_says, applied):
    grader_says(correct=True, confidence=0.9)
    one_item["check_items"].append(item("k1", "q2"))
    assert client.post(ANSWER, json=_answer(question_hash="q2", answer="x y z")).status_code == 409
    assert applied == []


@pytest.mark.parametrize(
    "since,revealed", [([{"question_hash": "other"}], set()), ([], {"q1"})]
)
def test_an_open_pose_revealed_or_worked_since_grades_with_no_unassisted_credit(
    gate_on, one_item, seen_revealed, grader_says, applied, captured_events, since, revealed
):
    """A88/A89 (owner 2): an open pose whose item a served turn revealed, or
    whose node has ANY evidence journaled after posed_at, is still graded — with
    no unassisted credit, like a released item."""
    grader_says(correct=True, confidence=0.9)
    one_item["evidence_since"] = since
    seen_revealed(revealed=revealed)
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
    # A112: the pose's outcome says so too — no clean delayed outcome
    pose = one_item["poses"][("u", "n1", W1)]
    assert pose["correct"] is True and pose["max_rung"] == params.RUNG_NO_CREDIT_MIN


def test_a_refusal_or_an_outage_releases_the_claim(gate_on, one_item, grader_unavailable, applied):
    assert client.post(ANSWER, json=_answer(answer="a loop")).status_code == 503
    pose = one_item["poses"][("u", "n1", W1)]
    assert pose["claim"] is None and pose["answered_at"] is None  # the student may answer again


def test_p_known_after_is_read_when_the_flush_does_not_say(
    gate_on, one_item, grader_says, captured_events
):
    from types import SimpleNamespace

    grader_says(correct=True, confidence=0.9)
    with (
        patch("services.graph_service.apply_graph_update", return_value=[]),
        patch("routes.learn_loop._learner_state", return_value=SimpleNamespace(p_known=0.93)),
    ):
        assert client.post(ANSWER, json=_answer(answer="its lexical scope")).status_code == 200
    (step,) = [e for e in captured_events if e["event_type"] == "zpd.step"]
    assert step["payload"]["p_known_after"] == pytest.approx(0.93)


@pytest.mark.parametrize("state", [None, RuntimeError("down")], ids=["no-row", "read-fails"])
def test_no_step_when_p_known_after_is_not_known(
    gate_on, one_item, grader_says, captured_events, state
):
    """m8: never a fabricated p_known_after — no stored row (the BKT prior is
    not a measurement) or a failed read emits no step, never a None."""
    grader_says(correct=True, confidence=0.9)
    kw = {"side_effect": state} if isinstance(state, Exception) else {"return_value": state}
    with (
        patch("services.graph_service.apply_graph_update", return_value=[]),
        patch("routes.learn_loop._learner_state", **kw),
        patch("routes.learn_loop._band_for", return_value=("develop", 0.35)),
    ):
        assert client.post(ANSWER, json=_answer(answer="its lexical scope")).status_code == 200
    assert not [e for e in captured_events if e["event_type"] == "zpd.step"]


def test_an_expired_pose_is_void_a_late_answer_is_409(gate_on, one_item, grader_says, applied):
    """A89 (owner 2): after POSTTEST_POSE_TTL_HOURS the pose is void."""
    grader_says(correct=True, confidence=0.9)
    _pose(one_item, posed=NOW - timedelta(hours=params.POSTTEST_POSE_TTL_HOURS, seconds=1))
    r = client.post(ANSWER, json=_answer(answer="its lexical scope"))
    assert r.status_code == 409 and applied == []


def test_an_expired_pose_may_be_re_posed(gate_on, one_item):
    _pose(
        one_item, qh="q-old", posed=NOW - timedelta(hours=params.POSTTEST_POSE_TTL_HOURS + 1)
    )
    items = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert [i["question_hash"] for i in items] == ["q1"]
    pose = one_item["poses"][("u", "n1", W1)]
    assert pose["question_hash"] == "q1" and pose["posed_at"] == NOW.isoformat()


def test_an_open_pose_within_the_ttl_is_returned_again(gate_on, one_item):
    _pose(one_item, posed=NOW - timedelta(hours=params.POSTTEST_POSE_TTL_HOURS - 1))
    posed_at = one_item["poses"][("u", "n1", W1)]["posed_at"]
    items = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert [i["question_hash"] for i in items] == ["q1"]
    assert one_item["poses"][("u", "n1", W1)]["posed_at"] == posed_at  # never re-posed


def test_a_taken_over_claim_writes_nothing(gate_on, one_item, grader_says, applied):
    """m1/m2: the claim is re-validated (and the pose closed) BEFORE the flush;
    a claim taken over mid-grade (stale takeover) writes no evidence."""
    grader_says(correct=True, confidence=0.9)
    with patch("routes.learn_loop._answer_pose", return_value=False):
        r = client.post(ANSWER, json=_answer(answer="its lexical scope"))
    assert r.status_code == 409 and applied == []


def test_a_failed_flush_never_reopens_the_answered_pose(gate_on, one_item, grader_says):
    """m2: the pose is closed before the flush; a flush that raises leaves it
    answered (fail closed: never graded twice), not released."""
    grader_says(correct=True, confidence=0.9)
    with (
        patch("routes.learn_loop.flush_pending", side_effect=RuntimeError("down")),
        pytest.raises(RuntimeError),
    ):
        client.post(ANSWER, json=_answer(answer="its lexical scope"))
    assert one_item["poses"][("u", "n1", W1)]["answered_at"] is not None


def test_an_unreadable_evidence_journal_grades_assisted(
    gate_on, one_item, grader_says, applied
):
    grader_says(correct=True, confidence=0.9)
    with patch("routes.learn_loop.recent_evidence", return_value=None):
        assert client.post(ANSWER, json=_answer(answer="its lexical scope")).status_code == 200
    (ev,) = applied[0]["graph_update"]["evidence"]
    assert ev["max_rung"] >= params.RUNG_ASSISTED_MIN and ev["assisted"] is True


def test_the_floor_reads_the_journal_from_posed_at(gate_on, one_item, grader_says, applied):
    grader_says(correct=True, confidence=0.9)
    with patch("routes.learn_loop.recent_evidence", return_value=[]) as journal:
        assert client.post(ANSWER, json=_answer(answer="its lexical scope")).status_code == 200
    posed = datetime.fromisoformat(one_item["poses"][("u", "n1", W1)]["posed_at"])
    assert journal.call_args.kwargs["since"] == learn_loop_iso_z(posed)


def learn_loop_iso_z(ts):
    from routes.learn_loop import _iso_z

    return _iso_z(ts)


def test_answer_to_another_students_node_is_404(gate_on, one_item, applied):
    r = client.post(ANSWER, json=_answer(user_id="someone-else", answer="x"))
    assert r.status_code == 404 and applied == []


def test_answer_unknown_item_is_404(gate_on, one_item, applied):
    assert client.post(ANSWER, json=_answer(question_hash="nope", answer="x")).status_code == 404


def test_a_second_submit_while_the_first_holds_the_claim_is_409(gate_on, one_item, applied):
    """A87: the claim is one conditional UPDATE in the database, so two
    submissions — in one process or many — never both grade."""
    one_item["poses"][("u", "n1", W1)]["claim"] = "someone-else"
    assert client.post(ANSWER, json=_answer(answer="its lexical scope")).status_code == 409
    assert applied == []


# ── the pose helpers against the table seam ──────────────────────────────────


def test_claim_pose_is_one_conditional_update():
    from unittest.mock import MagicMock

    from routes import learn_loop

    handle = MagicMock()
    handle.select.return_value = [{"window_days": W1, "posed_at": NOW.isoformat()}]
    handle.update.return_value = [{"node_id": "n1", "posed_at": NOW.isoformat()}]
    with patch("routes.learn_loop.table", return_value=handle) as tbl:
        assert learn_loop._claim_pose("u", "n1", "q1", "c-1", NOW) == handle.update.return_value[0]
    tbl.assert_called_with("posttest_poses")
    handle.update.assert_called_once()
    (data,) = handle.update.call_args.args[:1]
    filters = handle.update.call_args.kwargs["filters"]
    assert data["claim"] == "c-1"
    assert filters["answered_at"] == "is.null" and filters["question_hash"] == "eq.q1"
    assert filters["window_days"] == f"eq.{W1}"  # A112: the open pose's own window
    # m10: a claim with no claimed_at is claimable; the stale time is ISO-Z (no '+')
    assert filters["or"].startswith("(claim.is.null,claimed_at.is.null,claimed_at.lt.")
    assert "+" not in filters["or"]
    ttl = NOW - timedelta(hours=params.POSTTEST_POSE_TTL_HOURS)
    assert filters["posed_at"] == f"gte.{learn_loop._iso_z(ttl)}"  # A89
    # the window read asks for the same open pose: this item, unanswered, within the TTL
    read = handle.select.call_args.kwargs["filters"]
    assert {k: read[k] for k in ("question_hash", "answered_at", "posed_at")} == {
        k: filters[k] for k in ("question_hash", "answered_at", "posed_at")
    }
    handle.update.return_value = []
    with patch("routes.learn_loop.table", return_value=handle):
        assert learn_loop._claim_pose("u", "n1", "q1", "c-2", NOW) is None


def test_a_claim_names_one_window_and_none_without_an_open_pose():
    """A112: should a race have left two open poses of the item, the earliest
    posed is claimed, alone — one answer never closes two windows; no open pose
    → no UPDATE at all."""
    from unittest.mock import MagicMock

    from routes import learn_loop

    handle = MagicMock()
    handle.select.return_value = [
        {"window_days": W2, "posed_at": (NOW - timedelta(minutes=1)).isoformat()},
        {"window_days": W1, "posed_at": (NOW - timedelta(minutes=2)).isoformat()},
    ]
    handle.update.return_value = [{"node_id": "n1"}]
    with patch("routes.learn_loop.table", return_value=handle):
        learn_loop._claim_pose("u", "n1", "q1", "c-1", NOW)
    assert handle.update.call_args.kwargs["filters"]["window_days"] == f"eq.{W1}"
    handle.reset_mock()
    handle.select.return_value = []
    with patch("routes.learn_loop.table", return_value=handle):
        assert learn_loop._claim_pose("u", "n1", "q1", "c-2", NOW) is None
    handle.update.assert_not_called()


def test_answer_release_and_record_poses():
    from unittest.mock import MagicMock

    from routes import learn_loop

    handle = MagicMock()
    handle.update.return_value = [{"node_id": "n1"}]
    with patch("routes.learn_loop.table", return_value=handle):
        assert learn_loop._answer_pose("u", "n1", "c-1", NOW, correct=True, max_rung=0) is True
        answered = handle.update.call_args
        learn_loop._release_pose("u", "n1", "c-1")
        released = handle.update.call_args
        learn_loop._record_poses([{"user_id": "u", "node_id": "n1"}])
        learn_loop._record_poses([])
    assert answered.args[0] == {
        "answered_at": NOW.isoformat(),
        "claim": None,
        "claimed_at": None,
        "correct": True,  # A112: the outcome, in the write that closes the pose
        "max_rung": 0,
        # A126: what the answer reports beside it (none here: unknown, never 0)
        "answer_latency_s": None,
        "hidden_count": None,
        "hidden_s": None,
    }
    assert answered.kwargs["filters"]["claim"] == "eq.c-1"
    assert answered.kwargs["filters"]["answered_at"] == "is.null"  # m1: re-validated
    assert released.args[0] == {"claim": None, "claimed_at": None}
    assert released.kwargs["filters"]["answered_at"] == "is.null"  # never reopens an answer
    handle.upsert.assert_called_once_with(
        [{"user_id": "u", "node_id": "n1"}], on_conflict="user_id,node_id,window_days"
    )
    handle.update.return_value = []
    with patch("routes.learn_loop.table", return_value=handle):
        assert learn_loop._answer_pose("u", "n1", "c-1", NOW, correct=False, max_rung=4) is False


def test_read_poses_keys_each_node_by_window():
    from unittest.mock import MagicMock

    from routes import learn_loop

    handle = MagicMock()
    handle.select.return_value = [
        {"node_id": "n1", "window_days": W1, "question_hash": "q1"},
        {"node_id": "n1", "window_days": W2, "question_hash": "q2"},
    ]
    with patch("routes.learn_loop.table", return_value=handle):
        poses = learn_loop._read_poses("u", "c")
    assert {w: p["question_hash"] for w, p in poses["n1"].items()} == {W1: "q1", W2: "q2"}
    assert "window_days" in handle.select.call_args.args[0].split(",")


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


def test_the_windows_migration_rekeys_the_poses_and_maps_old_rows_to_the_first_window():
    """A112: a NEW migration (the A87 one is immutable): one row per (student,
    node, window); every pre-window row becomes the 7-day window; the anchor,
    the delay and the outcome columns; the outcome only on an answered pose."""
    import pathlib

    (mig,) = sorted(
        (pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations").glob(
            "*_learning_posttest_windows.sql"
        )
    )
    sql = mig.read_text()
    assert "PRIMARY KEY (user_id, node_id, window_days)" in sql
    assert "UPDATE posttest_poses SET window_days = 7 WHERE window_days IS NULL" in sql
    assert "ALTER COLUMN window_days SET NOT NULL" in sql
    assert W1 == 7  # the mapping above names the first window
    for column in (
        "anchor_event_id text",
        "anchor_at timestamptz",
        "last_evidence_at timestamptz",
        "days_since_evidence double precision",
        "correct boolean",
        "max_rung smallint",
    ):
        assert f"ADD COLUMN IF NOT EXISTS {column}" in sql
    assert "(correct IS NULL OR answered_at IS NOT NULL)" in sql
    assert "NOTIFY pgrst" in sql


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


# ── spec §13 A113: never a reported or retired item; clean items first ──────


@pytest.fixture
def reported():
    state: set[str] = set()
    with patch("routes.learn_loop.reported_hashes", side_effect=lambda u: set(state)) as reads:
        yield SimpleNamespace(hashes=state, reads=reads)


def _one_concept(tables, *items):
    tables["spans"] = _due("n1")  # A112: the first window is open
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c", "concept_name": "k1"}]
    tables["check_items"] = list(items)


def test_start_never_poses_an_item_the_student_reported(
    gate_on, tables, freeze_now, seen_revealed, reported
):
    freeze_now(NOW)
    _one_concept(tables, item("k1", "q1"), item("k1", "q2"))  # q1 would be the reserve
    reported.hashes.add("q1")
    (served,) = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert served["question_hash"] == "q2"
    reported.reads.assert_called_once_with("u")  # read once per request
    reported.hashes.add("q2")
    tables["poses"].clear()
    assert client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"] == []


def test_start_replaces_an_open_or_bound_pose_whose_item_was_reported(
    gate_on, tables, freeze_now, seen_revealed, reported
):
    """An open pose returns its item again (A87), and an expired one keeps its
    item bound (A93) — unless the student reported that item since: it is
    never posed again, so the node gets a fresh one."""
    freeze_now(NOW)
    _one_concept(tables, item("k1", "q1"), item("k1", "q2"))
    _pose(tables, qh="q1")
    reported.hashes.add("q1")
    (served,) = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert served["question_hash"] == "q2"
    assert tables["poses"][("u", "n1", W1)]["question_hash"] == "q2"  # the pose itself moved
    expired = NOW - timedelta(hours=params.POSTTEST_POSE_TTL_HOURS + 1)
    _pose(tables, qh="q1", posed=expired)
    (served,) = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert served["question_hash"] == "q2"


def test_start_never_poses_a_retired_item(gate_on, tables, freeze_now, seen_revealed, reported):
    """A retired item is deleted from the course's items (check_item_service's
    A23 retire path): an open pose of it is withdrawn, never re-posed."""
    freeze_now(NOW)
    _one_concept(tables, item("k1", "q2"))  # q1 retired: gone from the course's items
    _pose(tables, qh="q1")
    (served,) = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert served["question_hash"] == "q2"


def test_a_grade_refused_because_the_item_was_retired_meanwhile_is_a_409(
    gate_on, one_item, grader_says
):
    """Retired while it was graded (the commit refused it under the item's
    lock): nothing was written, the pose stays answered — its outcome is
    excluded from the learning gain by the void rule — and the student is told."""
    from learning.evidence_transaction import EvidenceItemRetired

    grader_says(correct=True, confidence=0.9)
    with patch(
        "services.graph_service.apply_graph_update",
        side_effect=EvidenceItemRetired("retired"),
    ):
        r = client.post(ANSWER, json=_answer(answer="its lexical scope"))
    assert r.status_code == 409 and "withdrawn" in r.json()["detail"]
    pose = one_item["poses"][("u", "n1", W1)]
    assert pose["answered_at"] is not None and pose["claim"] is None


def test_start_prefers_a_lint_clean_item(gate_on, tables, freeze_now, seen_revealed, reported):
    freeze_now(NOW)
    flagged = item("k1", "q1").model_copy(update={"lint_flags": ["negative_stem"]})
    unlinted = item("k1", "q2")
    clean = item("k1", "q3").model_copy(update={"lint_flags": []})
    _one_concept(tables, flagged, unlinted, clean)
    (served,) = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert served["question_hash"] == "q3"
    tables["poses"].clear()
    seen_revealed(seen={"q3"})
    (served,) = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert served["question_hash"] == "q2"  # never linted beats flagged
    tables["poses"].clear()
    seen_revealed(seen={"q2", "q3"})
    (served,) = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert served["question_hash"] == "q1"  # flagged only when nothing else is left


# ── A112 × A113: no window ever poses, or grades, an item the student reported ──


def test_the_28_day_window_never_poses_a_reported_item(
    gate_on, tables, freeze_now, seen_revealed, reported
):
    """The second window's pose skips an item the student reported: posed
    there before the report, its open pose counts as no pose and the window is
    re-posed with the next fresh item; with nothing fresh and unreported left,
    the window is skipped. The answered first window is never touched."""
    freeze_now(NOW)
    _one_concept(tables, item("k1", "q1"), item("k1", "q2"), item("k1", "q3"))
    tables["spans"] = _due("n1", first=NOW - timedelta(days=W2 + 1), last=FRESH)
    _pose(tables, qh="q1", answered=FRESH.isoformat())  # the first window, answered
    seen_revealed(seen={"q1"})  # its answer made the reserve seen
    items = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert [i["question_hash"] for i in items] == ["q2"]  # the A23 fallback
    reported.hashes.add("q2")  # reported since, on another surface
    items = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert [i["question_hash"] for i in items] == ["q3"]
    assert tables["poses"][("u", "n1", W2)]["question_hash"] == "q3"  # the 28-day pose moved
    first = tables["poses"][("u", "n1", W1)]
    assert first["question_hash"] == "q1" and first["answered_at"] == FRESH.isoformat()
    del tables["poses"][("u", "n1", W2)]
    reported.hashes.add("q3")
    assert client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"] == []
    assert ("u", "n1", W2) not in tables["poses"]


def test_an_expired_first_window_pose_never_binds_a_reported_item_into_the_next(
    gate_on, tables, freeze_now, seen_revealed, reported
):
    """A93 binds an expired, unanswered pose's item into the next window
    (test_an_expired_pose_binds_its_item_into_the_next_window) — never once the
    student reported it: the 28-day window gets a fresh item, and the missed
    first-window row stays as it was."""
    freeze_now(NOW)
    _one_concept(tables, item("k1", "q1"), item("k1", "q2"))
    tables["spans"] = _due("n1", first=NOW - timedelta(days=W2 + 1))
    expired = NOW - timedelta(days=W2 - W1)
    _pose(tables, qh="q2", posed=expired)
    reported.hashes.add("q2")
    items = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert [i["question_hash"] for i in items] == ["q1"]
    assert tables["poses"][("u", "n1", W2)]["question_hash"] == "q1"
    missed = tables["poses"][("u", "n1", W1)]
    assert missed["question_hash"] == "q2" and missed["answered_at"] is None
    assert missed["posed_at"] == expired.isoformat()


def test_an_open_first_window_pose_of_a_reported_item_gives_way_to_the_28_day_window(
    gate_on, tables, freeze_now, seen_revealed, reported, grader_says, applied
):
    """A87 returns the first window's pose while it is open, across the window
    boundary (test_an_open_pose_is_returned_across_a_window_boundary) — not
    once its item is reported: the 28-day window is posed with a fresh item.
    The first window's row is left as posed but is never answerable: a stale
    submission of the reported item is refused before any claim, and the fresh
    item answers the 28-day window only."""
    freeze_now(NOW)
    _one_concept(tables, item("k1", "q1"), item("k1", "q2"))
    tables["spans"] = _due("n1", first=NOW - timedelta(days=W2))  # the second window opens now
    _pose(tables, qh="q2")  # the first window's pose, still open
    reported.hashes.add("q2")
    items = client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]
    assert [i["question_hash"] for i in items] == ["q1"]
    assert tables["poses"][("u", "n1", W2)]["question_hash"] == "q1"
    assert tables["poses"][("u", "n1", W1)]["question_hash"] == "q2"
    grader_says(correct=True, confidence=0.9)
    stale = client.post(ANSWER, json=_answer(question_hash="q2", answer="its lexical scope"))
    assert stale.status_code == 409 and stale.json()["detail"] == "not a post-test item"
    assert tables["claims"] == [] and applied == []
    fresh = client.post(ANSWER, json=_answer(question_hash="q1", answer="its lexical scope"))
    assert fresh.status_code == 200 and len(applied) == 1
    assert tables["poses"][("u", "n1", W2)]["answered_at"] is not None
    assert tables["poses"][("u", "n1", W1)]["answered_at"] is None


def test_an_open_pose_whose_item_was_reported_since_is_not_answerable(
    gate_on, one_item, reported, grader_says, applied
):
    """Reported on another surface after it was posed, before any new start:
    refused before the claim (nothing graded, claimed or recorded), so the
    window stays unanswered and the next start poses a fresh item in it."""
    reported.hashes.add("q1")
    grader_says(correct=True, confidence=0.9)
    r = client.post(ANSWER, json=_answer(answer="its lexical scope"))
    assert r.status_code == 409 and r.json()["detail"] == "not a post-test item"
    assert one_item["claims"] == [] and applied == []
    pose = one_item["poses"][("u", "n1", W1)]
    assert pose["answered_at"] is None and pose["claim"] is None and pose.get("correct") is None


def test_an_unreadable_reported_set_refuses_the_answer(gate_on, one_item, applied):
    """Fail closed: whether the item was reported cannot be told, so nothing is
    claimed or graded (503, retry)."""
    with patch("routes.learn_loop.reported_hashes", side_effect=RuntimeError("down")):
        r = client.post(ANSWER, json=_answer(answer="its lexical scope"))
    assert r.status_code == 503 and one_item["claims"] == [] and applied == []


def test_band_control_ceilings_never_reach_the_posttest(
    gate_on, one_item, grader_says, applied, captured_events, monkeypatch
):
    """Spec §13 A122: band control's ceiling clause moves an in-session band
    ceiling only. The tool-removed post-test stays at H0 (spec §10 rung 3): it
    reads no band ceiling and no table ceiling at all."""
    import routes.learn_loop as loop_routes

    def never(*a, **k):
        raise AssertionError("the post-test read a ceiling")

    monkeypatch.setattr(loop_routes, "_band_ceiling_delta", never)
    monkeypatch.setattr(loop_routes, "_ceiling_for", never)
    monkeypatch.setattr(loop_routes.policy, "ceiling_with_reason", never)
    grader_says(correct=True, confidence=0.9)
    r = client.post(ANSWER, json=_answer(answer="a function with its lexical scope"))
    assert r.status_code == 200, r.text
    (step,) = [e for e in captured_events if e["event_type"] == "zpd.step"]
    assert step["payload"]["ceiling"] == 0 and step["payload"]["ceiling_reason"] == "posttest"
    (call,) = applied
    assert call["graph_update"]["evidence"][0]["max_rung"] == 0


# ══ spec §13 A126: matched outcome items, skips, the close, the telemetry ══

CLOSE = params.POSTTEST_LAST_WINDOW_CLOSE_DAYS
FMT = {"f": "free", "t": "teachback", "m": "mc_reason"}


def _grid(key="k1"):
    """A full bank: one item per (format, difficulty) — hashes 'f1' … 'm3'.
    The reserves (checks.posttest_reserve_hashes) are f2, then m2."""
    return [item(key, f"{f}{d}", FMT[f], d) for f in "ftm" for d in params.CHECK_ITEM_DIFFICULTIES]


def _grid_concept(tables, *, pretest, first=OLD):
    tables["spans"] = {"n1": EvidenceSpan("ev-anchor", first, first, pretest)}
    tables["graph_nodes"] = [{"id": "n1", "course_id": "c", "concept_name": "k1"}]
    tables["check_items"] = _grid()


def _start():
    return client.post(START, json={"course_id": "c", "user_id": "u"}).json()["items"]


def test_the_reserves_are_matched_to_the_students_pretest_item(gate_on, tables, freeze_now, seen_revealed):
    """The pretest was m1 (mc_reason, difficulty 1): of the two protected
    reserves (f2, m2), m2 shares its format, so the first window poses it —
    and the pose records the match and that the item was a reserve."""
    freeze_now(NOW)
    _grid_concept(tables, pretest="m1")
    seen_revealed(seen={"m1"})
    assert [i["question_hash"] for i in _start()] == ["m2"]
    pose = tables["poses"][("u", "n1", W1)]
    assert (pose["item_match"], pose["item_source"]) == ("format", "reserve")
    assert pose["served_at"] is None and pose["answer_latency_s"] is None
    assert pose["hidden_count"] is None and pose["hidden_s"] is None


def test_without_a_pretest_item_each_window_takes_its_own_reserve(gate_on, tables, freeze_now, seen_revealed):
    """No pretest to match (the anchor's item is not in the bank — a quiz
    question, a retired item): the first window's reserve, then the second's."""
    freeze_now(NOW)
    _grid_concept(tables, pretest="quiz-question")
    assert [i["question_hash"] for i in _start()] == ["f2"]
    assert tables["poses"][("u", "n1", W1)]["item_match"] == "no_pretest"
    tables["poses"][("u", "n1", W1)]["answered_at"] = FRESH.isoformat()
    seen_revealed(seen={"f2"})
    tables["spans"]["n1"] = EvidenceSpan("ev-anchor", NOW - timedelta(days=W2 + 1), FRESH, None)
    assert [i["question_hash"] for i in _start()] == ["m2"]
    second = tables["poses"][("u", "n1", W2)]
    assert (second["item_match"], second["item_source"]) == ("no_pretest", "reserve")


def test_with_no_fresh_reserve_a_fallback_is_posed_and_recorded(gate_on, tables, freeze_now, seen_revealed):
    """Both reserves seen (an older student practised them before they were
    protected): the fresh item nearest the pretest (m1 → difficulty 1, a free
    item first) is posed, and the pose says it was a fallback."""
    freeze_now(NOW)
    _grid_concept(tables, pretest="m1")
    seen_revealed(seen={"m1", "f2", "m2"})
    assert [i["question_hash"] for i in _start()] == ["f1"]
    pose = tables["poses"][("u", "n1", W1)]
    assert (pose["item_match"], pose["item_source"]) == ("difficulty", "fallback")
    assert tables["skips"] == []


@pytest.mark.parametrize(
    "bank,seen,reported_items,reason",
    [
        ([item("k1", "q1", final_answer=None)], set(), set(), "no_items"),  # nothing servable (A34)
        ([], set(), set(), "no_items"),  # no item drafted for the concept
        ([item("k1", "q1"), item("k1", "q2")], {"q1"}, set(), "exhausted"),  # q2 revealed below
        ([item("k1", "q1"), item("k1", "q2")], {"q1"}, {"q2"}, "reported"),
    ],
)
def test_a_due_window_with_nothing_fresh_is_skipped_with_its_reason(
    gate_on, tables, freeze_now, seen_revealed, reported, bank, seen, reported_items, reason
):
    freeze_now(NOW)
    _one_concept(tables, *bank)
    seen_revealed(seen=seen, revealed=set() if reported_items else {"q2"})
    reported.hashes.update(reported_items)
    assert _start() == []
    assert tables["poses"] == {}
    (skip,) = tables["skips"]
    assert skip == {
        "user_id": "u",
        "node_id": "n1",
        "course_id": "c",
        "window_days": W1,
        "reason": reason,
        "skipped_at": NOW.isoformat(),
    }
    assert reason in params.POSTTEST_SKIP_REASONS


def test_the_skip_write_never_fails_the_start():
    from routes import learn_loop

    class _Down:
        def upsert(self, *_a, **_kw):
            raise RuntimeError("db down")

    with patch("routes.learn_loop.table", return_value=_Down()):
        learn_loop._record_skips([{"user_id": "u"}])  # logged, not raised
    with patch("routes.learn_loop.table") as tbl:
        learn_loop._record_skips([])
    tbl.assert_not_called()


def test_the_last_window_closes(gate_on, tables, freeze_now, seen_revealed):
    """A126: no pose opens at or after the close; a concept whose last window
    closed is neither posed nor skipped — and a pose opened before the close
    is still returned within its TTL (A89), like any pose open across a
    boundary (A112)."""
    freeze_now(NOW)
    _one_concept(tables, item("k1", "q1"))
    tables["spans"] = _due("n1", first=NOW - timedelta(days=CLOSE))
    assert _start() == [] and tables["poses"] == {} and tables["skips"] == []
    tables["spans"] = _due("n1", first=NOW - timedelta(days=CLOSE) + timedelta(minutes=1))
    assert [i["question_hash"] for i in _start()] == ["q1"]
    assert list(tables["poses"]) == [("u", "n1", W2)]
    tables["spans"] = _due("n1", first=NOW - timedelta(days=CLOSE, hours=2))  # closed since
    assert [i["question_hash"] for i in _start()] == ["q1"]  # the open pose, as posed


def test_the_answer_records_latency_and_clamped_visibility(gate_on, one_item, grader_says, applied):
    """The latency is answered_at − served_at (the display /posttest/shown
    stamped); the client's hidden seconds can never exceed it."""
    grader_says(correct=True, confidence=0.9)
    one_item["poses"][("u", "n1", W1)]["served_at"] = (NOW - timedelta(seconds=90)).isoformat()
    r = client.post(
        ANSWER, json=_answer(answer="its lexical scope", hidden_count=3, hidden_s=500.0)
    )
    assert r.status_code == 200, r.text
    pose = one_item["poses"][("u", "n1", W1)]
    assert pose["answer_latency_s"] == pytest.approx(90.0)
    assert (pose["hidden_count"], pose["hidden_s"]) == (3, pytest.approx(90.0))


def test_without_a_display_stamp_the_latency_is_unknown_and_the_bound_is_the_pose(
    gate_on, one_item, grader_says, applied
):
    grader_says(correct=True, confidence=0.9)
    r = client.post(ANSWER, json=_answer(answer="its lexical scope", hidden_count=1, hidden_s=10**6))
    assert r.status_code == 200
    pose = one_item["poses"][("u", "n1", W1)]
    assert pose["answer_latency_s"] is None  # never posed_at standing in for the display
    assert pose["hidden_s"] == pytest.approx(3600.0)  # bounded by posed_at (an hour ago)


@pytest.mark.parametrize("telemetry", [{}, {"hidden_count": "lots", "hidden_s": {"x": 1}}, {"hidden_s": None}])
def test_missing_or_malformed_telemetry_is_not_reported_and_never_a_422(
    gate_on, one_item, grader_says, applied, telemetry
):
    grader_says(correct=True, confidence=0.9)
    r = client.post(ANSWER, json=_answer(answer="its lexical scope", **telemetry))
    assert r.status_code == 200, r.text
    pose = one_item["poses"][("u", "n1", W1)]
    assert pose["hidden_count"] is None and pose["hidden_s"] is None


def test_visibility_never_reaches_the_grade(gate_on, one_item, grader_says, grader_calls, applied):
    """The same answer with and without page-hidden telemetry writes the same
    evidence and calls the grader with the same arguments."""
    grader_says(correct=True, confidence=0.9)
    assert client.post(ANSWER, json=_answer(answer="its lexical scope")).status_code == 200
    pose = one_item["poses"][("u", "n1", W1)]
    pose.update(answered_at=None, claim=None, correct=None, max_rung=None)  # posed again
    hidden = _answer(answer="its lexical scope", hidden_count=9, hidden_s=120.0)
    assert client.post(ANSWER, json=hidden).status_code == 200
    first, second = applied
    assert first["graph_update"] == second["graph_update"]

    def _args(call):  # the request id differs per request; nothing else may
        return {k: v for k, v in call.items() if k != "deps"}

    assert _args(grader_calls[0]) == _args(grader_calls[1])
    assert "hidden" not in repr(grader_calls[1])


def test_shown_stamps_the_first_display_once():
    """One conditional UPDATE of the OPEN pose of this item whose served_at is
    still NULL (a reload keeps the first display)."""
    from unittest.mock import MagicMock

    from routes import learn_loop

    handle = MagicMock()
    handle.update.return_value = [{"node_id": "n1"}]
    with patch("routes.learn_loop.table", return_value=handle) as tbl:
        assert learn_loop._stamp_served("u", "n1", "q1", NOW) is True
    tbl.assert_called_with("posttest_poses")
    data = handle.update.call_args.args[0]
    filters = handle.update.call_args.kwargs["filters"]
    assert data == {"served_at": NOW.isoformat()}
    assert filters["served_at"] == "is.null" and filters["answered_at"] == "is.null"
    assert filters["question_hash"] == "eq.q1" and filters["node_id"] == "eq.n1"
    ttl = NOW - timedelta(hours=params.POSTTEST_POSE_TTL_HOURS)
    assert filters["posed_at"] == f"gte.{learn_loop._iso_z(ttl)}"
    handle.update.return_value = []
    with patch("routes.learn_loop.table", return_value=handle):
        assert learn_loop._stamp_served("u", "n1", "q1", NOW) is False


def test_the_shown_route_stamps_and_never_fails_the_student(gate_on, freeze_now):
    freeze_now(NOW)
    body = {"user_id": "u", "node_id": "n1", "question_hash": "q1"}
    with patch("routes.learn_loop._stamp_served", return_value=True) as stamp:
        r = client.post("/api/learn/loop/posttest/shown", json=body)
    assert r.status_code == 200 and r.json() == {"served": True}
    stamp.assert_called_once_with("u", "n1", "q1", NOW)
    with patch("routes.learn_loop._stamp_served", side_effect=RuntimeError("down")):
        r = client.post("/api/learn/loop/posttest/shown", json=body)
    assert r.status_code == 200 and r.json() == {"served": False}
    r = client.post("/api/learn/loop/posttest/shown", json={**body, "extra": 1})
    assert r.status_code == 422  # extra="forbid"


def test_the_shown_route_is_gated(gate_off):
    r = client.post(
        "/api/learn/loop/posttest/shown", json={"user_id": "u", "node_id": "n1", "question_hash": "q1"}
    )
    assert r.status_code == 404


# ── "a retention check is due" (GET /posttest/due) ───────────────────────────

DUE = "/api/learn/loop/posttest/due?user_id=u"


@pytest.fixture
def due_reads(tables):
    """The badge's reads, served from the same tables: the anchors function
    (one row per node with evidence) and the student's poses (every course)."""
    calls = {"anchors": 0}

    def _anchors(*, user_id=None, **_kw):
        calls["anchors"] += 1
        nodes = {r["id"]: r for r in tables["graph_nodes"]}
        rows = [
            {
                "node_id": node,
                "user_id": "u",
                "course_id": nodes[node]["course_id"],
                "concept_name": nodes[node]["concept_name"],
                "anchor_at": span.first_at.isoformat(),
            }
            for node, span in tables["spans"].items()
            if node in nodes and user_id == "u"
        ]
        return rows, False

    def _poses(user_id):
        out: dict = {}
        for (u, n, w), p in tables["poses"].items():
            if u == user_id:
                out.setdefault(n, {})[w] = dict(p)
        return out

    with (
        patch("routes.learn_loop.flag_on", return_value=True) as flag,
        patch("routes.learn_loop.posttest_anchors", side_effect=_anchors),
        patch("routes.learn_loop._read_student_poses", side_effect=_poses),
    ):
        yield SimpleNamespace(calls=calls, flag=flag)


def test_due_is_404_while_the_flag_is_off(gate_on, tables, due_reads):
    due_reads.flag.return_value = False
    assert client.get(DUE).status_code == 404
    assert due_reads.calls["anchors"] == 0
    due_reads.flag.assert_called_with("retention_due_badge", "u")


def test_due_is_404_with_the_loop_off(gate_off, tables, due_reads):
    assert client.get(DUE).status_code == 404


def test_due_says_yes_for_an_open_window_with_an_item(gate_on, tables, freeze_now, seen_revealed, due_reads):
    freeze_now(NOW)
    _one_concept(tables, item("k1", "q1"))
    r = client.get(DUE)
    assert r.status_code == 200 and r.json() == {"due": True, "course_ids": ["c"]}
    assert tables["poses"] == {} and tables["skips"] == []  # read-only: no pose, no skip


def test_nothing_due_reads_no_items(gate_on, tables, freeze_now, seen_revealed, due_reads):
    freeze_now(NOW)
    _one_concept(tables, item("k1", "q1"))
    tables["spans"] = _due("n1", first=FRESH)  # the first window has not opened
    with patch("routes.learn_loop.items_for_concepts") as items:
        assert client.get(DUE).json() == {"due": False, "course_ids": []}
    items.assert_not_called()  # the cheap path: anchors + poses only


def test_due_says_no_when_the_window_has_nothing_fresh(gate_on, tables, freeze_now, seen_revealed, due_reads):
    freeze_now(NOW)
    _one_concept(tables, item("k1", "q1"))
    seen_revealed(seen={"q1"})
    assert client.get(DUE).json() == {"due": False, "course_ids": []}


def test_an_open_pose_is_due_even_outside_a_window(gate_on, tables, freeze_now, seen_revealed, due_reads):
    freeze_now(NOW)
    _one_concept(tables, item("k1", "q1"))
    tables["spans"] = _due("n1", first=FRESH)
    _pose(tables)  # posed an hour ago, still open
    assert client.get(DUE).json() == {"due": True, "course_ids": ["c"]}


def test_due_is_cached_and_the_post_test_routes_clear_it(
    gate_on, tables, freeze_now, seen_revealed, due_reads
):
    freeze_now(NOW)
    _one_concept(tables, item("k1", "q1"))
    assert client.get(DUE).json()["due"] is True
    assert client.get(DUE).json()["due"] is True
    assert due_reads.calls["anchors"] == 1  # the second read is the cache
    _start()  # opens the pose: the student's entry is dropped
    assert client.get(DUE).json()["due"] is True  # the open pose
    assert due_reads.calls["anchors"] == 2


def test_an_unreadable_due_state_is_a_503_never_a_cached_no(gate_on, tables, freeze_now, due_reads):
    freeze_now(NOW)
    with patch("routes.learn_loop.posttest_anchors", side_effect=RuntimeError("no function")):
        assert client.get(DUE).status_code == 503
    _one_concept(tables, item("k1", "q1"))
    with patch("routes.learn_loop.seen_hashes", return_value=set()), patch(
        "routes.learn_loop.revealed_hashes", return_value=set()
    ):
        assert client.get(DUE).json()["due"] is True  # nothing was cached by the failure
