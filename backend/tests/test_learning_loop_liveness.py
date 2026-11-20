"""Loop liveness: a grade that cannot be finished never holds the session.

#866 review A1 (a slow grade plus "Check me"), A2 (a permanent evidence refusal)
and #866 review A9 ("Check me" over concepts with no check question), on the same
route seams as tests/test_learning_grade_recovery.py: the real compare-and-set
store over an in-memory document, the real checkpoint seal, no DB, no model.
"""

import asyncio
import json

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from learning import grade_checkpoint
from learning.claim_deadline import GRADE_DEADLINE_S, GradeDeadlineExceeded, within_grade_deadline
from learning.evidence import PlanningPersistenceUnavailable
from learning.evidence_transaction import EvidenceTransactionConflict
from learning.params import LOOP_GRADING_CLAIM_STALE_S
from models import LoopCheckAnswerBody
from tests import test_learn_loop_routes as routes
from tests.split_patches import patch_loop
import services.loop.checkpoint
import services.loop.grading
import services.loop.state

client = routes.client
gate_on, seams, no_rate_limit = routes.gate_on, routes.seams, routes.no_rate_limit
NEXT = "/api/learn/loop/check/next"
BODY = {"session_id": "s1", "user_id": "u1"}
STALE_AT = routes.NOW - LOOP_GRADING_CLAIM_STALE_S - 1


def submit(answer="The base case returns 1"):
    return asyncio.run(services.loop.grading._grade_submission(
        LoopCheckAnswerBody(**routes._answer(answer=answer)),
        Request({"type": "http", "headers": []}), loop_on=True,
    ))


def _qh2(user_id, course_id, st, *, now):
    """`_activate_next_item` standing in for the next servable item, qh-2."""
    st["current"] = "qh-2"
    st.setdefault("steps", {})["qh-2"] = routes._step(first_shown_at=now)
    return "qh-2"


def _in_flight(doc) -> bool:
    return services.loop.state._grading_in_flight(doc, routes.NOW)


def _abandoned(entry: dict, reason: str) -> None:
    assert entry["grading_superseded"] is True and entry["grading_abandoned"] == reason
    assert "grading_claim" not in entry and "grading_claim_at" not in entry
    assert grade_checkpoint.KEY not in entry and entry.get("graded_at") is None


# ── #866 review A1: a slow grade plus "Check me" ──────────────────────────────


def test_a_late_grade_after_check_me_moved_on_cannot_wedge_the_session(gate_on, seams):
    """The grader outlives its claim; meanwhile "Check me" moves past the stale
    claim to qh-2. The late grade finds its check closed: no checkpoint on the
    old step, no evidence, a 409 — and nothing is left that can hold the
    session (resubmit, /check/next, close and chat all keep working)."""
    moved = {}

    async def slow(item, answer, **kw):
        seams.store["doc"]["steps"]["qh-1"]["grading_claim_at"] = STALE_AT
        with patch_loop("_activate_next_item", side_effect=_qh2):
            moved["next"] = client.post(NEXT, json=BODY)
        return routes.CORRECT

    seams.grade.side_effect = slow
    with pytest.raises(HTTPException) as late:
        submit()
    assert moved["next"].status_code == 200, moved["next"].text
    assert moved["next"].json()["check"] is not None
    assert late.value.status_code == 409 and late.value.detail == services.loop.checkpoint._MOVED_ON
    doc = seams.store["doc"]
    _abandoned(doc["steps"]["qh-1"], "moved_past")
    assert doc["steps"]["qh-1"]["discarded_grade_operation_id"]
    assert doc["current"] == "qh-2"
    seams.flush.assert_not_called()
    assert not _in_flight(doc)
    with pytest.raises(HTTPException) as again:  # the old item is never graded again
        submit()
    assert again.value.status_code == 409
    seams.grade.assert_awaited_once()
    services.loop.state._teaching_open("s1", "u1")  # chat is not held by a pending grade


def test_check_me_gives_up_a_stale_claim_it_moves_past(gate_on, seams):
    seams.store["doc"]["steps"]["qh-1"].update(grading_claim="dead", grading_claim_at=STALE_AT)
    seams.store["doc"].update(concept="node-1")
    with patch_loop("_activate_next_item", side_effect=_qh2):
        r = client.post(NEXT, json=BODY)
    assert r.status_code == 200 and r.json()["check"] is not None
    entry = seams.store["doc"]["steps"]["qh-1"]
    _abandoned(entry, "moved_past")
    assert entry["discarded_grade_operation_id"] == "dead"


