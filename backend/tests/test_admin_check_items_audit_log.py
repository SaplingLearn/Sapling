"""#866 K59: every check-item decision reaches Admin -> Audit log.

The Audit tab lists `admin_audit_log` (services/admin_audit.py::log_admin_action),
the record of who did what for every other admin write. A check-item decision
changes what students are served and, on a retire, voids their results, so an
admin investigating a mastery drop or a vanished question must find it there:
approve, retire (finished or left retire-pending) and an audit verdict (correct
confirms the key; wrong / ambiguous holds the item). Ids, hashes, enums and
counts only, never the question's text. A decision that changed nothing (a
refused approval, a decision the store did not record) writes no row.

Hermetic: the route's service calls are fakes, as in
tests/test_learning_item_quality.py (which pins the events-table audit events).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from learning import item_reports
from services.check_item_service import RetireOutcome
from tests.test_learning_item_quality import _stored

ADMIN = "/api/admin/check-items"


@pytest.fixture
def client(monkeypatch):
    import routes.admin_check_items as admin

    monkeypatch.setattr(admin, "require_admin", lambda request: None)
    monkeypatch.setattr(admin, "require_admin_recent", lambda request: None)
    monkeypatch.setattr(admin, "get_session_user_id", lambda request: "admin-1")
    monkeypatch.setattr(admin, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(admin, "relint_course_item", lambda c, q: 0)
    monkeypatch.setattr(admin, "confirm_course_item", lambda c, q: None)
    monkeypatch.setattr(admin, "get_check_item", lambda i, **k: _stored("qh-1", id=i))
    audit = []
    monkeypatch.setattr(admin, "log_admin_action", lambda **kw: audit.append(kw))
    from main import app

    c = TestClient(app)
    c.audit = audit
    return c


def _decided(monkeypatch, applied=True):
    import routes.admin_check_items as admin

    monkeypatch.setattr(
        admin.item_reports, "decide", lambda *a, **k: item_reports.Decision(previous=None, applied=applied)
    )


def _row(action, **payload):
    return {
        "actor_id": "admin-1",
        "action": f"check_item.{action}",
        "target_type": "check_item",
        "target_id": "i1",
        "payload": {"course_id": "c1", "question_hash": "qh-1", **payload},
    }


def test_an_approval_is_in_the_audit_log(client, monkeypatch):
    _decided(monkeypatch)
    assert client.post(f"{ADMIN}/i1/approve").status_code == 200
    assert client.audit == [_row("approve", restored=False, finished=True)]


def test_an_approval_whose_key_was_not_confirmed_is_in_the_audit_log_unfinished(client, monkeypatch):
    """The decision stands (the quarantine is lifted) though the 503 asks for
    the approval again: the log says who approved it and that it is unfinished."""
    import routes.admin_check_items as admin

    _decided(monkeypatch)

    def down(c, q):
        raise RuntimeError("down")

    monkeypatch.setattr(admin, "confirm_course_item", down)
    assert client.post(f"{ADMIN}/i1/approve").status_code == 503
    assert client.audit == [_row("approve", restored=False, finished=False)]


def test_a_refused_approval_writes_no_audit_row(client, monkeypatch):
    _decided(monkeypatch, applied=False)
    assert client.post(f"{ADMIN}/i1/approve").status_code == 409
    assert client.audit == []


def test_a_decision_the_store_did_not_record_writes_no_audit_row(client, monkeypatch):
    import routes.admin_check_items as admin

    def down(*a, **k):
        raise RuntimeError("rpc down")

    monkeypatch.setattr(admin.item_reports, "decide", down)
    assert client.post(f"{ADMIN}/i1/approve").status_code == 503
    assert client.post(f"{ADMIN}/i1/retire").status_code == 503
    assert client.audit == []


def test_a_retire_is_in_the_audit_log_with_what_it_voided(client, monkeypatch):
    import routes.admin_check_items as admin

    _decided(monkeypatch)
    monkeypatch.setattr(admin, "retire_course_item", lambda c, q: RetireOutcome(items=2, students=3, voided=5))
    assert client.post(f"{ADMIN}/i1/retire").status_code == 200
    assert client.audit == [_row("retire", finished=True, items=2, students=3, voided=5)]


def test_a_retire_left_pending_is_in_the_audit_log(client, monkeypatch):
    """The retire is decided (nothing serves the item, no new grade of it
    commits) even when the void fails: the log names it, unfinished."""
    import routes.admin_check_items as admin

    _decided(monkeypatch)

    def boom(c, q):
        raise RuntimeError("down")

    monkeypatch.setattr(admin, "retire_course_item", boom)
    assert client.post(f"{ADMIN}/i1/retire").status_code == 503
    assert client.audit == [_row("retire", finished=False)]


@pytest.mark.parametrize("verdict,status,held", [("correct", "verified", False), ("wrong", "held", True)])
def test_an_audit_verdict_is_in_the_audit_log(client, monkeypatch, verdict, status, held):
    import routes.admin_check_items as admin

    monkeypatch.setattr(admin, "record_item_audit", lambda item, v, *, auditor: status)
    r = client.post(f"{ADMIN}/i1/audit", json={"verdict": verdict})
    assert r.status_code == 200
    assert client.audit == [_row("audit", verdict=verdict, key_status=status, held=held, finished=True)]


def test_an_audit_verdict_not_recorded_is_in_the_audit_log_unfinished(client, monkeypatch):
    """record_item_audit writes the verdict, then the item's rows: a failure
    between them can leave the verdict recorded, so the attempt is logged."""
    import routes.admin_check_items as admin

    def down(item, v, *, auditor):
        raise RuntimeError("down")

    monkeypatch.setattr(admin, "record_item_audit", down)
    assert client.post(f"{ADMIN}/i1/audit", json={"verdict": "ambiguous"}).status_code == 503
    assert client.audit == [_row("audit", verdict="ambiguous", held=True, finished=False)]


def test_the_audit_log_carries_no_question_text(client, monkeypatch):
    import routes.admin_check_items as admin

    _decided(monkeypatch)
    monkeypatch.setattr(admin, "retire_course_item", lambda c, q: RetireOutcome(items=1, students=1, voided=1))
    client.post(f"{ADMIN}/i1/approve")
    client.post(f"{ADMIN}/i1/retire")
    flat = repr(client.audit)
    for text in ("Q?", "the base case", "A reference"):
        assert text not in flat
