"""#866 review (fix866/a-loop, A1/A4 follow-up): a review grade whose WRITE lands after
its claim went stale journals a second observation of the same served item.

claim_deadline bounds only grade_answer (elapsed 0, not counted from the
claim), so the evidence write can land past LOOP_GRADING_CLAIM_STALE_S. By
then a /review/next refresh treats the entry as not open (stale claim) and
re-serves it; `_open_item` keeps the serving's operation id, so the re-answer
and the late write share one identity and journal ONE observation.
"""
from datetime import timedelta

from learning import params
from tests import test_learning_review as base
from tests.test_learning_review import NOW, _check_item, _checked, _grade_check, _serve_check
from tests.test_learning_review_evidence_identity import _committing_journal

store, _no_review_history = base.store, base._no_review_history


def test_a_late_write_after_a_stale_reserve_journals_once(monkeypatch, store):
    from learning import review

    _checked(monkeypatch)
    journal = _committing_journal(monkeypatch)
    item = _serve_check(store)
    op_a = review.claim_item("sess-1", "n1", "ci-q", "cA", NOW)  # request A: grading...

    # ...A's grade + write outlive the claim; the student refreshes and re-answers
    later = NOW + timedelta(seconds=params.LOOP_GRADING_CLAIM_STALE_S + 1)
    _serve_check(store, now=later)  # the refresh re-serves the SAME item (stale claim)
    op_b = review.claim_item("sess-1", "n1", "ci-q", "cB", later)
    _grade_check(item, _check_item("n1", "q"), {"sr": {}}, answer="x", claim="cB",
                 operation_id=op_b, now=later)

    # A's write finally lands (its record then finds no claim) -- under op_a
    _grade_check(item, _check_item("n1", "q"), {"sr": {}}, answer="x", claim="cA",
                 operation_id=op_a)

    assert op_a == op_b, "the stale re-serve dropped the serving's operation id"
    assert len(journal) == 1, f"one served item journaled {len(journal)} observations"