def test_a_late_save_on_a_step_no_longer_current_releases_its_claim(gate_on, seams):
    """A withdrawn item (or any move) left the claimed step non-current but
    still claimed: the save gives the claim up in its own write and refuses."""

    async def withdrawn_meanwhile(item, answer, **kw):
        seams.store["doc"]["current"] = None
        return routes.CORRECT

    seams.grade.side_effect = withdrawn_meanwhile
    with pytest.raises(HTTPException) as late:
        submit()
    assert late.value.status_code == 409 and late.value.detail == services.loop.checkpoint._MOVED_ON
    _abandoned(seams.store["doc"]["steps"]["qh-1"], "moved_past")
    seams.flush.assert_not_called()
    assert not _in_flight(seams.store["doc"])


def test_a_saved_grade_left_on_a_moved_past_step_never_holds_the_session(gate_on, seams):
    """A checkpoint an older build saved on a step that is no longer current can
    never be flushed: it holds neither the close nor chat, and its retry
    closes it for good instead of a 409 forever."""
    seams.flush.side_effect = PlanningPersistenceUnavailable("DB down")
    with pytest.raises(HTTPException):
        submit()
    seams.store["doc"]["current"] = None  # moved past under the saved grade
    assert grade_checkpoint.KEY in seams.store["doc"]["steps"]["qh-1"]
    assert not _in_flight(seams.store["doc"])
    seams.flush.side_effect = None
    seams.flush.reset_mock()
    with pytest.raises(HTTPException) as retry:
        submit()
    assert retry.value.status_code == 409 and retry.value.detail == services.loop.checkpoint._MOVED_ON
    _abandoned(seams.store["doc"]["steps"]["qh-1"], "moved_past")
    seams.flush.assert_not_called()
    seams.grade.assert_awaited_once()


def test_a_grade_runs_only_inside_its_claim():
    """The bound a grading surface puts around its claimed run: cancelled and
    GradeDeadlineExceeded past GRADE_DEADLINE_S (below the claim's stale age,
    leaving room for the save); other errors pass through untouched."""
    assert 0 < GRADE_DEADLINE_S < LOOP_GRADING_CLAIM_STALE_S

    async def run(elapsed, body):
        async with within_grade_deadline(elapsed):
            return await body()

    async def quick():
        return "graded"

    async def forever():
        await asyncio.sleep(3600)

    async def own_timeout():
        raise TimeoutError("the body's own")

    assert asyncio.run(run(0, quick)) == "graded"
    with pytest.raises(GradeDeadlineExceeded):
        asyncio.run(run(GRADE_DEADLINE_S - 0.01, forever))
    with pytest.raises(GradeDeadlineExceeded):
        asyncio.run(run(GRADE_DEADLINE_S + 5, forever))  # already past it
    with pytest.raises(TimeoutError, match="the body's own"):
        asyncio.run(run(0, own_timeout))


_SLOW_GRADE_503 = "Checking your answer took too long, so nothing was recorded. Please submit it again."


def test_a_check_grade_that_outlives_its_deadline_is_a_503_that_records_nothing(
    gate_on, seams, monkeypatch,
):
    """#866 review A1: the check grader runs inside `within_grade_deadline`. A
    grade that outlives it is cancelled: 503, nothing saved (no checkpoint, no
    grade, no evidence), the claim released — and the same answer grades on
    the next submit."""
    import learning.claim_deadline as deadline

    async def slow(item, answer, **kw):
        await asyncio.sleep(5)
        return routes.CORRECT

    monkeypatch.setattr(deadline, "GRADE_DEADLINE_S", 0.05)
    seams.grade.side_effect = slow
    with pytest.raises(HTTPException) as late:
        submit()
    assert late.value.status_code == 503 and late.value.detail == _SLOW_GRADE_503
    entry = seams.store["doc"]["steps"]["qh-1"]
    assert "grading_claim" not in entry and "grading_claim_at" not in entry
    assert grade_checkpoint.KEY not in entry and entry.get("graded_at") is None
    seams.flush.assert_not_called()
    assert not _in_flight(seams.store["doc"])
    seams.grade.side_effect = None  # the grader answers in time: the same answer grades
    assert submit().kind == "feedback"
    assert seams.store["doc"]["steps"]["qh-1"]["graded_at"] is not None
    seams.flush.assert_called_once()


# ── #866 review A2: a permanent evidence refusal ──────────────────────────────


def _abandoned_session(seams, reason: str) -> None:
    doc = seams.store["doc"]
    _abandoned(doc["steps"]["qh-1"], reason)
    assert doc["current"] is None and "goal_observation" not in doc["steps"]["qh-1"]
    assert not _in_flight(doc) and services.loop.state._pending_grade(doc) is None
    assert not doc.get("checks_since_rating")
    assert "base case" not in json.dumps(doc)


