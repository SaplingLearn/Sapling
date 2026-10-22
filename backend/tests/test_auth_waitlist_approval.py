"""
Waitlist pre-approval at sign-in.

An admin approving an email under Admin → Allowlist sets
`newsletter_emails.approved_at`. Before this, nothing read that column at
sign-in, so the student still landed on /pending and had to be approved a
second time as a `users` row. The callback now promotes a pending account whose
email is approved on the waitlist.
"""
from unittest.mock import MagicMock
from urllib.parse import urlparse

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import config
import routes.auth as auth_module
import services.achievement_service as ach_module

_app = FastAPI()
_app.include_router(auth_module.router, prefix="/api/auth")

FRONTEND = "https://sapling.example"
EMAIL = "student@bu.edu"
APPROVED_AT = "2026-10-20T12:00:00+00:00"


def _tables(monkeypatch, *, users_rows, waitlist_rows=None, waitlist_error=None):
    tables: dict = {}

    def factory(name):
        if name not in tables:
            m = MagicMock(name=f"table:{name}")
            m.select.return_value = []
            m.insert.return_value = []
            m.update.return_value = []
            m.upsert.return_value = []
            tables[name] = m
        return tables[name]

    factory("users").select.return_value = users_rows
    if waitlist_error is not None:
        factory("newsletter_emails").select.side_effect = waitlist_error
    else:
        factory("newsletter_emails").select.return_value = waitlist_rows or []
    monkeypatch.setattr(auth_module, "table", factory)
    return tables


@pytest.fixture
def callback(monkeypatch):
    """Drive the real /google/callback past the Google network hops."""
    monkeypatch.setattr(config, "APP_ENV", "production")
    monkeypatch.setattr(auth_module, "_LOCAL_AUTO_APPROVE", False)
    monkeypatch.setattr(auth_module, "FRONTEND_URL", FRONTEND)
    monkeypatch.setattr(auth_module, "SESSION_SECRET", "test-secret-key")
    monkeypatch.setattr(auth_module, "GOOGLE_AVAILABLE", True)

    creds = MagicMock(token="access-tok", refresh_token="refresh-tok", expiry=None)
    flow_cls = MagicMock()
    flow_cls.from_client_config.return_value = MagicMock(credentials=creds)
    monkeypatch.setattr(auth_module, "Flow", flow_cls, raising=False)
    monkeypatch.setattr(ach_module, "check_achievements", lambda *a, **k: None)

    def _drive(*, email=EMAIL):
        userinfo = MagicMock()
        userinfo.raise_for_status.return_value = None
        userinfo.json.return_value = {
            "id": "112233", "email": email,
            "name": "Ada Lovelace", "picture": "https://example.com/a.png",
        }
        monkeypatch.setattr(httpx, "get", lambda *a, **k: userinfo)

        cookie = auth_module._encode_oauth_cookie(
            {"n": "n1", "cv": "verifier", "popup_id": None}
        )
        state = auth_module._encode_state({"action": "signin", "n": "n1"})
        client = TestClient(_app)
        client.cookies.set(auth_module.OAUTH_STATE_COOKIE, cookie)
        resp = client.get(
            f"/api/auth/google/callback?code=c&state={state}", follow_redirects=False,
        )
        assert resp.status_code in (302, 307)
        return urlparse(resp.headers["location"]).path

    return _drive


def _pending_user():
    return [{"id": "user_112233", "is_approved": False, "streak_count": 1}]


def _approved_update(tables) -> bool:
    return any(
        c.args and c.args[0] == {"is_approved": True}
        for c in tables["users"].update.call_args_list
    )


def test_waitlist_approved_email_skips_pending(callback, monkeypatch):
    tables = _tables(
        monkeypatch, users_rows=_pending_user(),
        waitlist_rows=[{"email": EMAIL, "approved_at": APPROVED_AT}],
    )
    assert callback() == "/auth/callback"
    assert _approved_update(tables)


def test_new_account_on_approved_waitlist_is_let_in(callback, monkeypatch):
    # No users row yet: the google_id lookup misses and the account is created
    # pending, then promoted by the waitlist check.
    tables = _tables(
        monkeypatch, users_rows=[],
        waitlist_rows=[{"email": EMAIL, "approved_at": APPROVED_AT}],
    )
    assert callback() == "/auth/callback"
    assert _approved_update(tables)


def test_waitlist_match_is_case_insensitive(callback, monkeypatch):
    tables = _tables(
        monkeypatch, users_rows=_pending_user(),
        waitlist_rows=[{"email": "Student@BU.edu", "approved_at": APPROVED_AT}],
    )
    assert callback() == "/auth/callback"
    assert _approved_update(tables)


def test_unapproved_waitlist_entry_stays_pending(callback, monkeypatch):
    tables = _tables(
        monkeypatch, users_rows=_pending_user(),
        waitlist_rows=[{"email": EMAIL, "approved_at": None}],
    )
    assert callback() == "/pending"
    assert not _approved_update(tables)


def test_not_on_waitlist_stays_pending(callback, monkeypatch):
    tables = _tables(monkeypatch, users_rows=_pending_user(), waitlist_rows=[])
    assert callback() == "/pending"
    assert not _approved_update(tables)


def test_wildcard_lookalike_does_not_approve(callback, monkeypatch):
    # PostgREST turns `*` into `%` inside ilike, so the DB can hand back a row
    # that only matches as a pattern. Only an exact address counts.
    tables = _tables(
        monkeypatch, users_rows=_pending_user(),
        waitlist_rows=[{"email": "*@bu.edu", "approved_at": APPROVED_AT}],
    )
    assert callback() == "/pending"
    assert not _approved_update(tables)


def test_lookup_failure_fails_closed(callback, monkeypatch):
    tables = _tables(
        monkeypatch, users_rows=_pending_user(),
        waitlist_error=RuntimeError("postgrest down"),
    )
    assert callback() == "/pending"
    assert not _approved_update(tables)


def test_already_approved_user_skips_waitlist_lookup(callback, monkeypatch):
    tables = _tables(
        monkeypatch,
        users_rows=[{"id": "user_112233", "is_approved": True, "streak_count": 1}],
    )
    assert callback() == "/auth/callback"
    tables["newsletter_emails"].select.assert_not_called()


def test_lookup_escapes_like_metacharacters(monkeypatch):
    # `_` is LIKE's single-character wildcard; unescaped, a.b_c@bu.edu would
    # also match a.bXc@bu.edu at the DB.
    tables = _tables(monkeypatch, users_rows=[], waitlist_rows=[])
    auth_module._waitlist_approved("  A.B_C@bu.edu ")
    filters = tables["newsletter_emails"].select.call_args.kwargs["filters"]
    assert filters["approved_at"] == "not.is.null"
    assert filters["or"] == '(email.ilike."a.b\\\\_c@bu.edu")'
