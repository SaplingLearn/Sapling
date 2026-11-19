"""The daily review's evidence identity and rating (#866 review A3, A4, A6).

#866 review A4: a review answer's evidence carries its SERVING's operation id — minted
from the serving's first answer claim and kept when a claim is released — so
an answer sent again after an ambiguous acknowledgment journals at most one
observation: the commit replays the first, or refuses another grade under the
same identity, and then the committed outcome stands. #866 review A6: the rating returned
is the one the journal scheduled (after the help floor). The route maps a
persistence failure to 503 (it was an unmapped 500).

On the hermetic seams of tests/test_learning_review.py: the in-memory CAS
store, a mock `table`, the grade_answer stand-in.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from learning import params
from learning.evidence import PlanningPersistenceUnavailable
from learning.evidence_transaction import EvidenceTransactionConflict
from tests import test_learning_review as base
from tests.test_learning_review import (
    COURSE,
    NOW,
    REVIEW,
    USER,
    _check_answer_seams,
    _check_item,
    _checked,
    _deps,
    _grade,
    _grade_check,
    _loop,
    _opened,
    _serve_check,
    _session,
    _sid,
)

# the review suite's fixtures (its two autouse ones apply here too)
client, store, _no_review_history = base.client, base.store, base._no_review_history

_T = NOW.timestamp()


def _committing_journal(monkeypatch, *, ack_lost_first: bool = False):
    """apply_graph_update as the evidence transaction behaves for one
    operation id: the first input under an id commits; the SAME input again
    replays; ANOTHER input under it is refused (EvidenceTransactionConflict).
    `ack_lost_first`: the first commit lands but its acknowledgment is lost
    (PlanningPersistenceUnavailable). Returns the journal {op: evidence}."""
    from learning import review

    journal: dict[str, dict] = {}
    armed = {"lost": ack_lost_first}

    def apply(user_id, update, **kw):
        (ev,) = update["evidence"]
        op = ev.get("operation_id")
        assert op, "review evidence carries its serving's operation id"
        if op in journal:
            if journal[op] != ev:
                raise EvidenceTransactionConflict("Evidence operation input changed")
            return []
        journal[op] = dict(ev)
        if armed["lost"]:
            armed["lost"] = False
            raise PlanningPersistenceUnavailable("Evidence commit acknowledgment unavailable")
        return []

    def committed(user_id, op):
        ev = journal.get(op)
        if ev is None:
            return None
        return [{"node_id": ev["node_id"], "question_hash": ev["question_hash"], "channel": ev["channel"],
                 "correct": ev["correct"], "idk": False, "max_rung": ev["max_rung"]}]

    monkeypatch.setattr(review, "apply_graph_update", apply)
    monkeypatch.setattr(review, "committed_outcome", committed)
    return journal


def test_a_serving_keeps_one_operation_id_across_released_claims(monkeypatch, store):
    from learning import review

    _checked(monkeypatch, unavailable=True)  # the first answer writes nothing
    item = _serve_check(store)
    first = review.claim_item("sess-1", "n1", "ci-q", "c1", NOW)
    assert first == review.review_operation_id("c1")
    _grade_check(item, _check_item("n1", "q"), {"sr": {}}, answer="x", claim="c1", operation_id=first)
    assert "claim" not in store.state.extra["open"]["n1"]
    assert review.claim_item("sess-1", "n1", "ci-q", "c2", NOW) == first  # same serving, same id
    calls, applied = _checked(monkeypatch)
    _grade_check(item, _check_item("n1", "q"), {"sr": {}}, answer="x", claim="c2", operation_id=first)
    assert applied[0]["evidence"][0]["operation_id"] == first
    later = NOW + timedelta(minutes=5)
    _serve_check(store, item_id="ci-q2", qh="q2", now=later)  # a new serving after the grade
    assert review.claim_item("sess-1", "n1", "ci-q2", "c3", later) == review.review_operation_id("c3")


def test_a_flashcard_claim_mints_no_operation(store):
    from learning import review

    card = MagicMock(kind="flashcard", id="f1")
    store.state.extra["open"] = {"fc:f1": {"item_id": "f1", "served_at": _T}}
    assert review.claim_item("s", review.sr_key(card), "f1", "c1", NOW) is None
    assert "operation_id" not in store.state.extra["open"]["fc:f1"]


def test_an_answer_sent_again_after_a_lost_acknowledgment_counts_once(monkeypatch, store):
    """The first write lands but its acknowledgment is lost: nothing is recorded
    and the claim is released (503). The answer is sent again and graded
    WRONG this time: the commit refuses another grade under the serving's id,
    so the committed (correct) outcome stands — one observation, recorded once."""
    from learning import review

    _checked(monkeypatch)
    journal = _committing_journal(monkeypatch, ack_lost_first=True)
    item = _serve_check(store)
    op = review.claim_item("sess-1", "n1", "ci-q", "c1", NOW)
    with pytest.raises(PlanningPersistenceUnavailable):
        _grade_check(item, _check_item("n1", "q"), {"sr": {}}, answer="x", claim="c1", operation_id=op)
    entry = store.state.extra["open"]["n1"]
    assert "claim" not in entry and "graded_at" not in entry and entry["operation_id"] == op
    assert list(journal) == [op]

    grade, _ = _grade(correct=False)
    monkeypatch.setattr(review, "grade_answer", grade)
    assert review.claim_item("sess-1", "n1", "ci-q", "c2", NOW) == op
    out = _grade_check(item, _check_item("n1", "q"), {"sr": {}}, answer="y", claim="c2", operation_id=op)
    assert out.correct is True and out.hint is None  # the committed grade, not the retry's
    assert out.rating == 3  # Good: free_response, correct, rung 0
    assert list(journal) == [op]  # one observation
    assert store.state.extra["open"]["n1"]["graded_at"] == _T
    with pytest.raises(review.ReviewClaimRefused):
        review.claim_item("sess-1", "n1", "ci-q", "c3", NOW)


def test_the_same_grade_sent_again_replays(monkeypatch, store):
    from learning import review

    _checked(monkeypatch)
    journal = _committing_journal(monkeypatch, ack_lost_first=True)
    item = _serve_check(store)
    op = review.claim_item("sess-1", "n1", "ci-q", "c1", NOW)
    with pytest.raises(PlanningPersistenceUnavailable):
        _grade_check(item, _check_item("n1", "q"), {"sr": {}}, answer="x", claim="c1", operation_id=op)
    review.claim_item("sess-1", "n1", "ci-q", "c2", NOW)
    out = _grade_check(item, _check_item("n1", "q"), {"sr": {}}, answer="x", claim="c2", operation_id=op)
    assert out.correct is True and out.hint == "Nice." and len(journal) == 1


def test_a_real_refusal_is_not_taken_for_an_earlier_commit(monkeypatch, store):
    """A refusal with no committed observation of this serving (the node is gone,
    say) is not an earlier grade: it propagates and the claim is released."""
    from learning import review

    _checked(monkeypatch)
    monkeypatch.setattr(
        review, "apply_graph_update",
        MagicMock(side_effect=EvidenceTransactionConflict("Evidence target ownership/course unavailable")),
    )
    monkeypatch.setattr(review, "committed_outcome", lambda user_id, op: None)
    item = _serve_check(store)
    op = review.claim_item("sess-1", "n1", "ci-q", "c1", NOW)
    with pytest.raises(EvidenceTransactionConflict):
        _grade_check(item, _check_item("n1", "q"), {"sr": {}}, answer="x", claim="c1", operation_id=op)
    assert "claim" not in store.state.extra["open"]["n1"]


@pytest.mark.parametrize("floor,rating", [(0, 3), (1, 2), (params.RUNG_NO_CREDIT_MIN, 1)])
def test_the_rating_is_the_one_the_journal_scheduled(monkeypatch, store, floor, rating):
    """#866 review A6: the help floor raises the evidence's rung before the write;
    the answer's rating is the journaled one (Good / Hard / Again), never rung 0's."""
    calls, applied = _checked(monkeypatch)

    def refloor(ev):
        ev["max_rung"] = max(int(ev.get("max_rung") or 0), floor)

    item = _serve_check(store)
    out = _grade_check(item, _check_item("n1", "q"), {"sr": {}}, answer="x", refloor=refloor)
    assert applied[0]["evidence"][0]["max_rung"] == floor
    assert out.correct is True and out.rating == rating


@pytest.mark.parametrize("failure", ["unavailable", "deadline"])
def test_review_answer_maps_a_persistence_failure_to_503(client, monkeypatch, store, failure):
    """It was an unmapped 500. Nothing is recorded, the claim is released, and
    the same answer may be sent again under the serving's operation id."""
    from learning import review
    from learning.claim_deadline import GradeDeadlineExceeded

    _session(monkeypatch)
    _check_answer_seams(monkeypatch, _check_item("n-due", "qh-1"), deps=_deps)
    _checked(monkeypatch)
    error = (PlanningPersistenceUnavailable("Evidence transaction unavailable") if failure == "unavailable"
             else GradeDeadlineExceeded("the grade outlived its claim"))
    monkeypatch.setattr(review, "apply_graph_update", MagicMock(side_effect=error))
    _opened(store, "n-due", "ci-qh-1")
    body = {"user_id": USER, "session_id": _sid(), "course_id": COURSE, "kind": "check",
            "item_id": "ci-qh-1", "answer": "x"}
    with _loop():
        r = client.post(f"{REVIEW}/answer", json=body)
    assert r.status_code == 503, r.text
    entry = store.state.extra["open"]["n-due"]
    assert "claim" not in entry and "graded_at" not in entry and entry["operation_id"]
