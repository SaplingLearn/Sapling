"""Credentials go at the student's own account delete (owner decision 2026-11-14).

`DELETE /api/profile/{user_id}/account` reads the Google tokens, hides the
account, then removes the Google OAuth tokens and the Gradescope login and
schedules a best-effort revoke of the Google grant with the tokens it read;
`services/account_credentials.py` does the reading, removing and revoking.
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
            m.select.side_effect = lambda *a, **k: (
                [self.oauth_row] if name == "oauth_tokens" and self.oauth_row else [])
            m.delete.side_effect = lambda filters=None, **k: self._delete(name, filters)
            m.update.side_effect = lambda data, filters=None, **k: self.log.append(("update", name, data)) or [{}]
            self.mocks[name] = m
        return self.mocks[name]

    def _delete(self, name, filters):
        self.log.append(("delete", name, filters))
        if name == "oauth_tokens":
            self.oauth_row = None  # a retry reads what is really left
        return []


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


def _tokens():
    return {"access_token": encrypt("ya29.access"), "refresh_token": encrypt("1//refresh")}


def test_self_delete_hides_the_account_then_removes_credentials():
    tables = Tables(_tokens())

    r, revoke = _delete_account(tables)

    assert r.status_code == 200 and r.json() == {"deleted": True}
    writes = [(op, name) for op, name, _ in tables.log]
    assert writes == [("update", "users"), ("delete", "oauth_tokens"),
                      ("delete", "gradescope_credentials")]
    assert "deleted_at" in tables.log[0][2]
    for op, name, filters in tables.log[1:]:
        assert filters == {"user_id": f"eq.{USER}"}, name
    # The grant is revoked after the response: refresh token first.
    revoke.assert_called_once_with(["1//refresh", "ya29.access"])


def test_a_failed_soft_delete_keeps_the_tokens_so_the_retry_revokes_the_grant():
    """The soft delete failing must not strand a live Google grant: the
    tokens stay stored, and the student's retry still revokes them."""
    tables = Tables(_tokens())
    attempts = []

    def update(data, filters=None, **k):
        attempts.append(data)
        if len(attempts) == 1:
            raise RuntimeError("db down")
        tables.log.append(("update", "users", data))
        return [{}]

    tables("users").update.side_effect = update

    first, revoke = _delete_account(tables)

    assert first.status_code == 500
    assert tables.log == [] and tables.oauth_row is not None  # nothing removed
    revoke.assert_not_called()

    retry, revoke = _delete_account(tables)

    assert retry.status_code == 200
    revoke.assert_called_once_with(["1//refresh", "ya29.access"])
    assert tables.oauth_row is None


def test_a_token_read_failure_is_a_500_that_changes_nothing():
    tables = Tables(_tokens())
    tables("oauth_tokens").select.side_effect = RuntimeError("db down")

    r, revoke = _delete_account(tables)

    assert r.status_code == 500 and tables.log == []
    revoke.assert_not_called()


def test_a_credential_delete_failure_after_the_hide_still_revokes_the_grant():
    """Once the account is hidden the student cannot retry (the guard refuses
    the session), so a failed row delete does not fail the request: the grant
    is revoked with the tokens read before the hide, and the 30-day purge
    removes the leftover rows (services/account_purge.py)."""
    tables = Tables(_tokens())
    tables("gradescope_credentials").delete.side_effect = RuntimeError("db down")

    r, revoke = _delete_account(tables)

    assert r.status_code == 200 and r.json() == {"deleted": True}
    assert ("update", "users") in [(op, name) for op, name, _ in tables.log]
    revoke.assert_called_once_with(["1//refresh", "ya29.access"])


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
