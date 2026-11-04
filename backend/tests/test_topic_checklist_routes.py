"""Real signed-session guards on every checklist endpoint."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import topic_checklist as routes
from services import auth_guard
from services.session_tokens import mint_session

# Capture these before the suite's general-purpose auth bypass is applied.
REAL_REQUIRE_SELF = auth_guard.require_self
REAL_GET_SESSION = auth_guard.get_session_user_id
REAL_DECODE_SESSION = auth_guard._decode_session


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(routes, "require_self", REAL_REQUIRE_SELF)
    monkeypatch.setattr(auth_guard, "get_session_user_id", REAL_GET_SESSION)
    monkeypatch.setattr(auth_guard, "_decode_session", REAL_DECODE_SESSION)
    monkeypatch.setattr(auth_guard, "SESSION_SECRET", "checklist-test-secret")
    monkeypatch.setattr(auth_guard, "_log_permission_denied", lambda *args: None)
    monkeypatch.setattr(routes, "get_checklist", lambda *args: {"args": args})
    monkeypatch.setattr(routes, "refresh_checklist", lambda *args: {"args": args})
    monkeypatch.setattr(routes, "set_reviewed", lambda *args: {"args": args})
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/topic-checklist")
    with TestClient(app) as http:
        yield http


@pytest.mark.parametrize("method,suffix,body", [("get", "", None), ("post", "/refresh", None), ("patch", "/topics/key", {"checked": True})])
def test_authentication_and_cross_user_access(client, method, suffix, body):
    url = "/api/topic-checklist/u/courses/c" + suffix
    kwargs = {"json": body} if body else {}
    assert client.request(method, url, **kwargs).status_code == 401
    client.cookies.set("sapling_session", mint_session("other", secret="checklist-test-secret"))
    assert client.request(method, url, **kwargs).status_code == 403


@pytest.mark.parametrize("method,suffix,body,expected", [
    ("get", "", None, ["u", "c", "Fall 2026"]),
    ("post", "/refresh", None, ["u", "c", "Fall 2026"]),
    ("patch", "/topics/key", {"checked": False}, ["u", "c", "key", False, "Fall 2026"]),
])
def test_owned_requests_preserve_scope(client, method, suffix, body, expected):
    client.cookies.set("sapling_session", mint_session("u", secret="checklist-test-secret"))
    response = client.request(method, "/api/topic-checklist/u/courses/c" + suffix,
                              params={"semester": "Fall 2026"}, **({"json": body} if body else {}))
    assert response.status_code == 200 and response.json()["args"] == expected


@pytest.mark.parametrize("value", ["false", 1, None])
def test_checked_requires_a_real_boolean(client, value):
    client.cookies.set("sapling_session", mint_session("u", secret="checklist-test-secret"))
    assert client.patch("/api/topic-checklist/u/courses/c/topics/key", json={"checked": value}).status_code == 422
