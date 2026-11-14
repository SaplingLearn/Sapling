"""Credentials go at the student's own account delete (owner decision 2026-11-14).

`DELETE /api/profile/{user_id}/account` removes the Google OAuth tokens and
the Gradescope login BEFORE hiding the account, and schedules a best-effort
revoke of the Google grant; `services/account_credentials.py` does both.
"""
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from services import account_credentials as ac
from services.encryption import encrypt
from tests.split_patches import patch_profile_table

USER = "user_cred"


class Tables:
    """table() over per-table MagicMocks, logging every write in order."""

    def __init__(self, oauth_row=None):
        self.log: list[tuple[str, str, dict]] = []
        self.mocks: dict[str, MagicMock] = {}
        self.oauth_row = oauth_row

    def __call__(self, name):
        if name not in self.mocks:
            m = MagicMock()
            m.select.return_value = [self.oauth_row] if name == "oauth_tokens" and self.oauth_row else []
            m.delete.side_effect = lambda filters=None, **k: self.log.append(("delete", name, filters)) or []
            m.update.side_effect = lambda data, filters=None, **k: self.log.append(("update", name, data)) or [{}]
            self.mocks[name] = m
        return self.mocks[name]


def _delete_account(tables, **patches):
    from main import app

    revoke = patches.get("revoke", MagicMock())
    with patch("routes.profile.require_self"), \
         patch_profile_table(side_effect=tables), \
         patch("routes.profile.delete_posthog_person"), \
         patch("routes.profile.revoke_google_tokens", revoke):
        r = TestClient(app, raise_server_exceptions=False).request(
            "DELETE", f"/api/profile/{USER}/account", json={"confirmation": "DELETE"},
        )
    return r, revoke


def test_self_delete_removes_credentials_before_hiding_the_account():
    tables = Tables({"access_token": encrypt("ya29.access"), "refresh_token": encrypt("1//refresh")})

    r, revoke = _delete_account(tables)

    assert r.status_code == 200 and r.json() == {"deleted": True}
    writes = [(op, name) for op, name, _ in tables.log]
    assert writes == [("delete", "oauth_tokens"), ("delete", "gradescope_credentials"),
                      ("update", "users")]
    for op, name, filters in tables.log[:2]:
        assert filters == {"user_id": f"eq.{USER}"}, name
    assert "deleted_at" in tables.log[2][2]
    # The grant is revoked after the response: refresh token first.
    revoke.assert_called_once_with(["1//refresh", "ya29.access"])


def test_a_credential_delete_failure_is_a_500_and_the_account_stays_visible():
    tables = Tables()
    tables("gradescope_credentials").delete.side_effect = RuntimeError("db down")

    r, revoke = _delete_account(tables)

    assert r.status_code == 500
    assert ("update", "users") not in [(op, name) for op, name, _ in tables.log]
    revoke.assert_not_called()


def test_wrong_confirmation_touches_no_credential():
    from main import app

    tables = Tables()
    with patch("routes.profile.require_self"), patch_profile_table(side_effect=tables):
        r = TestClient(app).request(
            "DELETE", f"/api/profile/{USER}/account", json={"confirmation": "nope"},
        )
    assert r.status_code == 400 and tables.log == []


# ── remove_credentials ──────────────────────────────────────────────────────


def test_undecryptable_or_missing_tokens_are_never_returned(monkeypatch):
    tables = Tables({"access_token": "not-ciphertext", "refresh_token": None})
    monkeypatch.setattr(ac, "table", tables)

    assert ac.remove_credentials(USER) == []
    assert [(op, name) for op, name, _ in tables.log] == [
        ("delete", "oauth_tokens"), ("delete", "gradescope_credentials")]


# ── revoke_google_tokens ────────────────────────────────────────────────────


def test_revoke_is_off_under_pytest(monkeypatch):
    post = MagicMock()
    monkeypatch.setattr(ac.httpx, "post", post)

    assert ac.revoke_google_tokens(["tok"]) is False
    post.assert_not_called()


@pytest.fixture
def revoke_on(monkeypatch):
    monkeypatch.setattr(ac, "_revoke_disabled", lambda: False)
    calls = []

    def respond(answers):
        def post(url, data=None, **kw):
            calls.append((url, data))
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return MagicMock(status_code=answer)
        monkeypatch.setattr(ac.httpx, "post", post)
        return calls

    return respond


def test_revoke_posts_the_token_to_google(revoke_on):
    calls = revoke_on([200])

    assert ac.revoke_google_tokens(["refresh", "access"]) is True
    assert calls == [(ac.GOOGLE_REVOKE_URL, {"token": "refresh"})]


def test_revoke_falls_back_to_the_next_token_and_never_raises(revoke_on, caplog):
    calls = revoke_on([400, httpx.ConnectTimeout("slow")])

    assert ac.revoke_google_tokens(["refresh", "access"]) is False
    assert [d["token"] for _, d in calls] == ["refresh", "access"]
    assert "refresh" not in caplog.text and "access" not in caplog.text


def test_nothing_to_revoke_is_a_no_op(revoke_on):
    calls = revoke_on([])
    assert ac.revoke_google_tokens([]) is False and calls == []
