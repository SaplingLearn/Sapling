"""
Waitlist pre-approval at sign-in.

An admin approving an email under Admin → Allowlist sets
`newsletter_emails.approved_at`. Before this, nothing read that column at
sign-in, so the student still landed on /pending and had to be approved a
second time as a `users` row. The callback now promotes a pending account whose
email is approved on the waitlist, and stamps the waitlist row as joined once
an approved account gets in (users.email is encrypted, so sign-in is the only
place the two can be matched).
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

    def _drive(*, email=EMAIL, popup_id=None, full=False):
        userinfo = MagicMock()
        userinfo.raise_for_status.return_value = None
        userinfo.json.return_value = {
            "id": "112233", "email": email,
            "name": "Ada Lovelace", "picture": "https://example.com/a.png",
        }
        monkeypatch.setattr(httpx, "get", lambda *a, **k: userinfo)

        cookie = auth_module._encode_oauth_cookie(
            {"n": "n1", "cv": "verifier", "popup_id": popup_id}
        )
        state = auth_module._encode_state({"action": "signin", "n": "n1"})
        client = TestClient(_app)
        client.cookies.set(auth_module.OAUTH_STATE_COOKIE, cookie)
        resp = client.get(
            f"/api/auth/google/callback?code=c&state={state}", follow_redirects=False,
        )
        assert resp.status_code in (302, 307)
        location = resp.headers["location"]
        return location if full else urlparse(location).path

    return _drive


def _pending_user():
    return [{"id": "user_112233", "is_approved": False, "streak_count": 1}]


def _joined_update(tables):
    for c in tables["newsletter_emails"].update.call_args_list:
        if "joined_at" in c.args[0]:
            return c
    return None


def _approved_update(tables) -> bool:
    return any(
        c.args and c.args[0] == {"is_approved": True}
        for c in tables["users"].update.call_args_list
    )


def test_waitlist_approved_email_skips_pending(callback, monkeypatch):
    tables = _tables(
        monkeypatch, users_rows=_pending_user(),
        waitlist_rows=[{"id": "w1", "email": EMAIL, "approved_at": APPROVED_AT}],
    )
    assert callback() == "/auth/callback"
    assert _approved_update(tables)
    joined = _joined_update(tables)
    assert joined.args[0]["joined_user_id"] == "user_112233"
    # Only an unstamped row: a repeat sign-in never moves joined_at.
    assert joined.kwargs["filters"] == {"id": "eq.w1", "joined_at": "is.null"}


def test_new_account_on_approved_waitlist_is_let_in(callback, monkeypatch):
    # No users row yet: the account is created already approved, because the
    # waitlist said yes before anything was stored.
    tables = _tables(
        monkeypatch, users_rows=[],
        waitlist_rows=[{"id": "w1", "email": EMAIL, "approved_at": APPROVED_AT}],
    )
    assert callback() == "/auth/callback"
    assert tables["users"].upsert.call_args.args[0]["is_approved"] is True


def test_waitlist_match_is_case_insensitive(callback, monkeypatch):
    tables = _tables(
        monkeypatch, users_rows=_pending_user(),
        waitlist_rows=[{"id": "w1", "email": "Student@BU.edu", "approved_at": APPROVED_AT}],
    )
    assert callback() == "/auth/callback"
    assert _approved_update(tables)


def test_unapproved_waitlist_entry_stays_pending(callback, monkeypatch):
    tables = _tables(
        monkeypatch, users_rows=_pending_user(),
        waitlist_rows=[{"id": "w1", "email": EMAIL, "approved_at": None}],
    )
    assert callback() == "/pending"
    assert not _approved_update(tables)
    assert _joined_update(tables) is None  # pending isn't joined


def test_not_on_waitlist_stays_pending(callback, monkeypatch):
    tables = _tables(monkeypatch, users_rows=_pending_user(), waitlist_rows=[])
    assert callback() == "/pending"
    assert not _approved_update(tables)


def test_wildcard_lookalike_does_not_approve(callback, monkeypatch):
    # PostgREST turns `*` into `%` inside ilike, so the DB can hand back a row
    # that only matches as a pattern. Only an exact address counts.
    tables = _tables(
        monkeypatch, users_rows=_pending_user(),
        waitlist_rows=[{"id": "w1", "email": "*@bu.edu", "approved_at": APPROVED_AT}],
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


def _approved_user():
    return [{"id": "user_112233", "is_approved": True, "streak_count": 1}]


def test_user_approved_elsewhere_is_still_marked_joined(callback, monkeypatch):
    # Approved under Admin → Users, never on the waitlist: still a waitlist
    # signup who got in.
    tables = _tables(
        monkeypatch, users_rows=_approved_user(),
        waitlist_rows=[{"id": "w1", "email": EMAIL, "approved_at": None, "joined_at": None}],
    )
    assert callback() == "/auth/callback"
    assert _joined_update(tables) is not None


def test_already_joined_is_not_restamped(callback, monkeypatch):
    tables = _tables(
        monkeypatch, users_rows=_approved_user(),
        waitlist_rows=[{"id": "w1", "email": EMAIL, "approved_at": APPROVED_AT,
                        "joined_at": APPROVED_AT}],
    )
    assert callback() == "/auth/callback"
    assert _joined_update(tables) is None


def test_joined_stamp_failure_never_breaks_sign_in(callback, monkeypatch):
    tables = _tables(
        monkeypatch, users_rows=_approved_user(),
        waitlist_rows=[{"id": "w1", "email": EMAIL, "approved_at": APPROVED_AT}],
    )
    tables["newsletter_emails"].update.side_effect = RuntimeError("postgrest down")
    assert callback() == "/auth/callback"


def test_case_twin_prefers_the_approved_row(monkeypatch):
    _tables(monkeypatch, users_rows=[], waitlist_rows=[
        {"id": "w1", "email": "Student@bu.edu", "approved_at": None},
        {"id": "w2", "email": "student@bu.edu", "approved_at": APPROVED_AT},
    ])
    assert auth_module._waitlist_entry(EMAIL)["id"] == "w2"


def test_lookup_escapes_like_metacharacters(monkeypatch):
    # `_` is LIKE's single-character wildcard; unescaped, a.b_c@bu.edu would
    # also match a.bXc@bu.edu at the DB.
    tables = _tables(monkeypatch, users_rows=[], waitlist_rows=[])
    auth_module._waitlist_entry("  A.B_C@bu.edu ")
    filters = tables["newsletter_emails"].select.call_args.kwargs["filters"]
    assert filters["or"] == '(email.ilike."a.b\\\\_c@bu.edu")'


# ── Unapproved sign-in: no account, a pending token instead ─────────────────

def _token_from(location: str, key: str) -> str:
    from urllib.parse import parse_qs
    return parse_qs(urlparse(location).query)[key][0]


def _nothing_stored(tables) -> bool:
    users = tables.get("users")
    return (
        (users is None or (not users.upsert.called and not users.update.called))
        and "user_profiles" not in tables
        and "oauth_tokens" not in tables
    )


def test_unapproved_first_sign_in_stores_nothing(callback, monkeypatch):
    tables = _tables(monkeypatch, users_rows=[], waitlist_rows=[])
    location = callback(full=True)
    assert urlparse(location).path == "/pending"
    assert _nothing_stored(tables)
    assert auth_module._pending_token_email(_token_from(location, "t")) == EMAIL


def test_unapproved_waitlist_entry_first_sign_in_stores_nothing(callback, monkeypatch):
    tables = _tables(
        monkeypatch, users_rows=[],
        waitlist_rows=[{"id": "w1", "email": EMAIL, "approved_at": None}],
    )
    assert callback() == "/pending"
    assert _nothing_stored(tables)


def test_unapproved_popup_sign_in_carries_the_token(callback, monkeypatch):
    tables = _tables(monkeypatch, users_rows=[], waitlist_rows=[])
    location = callback(popup_id="p1", full=True)
    assert urlparse(location).path == "/auth/callback"
    assert _token_from(location, "error") == "not_approved"
    assert auth_module._pending_token_email(_token_from(location, "pending_token")) == EMAIL
    assert _nothing_stored(tables)


def test_token_never_shows_the_email(callback, monkeypatch):
    import base64

    _tables(monkeypatch, users_rows=[], waitlist_rows=[])
    token = _token_from(callback(full=True), "t")
    payload = token.partition(".")[0]
    decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode()
    assert EMAIL not in token and EMAIL not in decoded


def test_existing_unapproved_account_goes_to_pending(callback, monkeypatch):
    # e.g. access removed under Admin → Users: the row exists, nothing new is made.
    tables = _tables(monkeypatch, users_rows=_pending_user(), waitlist_rows=[])
    location = callback(full=True)
    assert urlparse(location).path == "/pending"
    assert not tables["users"].upsert.called
    assert auth_module._pending_token_email(_token_from(location, "t")) == EMAIL


@pytest.fixture
def pending(monkeypatch):
    """A client plus a pending token for EMAIL."""
    monkeypatch.setattr(auth_module, "SESSION_SECRET", "test-secret-key")

    def _setup(*, waitlist_rows=None):
        tables = _tables(monkeypatch, users_rows=[], waitlist_rows=waitlist_rows)
        return tables, TestClient(_app), auth_module._mint_pending_token(EMAIL)

    return _setup


def test_pending_token_is_not_a_session(pending):
    # auth_guard and the frontend session BFF both verify HMAC(SESSION_SECRET,
    # payload); conftest stubs _decode_session, so pin the property directly.
    import base64
    import hashlib
    import hmac

    _, _, token = pending()
    payload, _, sig = token.partition(".")
    session_sig = base64.urlsafe_b64encode(
        hmac.new(b"test-secret-key", payload.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")
    assert sig != session_sig


def test_pending_token_rejects_tampering_and_expiry(pending, monkeypatch):
    _, _, token = pending()
    payload, _, sig = token.partition(".")
    assert auth_module._pending_token_email(f"{payload}.{sig[:-2]}xx") is None
    # A real session token is not a pending token either.
    assert auth_module._pending_token_email(
        auth_module.mint_session(EMAIL, secret="test-secret-key")
    ) is None
    monkeypatch.setattr(auth_module, "_PENDING_TOKEN_TTL_SECONDS", -1)
    assert auth_module._pending_token_email(auth_module._mint_pending_token(EMAIL)) is None


def test_pending_status_not_on_waitlist(pending):
    tables, client, token = pending(waitlist_rows=[])
    resp = client.post("/api/auth/pending/status", json={"token": token})
    assert resp.status_code == 200
    assert resp.json() == {"email": EMAIL, "on_waitlist": False}
    tables["users"].select.assert_not_called()  # there is no account to look up


def test_pending_status_on_waitlist_is_case_insensitive(pending):
    _, client, token = pending(waitlist_rows=[{"id": "w1", "email": "Student@BU.edu", "approved_at": None}])
    assert client.post("/api/auth/pending/status", json={"token": token}).json()["on_waitlist"] is True


def test_pending_status_bad_token_is_401(pending):
    _, client, _ = pending()
    assert client.post("/api/auth/pending/status", json={"token": "nope.nope"}).status_code == 401


def test_pending_join_adds_the_sign_in_email(pending):
    tables, client, token = pending(waitlist_rows=[])
    resp = client.post("/api/auth/pending/join", json={"token": token})
    assert resp.status_code == 200
    assert resp.json() == {"email": EMAIL, "on_waitlist": True}
    upsert = tables["newsletter_emails"].upsert.call_args
    assert upsert.args[0] == {"email": EMAIL}
    assert upsert.kwargs["on_conflict"] == "email"


def test_pending_join_is_a_no_op_when_already_listed(pending):
    tables, client, token = pending(waitlist_rows=[{"id": "w1", "email": EMAIL, "approved_at": None}])
    assert client.post("/api/auth/pending/join", json={"token": token}).status_code == 200
    tables["newsletter_emails"].upsert.assert_not_called()


def test_pending_join_bad_token_writes_nothing(pending):
    tables, client, _ = pending(waitlist_rows=[])
    assert client.post("/api/auth/pending/join", json={"token": "x.y"}).status_code == 401
    tables["newsletter_emails"].upsert.assert_not_called()