def test_a_refused_flush_is_abandoned_not_retried_forever(gate_on, seams):
    """EvidenceTransactionConflict (the node is gone or outside the course, the
    operation's input or owner changed) can never succeed on a retry: the
    claim is released and the checkpoint cleared in one write, the reason is
    kept, nothing is written, and the session goes on."""
    seams.flush.side_effect = EvidenceTransactionConflict("Evidence target ownership/course unavailable")
    with pytest.raises(HTTPException) as error:
        submit()
    assert error.value.status_code == 409
    assert error.value.detail == services.loop.checkpoint._ABANDONED_DETAIL
    _abandoned_session(seams, "evidence_refused")
    with pytest.raises(HTTPException) as again:  # a retry grades and writes nothing
        submit()
    assert again.value.status_code in (404, 409)
    seams.grade.assert_awaited_once()
    assert seams.flush.call_count == 1
    seams.store["doc"].update(concept="node-1")
    with patch_loop("_activate_next_item", side_effect=_qh2):
        r = client.post(NEXT, json=BODY)
    assert r.status_code == 200 and r.json()["check"] is not None  # "Check me" moves on


def test_a_saved_grade_refused_on_recovery_is_abandoned(gate_on, seams):
    """A saved grade whose replay is refused for good (here: on a cold retry)
    leaves the session too, instead of 503 on every retry."""
    seams.flush.side_effect = PlanningPersistenceUnavailable("DB down")
    with pytest.raises(HTTPException) as down:
        submit()
    assert down.value.status_code == 503
    assert grade_checkpoint.KEY in seams.store["doc"]["steps"]["qh-1"]
    seams.flush.side_effect = EvidenceTransactionConflict("Evidence operation input changed")
    with pytest.raises(HTTPException) as error:
        submit("a retry's text is never graded")
    assert error.value.status_code == 409
    _abandoned_session(seams, "evidence_refused")
    seams.grade.assert_awaited_once()


@pytest.mark.parametrize("receipt", ["foreign_owner", "other_course"])
def test_a_receipt_that_is_not_this_grade_is_abandoned(gate_on, seams, receipt):
    original = seams.receipt.side_effect

    def read(user_id, operation):
        if receipt == "foreign_owner":
            raise EvidenceTransactionConflict("Evidence operation ownership changed")
        return {**original(user_id, operation), "course_id": "another-course"}

    seams.receipt.side_effect = read
    with pytest.raises(HTTPException) as error:
        submit()
    assert error.value.status_code == 409
    _abandoned_session(seams, "receipt_mismatch")


def test_a_missing_receipt_right_after_the_flush_is_retried(gate_on, seams):
    """Missing straight after a successful flush is a read that has not caught
    up, not a refusal: 503, the saved grade kept for the retry."""
    original = seams.receipt.side_effect
    seams.receipt.side_effect = lambda user_id, operation: None
    with pytest.raises(HTTPException) as error:
        submit()
    assert error.value.status_code == 503
    assert grade_checkpoint.KEY in seams.store["doc"]["steps"]["qh-1"]
    seams.receipt.side_effect = original
    assert submit().kind == "feedback"
    seams.grade.assert_awaited_once()


# ── #866 review A9: "Check me" over concepts with no check question ───────────


def test_check_me_names_the_concepts_it_could_not_check(gate_on, seams):
    """A plan whose concepts have no check item: "Check me" at concept 1 of 3
    runs the cursor off the end. plan_done stays as it was; the concepts it
    passed without a graded check are named, in plan order."""
    seams.store["doc"] = routes._plan_state(plan={"approved": ["n1", "n2", "n3"], "cursor": 0}, concept="n1")
    seams.list_items.return_value = []
    r = client.post(NEXT, json=BODY)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["check"] is None and out["plan_done"] is True
    assert out["checks_unavailable_node_ids"] == ["n1", "n2", "n3"]


def test_a_plan_finished_with_graded_checks_names_none(gate_on, seams):
    graded = {
        f"qh-{n}": routes._step(node_id=n, graded_at=routes.NOW - 5, feedback_given=True)
        for n in ("n1", "n2")
    }
    seams.store["doc"] = routes._plan_state(
        plan={"approved": ["n1", "n2"], "cursor": 2, "done": True}, steps=graded, current=None,
    )
    seams.store["doc"].pop("concept")
    r = client.post(NEXT, json=BODY)
    assert r.status_code == 200, r.text
    assert r.json()["plan_done"] is True and r.json()["checks_unavailable_node_ids"] == []


def test_only_the_unchecked_concepts_are_named(gate_on, seams):
    graded = {"qh-a": routes._step(node_id="n1", graded_at=routes.NOW - 5, feedback_given=True)}
    seams.store["doc"] = routes._plan_state(
        plan={"approved": ["n1", "n2", "n3"], "cursor": 1}, steps=graded, concept="n2", current=None,
    )
    seams.list_items.return_value = []
    r = client.post(NEXT, json=BODY)
    assert r.json()["check"] is None
    assert r.json()["checks_unavailable_node_ids"] == ["n2", "n3"]
