"""
Regression test for F7 — "First Steps" (first_login) is stuck at 100% but never
granted.

The login-streak achievements (First Steps / Week Warrior / Monthly Master) were
only ever *evaluated* at study-session end (learn.py fires
`check_achievements(user_id, "login_streak", {})` when a session closes). The
sign-in path itself never fired any achievement check, so a user who signs in —
with a login streak already at 1, i.e. progress 1/1 — but has not just finished a
study session stayed LOCKED on First Steps forever. (Document Collector works
because the upload path in documents.py fires its own check.)

The fix wires the same idempotent grant check into the real /google/callback
sign-in path. These tests drive the REAL callback (only the Google network hops
are mocked, mirroring test_auth_stub_promotion.py) and pin:

  1. an approved sign-in with streak >= 1 grants First Steps (moves it to
     user_achievements), and
  2. the grant is idempotent — an already-earned First Steps is not re-inserted.
"""
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.auth as auth_module
import services.achievement_service as ach_module

# Mount ONLY the auth router — main.py pulls in the full stack (logfire etc.).
_app = FastAPI()
_app.include_router(auth_module.router, prefix="/api/auth")

GOOGLE_ID = "112233445566778899000"
USER_ID = f"user_{GOOGLE_ID}"
EMAIL = "student@bu.edu"
FIRST_STEPS_ID = "ach-first-steps"


def _make_factory(user_rows, earned_rows, insert_sink):
    """Per-table mocks shared by BOTH auth.py and achievement_service.py.

    `users.select` returns `user_rows` for every call — the shape carries both
    `id`/`is_approved` (the google_id lookup) and `streak_count` (the
    login_streak stat lookup). `user_achievements.insert` is captured so the test
    can assert First Steps actually moved to earned.
    """
    mocks: dict = {}

    def factory(name):
        if name not in mocks:
            m = MagicMock(name=f"table:{name}")
            m.select.return_value = []
            m.insert.return_value = []
            m.update.return_value = []
            m.upsert.return_value = []
            mocks[name] = m
        return mocks[name]

    factory("users").select.return_value = user_rows
    # First Steps' seeded trigger: login_streak, threshold 1.
    factory("achievement_triggers").select.return_value = [
        {
            "id": "trg-1",
            "achievement_id": FIRST_STEPS_ID,
            "trigger_type": "login_streak",
            "trigger_threshold": 1,
        },
    ]
    factory("user_achievements").select.return_value = earned_rows

    def _capture_insert(payload):
        insert_sink.append(payload)
        return [{}]

    factory("user_achievements").insert.side_effect = _capture_insert
    factory("achievements").select.return_value = [{
        "slug": "first_login", "name": "First Steps", "xp_reward": 0, "status": "live",
    }]
    factory("achievement_cosmetics").select.return_value = []
    return factory, mocks


@pytest.fixture
def drive_callback(monkeypatch):
    """Drive the real /google/callback past the two Google network hops."""
    monkeypatch.setattr(auth_module, "SESSION_SECRET", "test-secret-key")
    monkeypatch.setattr(auth_module, "GOOGLE_AVAILABLE", True)

    creds = MagicMock(token="access-tok", refresh_token="refresh-tok", expiry=None)
    flow = MagicMock(credentials=creds)
    fake_flow_cls = MagicMock()
    fake_flow_cls.from_client_config.return_value = flow
    monkeypatch.setattr(auth_module, "Flow", fake_flow_cls, raising=False)

    userinfo = MagicMock()
    userinfo.raise_for_status.return_value = None
    userinfo.json.return_value = {
        "id": GOOGLE_ID,
        "email": EMAIL,
        "name": "Ada Lovelace",
        "picture": "https://example.com/a.png",
    }
    # auth.py does `import httpx` inside the function, so patch the module attr.
    monkeypatch.setattr(httpx, "get", lambda *a, **k: userinfo)

    def _drive(user_rows, earned_rows):
        insert_sink: list = []
        factory, mocks = _make_factory(user_rows, earned_rows, insert_sink)
        # Both modules resolve `table` independently; share one factory so the
        # achievement check sees the same mocked DB the callback wrote to.
        monkeypatch.setattr(auth_module, "table", factory)
        monkeypatch.setattr(ach_module, "table", factory)

        nonce = "nonce-xyz"
        cookie = auth_module._encode_oauth_cookie(
            {"n": nonce, "cv": "verifier", "popup_id": None}
        )
        state = auth_module._encode_state({"action": "signin", "n": nonce})
        client = TestClient(_app)
        client.cookies.set(auth_module.OAUTH_STATE_COOKIE, cookie)
        resp = client.get(
            f"/api/auth/google/callback?code=auth-code&state={state}",
            follow_redirects=False,
        )
        return resp, mocks, insert_sink

    return _drive


def test_first_steps_granted_on_approved_signin(drive_callback):
    """An approved sign-in with a login streak of 1 must grant First Steps."""
    resp, _mocks, insert_sink = drive_callback(
        user_rows=[{"id": USER_ID, "is_approved": True, "streak_count": 1}],
        earned_rows=[],
    )
    # Sign-in still succeeds (redirect to the frontend callback, not /pending).
    assert resp.status_code in (302, 307)
    assert "/pending" not in resp.headers["location"]

    granted = [p["achievement_id"] for p in insert_sink]
    assert FIRST_STEPS_ID in granted, (
        "First Steps must be granted on an approved sign-in — the login path "
        "never fired the login_streak achievement check (F7)."
    )


def test_first_steps_grant_is_idempotent(drive_callback):
    """A already-earned First Steps must not be re-inserted on the next sign-in."""
    resp, _mocks, insert_sink = drive_callback(
        user_rows=[{"id": USER_ID, "is_approved": True, "streak_count": 1}],
        earned_rows=[{"achievement_id": FIRST_STEPS_ID}],
    )
    assert resp.status_code in (302, 307)

    granted = [p["achievement_id"] for p in insert_sink]
    assert FIRST_STEPS_ID not in granted, (
        "check_achievements dedups against user_achievements, so an already-earned "
        "achievement must never be inserted twice (award-once)."
    )


def test_signin_still_succeeds_when_achievement_check_raises(drive_callback, monkeypatch):
    """The grant is best-effort: a failure in the check must not break sign-in."""

    def _boom(*_a, **_k):
        raise RuntimeError("achievement backend down")

    monkeypatch.setattr(ach_module, "check_achievements", _boom)

    resp, _mocks, _sink = drive_callback(
        user_rows=[{"id": USER_ID, "is_approved": True, "streak_count": 1}],
        earned_rows=[],
    )
    assert resp.status_code in (302, 307)
    assert "/pending" not in resp.headers["location"]
