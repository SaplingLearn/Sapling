"""Missing deployed schema is actionable unavailability, not a raw database 500."""
import httpx
import pytest
from fastapi.testclient import TestClient

from db import connection
from main import app
from routes import learn_loop


@pytest.mark.parametrize("status,code", [(400, "42703"), (404, "PGRST205"), (404, "PGRST202")])
def test_missing_schema_reports_safe_migration_guidance(monkeypatch, status, code):
    def handler(request):
        return httpx.Response(status, json={"code": code, "message": "missing private table/column"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(connection, "_client", client)
        response = TestClient(app, raise_server_exceptions=False).get("/api/flashcards/user/user_test")
    assert response.status_code == 503
    assert "migrations" in response.json()["detail"]
    assert "private" not in response.json()["detail"]


def test_other_database_failures_are_not_misclassified(monkeypatch):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(403, json={"code": "42501"}))) as client:
        monkeypatch.setattr(connection, "_client", client)
        with pytest.raises(httpx.HTTPStatusError):
            connection.table("flashcards").select("id")


def test_review_queue_reports_missing_schema_without_creating_a_session(monkeypatch):
    monkeypatch.setattr(learn_loop, "_gate", lambda *args: None)
    monkeypatch.setattr(learn_loop, "_review_course", lambda *args: None)

    def load_session(*args):
        connection.table("learner_concept_state").select("node_id", limit=1)
        raise AssertionError("The missing schema must stop session creation")

    monkeypatch.setattr(learn_loop, "_review_session", load_session)
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(404, json={"code": "PGRST205"}))) as client:
        monkeypatch.setattr(connection, "_client", client)
        response = TestClient(app, raise_server_exceptions=False).get("/api/learn/loop/review/next", params={"user_id": "user_test"})
    assert response.status_code == 503
    assert "migrations" in response.json()["detail"]
