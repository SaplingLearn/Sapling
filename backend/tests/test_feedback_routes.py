"""Tests for routes/feedback.py POST endpoints after the 0026_ops schema change.

0026_ops.sql dropped the SERIAL integer PKs on `feedback` and `issue_reports`
and recreated them with `TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text`, plus
real FKs to `users(id)` (and `sessions(id)` for feedback). Following the repo
convention (services/academics.py, services/graph_service.py), the routes now
hand-build the text PK with `str(uuid.uuid4())` rather than leaning on the DB
default, so the insert shape is explicit and consistent with the rest of the
redesign.

These tests patch `routes.feedback.table` with a MagicMock-per-table factory
that records `.insert()` payloads — the same hermetic pattern as
tests/test_academics.py.
"""
import uuid
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _factory(recorder):
    """Return a `table(name)` stand-in that records `.insert()` payloads."""
    cache: dict = {}

    def make(name):
        if name in cache:
            return cache[name]
        m = MagicMock(name=f"table({name})")

        def _insert(data):
            recorder.append((name, data))
            return [data]

        m.insert.side_effect = _insert
        cache[name] = m
        return m

    return make


def _is_uuid(value):
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


class TestSubmitFeedback:
    def test_inserts_with_text_uuid_pk(self):
        recorded: list = []
        with patch("routes.feedback.table", side_effect=_factory(recorded)):
            r = client.post(
                "/api/feedback",
                json={
                    "user_id": "user_andres",
                    "type": "session",
                    "rating": 5,
                    "selected_options": ["clear", "fast"],
                    "comment": "great",
                    "session_id": "sess_1",
                    "topic": "calculus",
                },
            )
        assert r.status_code == 200
        assert r.json() == {"ok": True}

        assert len(recorded) == 1
        name, data = recorded[0]
        assert name == "feedback"
        # Text PK is hand-built and parses as a UUID (no SERIAL default reliance).
        assert _is_uuid(data["id"])

    def test_insert_payload_round_trips_body_fields(self):
        recorded: list = []
        with patch("routes.feedback.table", side_effect=_factory(recorded)):
            client.post(
                "/api/feedback",
                json={
                    "user_id": "user_andres",
                    "type": "session",
                    "rating": 4,
                    "selected_options": ["clear"],
                    "comment": "ok",
                    "session_id": "sess_42",
                    "topic": "algebra",
                },
            )
        _name, data = recorded[0]
        assert data["user_id"] == "user_andres"
        assert data["type"] == "session"
        assert data["rating"] == 4
        assert data["selected_options"] == ["clear"]
        assert data["comment"] == "ok"
        assert data["session_id"] == "sess_42"
        assert data["topic"] == "algebra"
        # Regression guard: the insert must carry exactly these keys.
        assert set(data.keys()) == {
            "id", "user_id", "type", "rating",
            "selected_options", "comment", "session_id", "topic",
        }

    def test_session_id_may_be_null(self):
        # session_id FK is ON DELETE SET NULL and the column is nullable; a
        # global (non-session) feedback submission carries session_id=None.
        recorded: list = []
        with patch("routes.feedback.table", side_effect=_factory(recorded)):
            r = client.post(
                "/api/feedback",
                json={"user_id": "user_andres", "type": "global", "rating": 3},
            )
        assert r.status_code == 200
        _name, data = recorded[0]
        assert data["session_id"] is None
        assert _is_uuid(data["id"])


class TestSubmitIssueReport:
    def test_inserts_with_text_uuid_pk(self):
        recorded: list = []
        with patch("routes.feedback.table", side_effect=_factory(recorded)):
            r = client.post(
                "/api/issue-reports",
                json={
                    "user_id": "user_andres",
                    "topic": "bug",
                    "description": "something broke",
                    "screenshot_urls": ["user_andres/a.png"],
                },
            )
        assert r.status_code == 200
        assert r.json() == {"ok": True}

        assert len(recorded) == 1
        name, data = recorded[0]
        assert name == "issue_reports"
        assert _is_uuid(data["id"])
        assert data["user_id"] == "user_andres"
        assert data["topic"] == "bug"
        assert data["description"] == "something broke"
        assert data["screenshot_urls"] == ["user_andres/a.png"]
        assert set(data.keys()) == {
            "id", "user_id", "topic", "description", "screenshot_urls",
        }
