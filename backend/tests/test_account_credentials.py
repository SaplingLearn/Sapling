"""Credentials go at the student's own account delete (owner decision 2026-11-14).

`DELETE /api/profile/{user_id}/account` is a thin wrapper over
`services/profile/deletion.py::delete_account` (#118), which reads the Google
tokens, hides the account, then removes the Google OAuth tokens and the
Gradescope login and schedules a best-effort revoke of the Google grant with
the tokens it read; `services/account_credentials.py` does the reading,
removing and revoking. The ordering is tested at the service level; the
route's own tests only check the HTTP mapping.
"""
import asyncio
import inspect
import threading
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from services import account_credentials as ac
from services.encryption import encrypt
from services.profile import DeletionNotConfirmed
from services.profile import deletion
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


class AfterResponse:
    """The `after_response` scheduler (the route passes BackgroundTasks.add_task):
    records what the delete scheduled, runs nothing."""

    def __init__(self):
        self.calls: list[tuple] = []

    def __call__(self, fn, *args, **kwargs):
        self.calls.append((fn, args, kwargs))

    def finishes(self):
        """The `finish_removal` calls scheduled: (user_id, tokens, retry_delete)."""
        return [(*args, kwargs["retry_delete"]) for fn, args, kwargs in self.calls
                if fn is ac.finish_removal]

    def revoked(self):
        """The token lists scheduled for revoke at Google."""
        return [tokens for _uid, tokens, _retry in self.finishes()]


def _delete_account(tables, confirmation="DELETE"):
    """Run the service's delete over `tables`. Returns (result or the raised
    exception, the scheduler)."""
    later = AfterResponse()
    with patch_profile_table(side_effect=tables):
        try:
            result = deletion.delete_account(USER, confirmation, after_response=later)
        except Exception as exc:  # noqa: BLE001 — the test inspects it
            result = exc
    return result, later


def _tokens():
    return {"access_token": encrypt("ya29.access"), "refresh_token": encrypt("1//refresh")}


def test_self_delete_hides_the_account_then_removes_credentials():
    tables = Tables(_tokens())

    result, later = _delete_account(tables)

    assert result == {"deleted": True}
    writes = [(op, name) for op, name, _ in tables.log]
    assert writes == [("update", "users"), ("delete", "oauth_tokens"),
                      ("delete", "gradescope_credentials")]
    assert "deleted_at" in tables.log[0][2]
    for op, name, filters in tables.log[1:]:
        assert filters == {"user_id": f"eq.{USER}"}, name
    # The grant is revoked after the response: refresh token first. The
    # credentials are already gone, so nothing is retried.
    assert later.finishes() == [(USER, ["1//refresh", "ya29.access"], False)]


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

    first, later = _delete_account(tables)

    assert isinstance(first, RuntimeError)
    assert tables.log == [] and tables.oauth_row is not None  # nothing removed
    assert later.calls == []

    retry, later = _delete_account(tables)

    assert retry == {"deleted": True}
    assert later.revoked() == [["1//refresh", "ya29.access"]]
    assert tables.oauth_row is None


def test_a_token_read_failure_raises_and_changes_nothing():
    tables = Tables(_tokens())
    tables("oauth_tokens").select.side_effect = RuntimeError("db down")

    result, later = _delete_account(tables)

    assert isinstance(result, RuntimeError) and tables.log == []
    assert later.calls == []


def test_wrong_confirmation_touches_nothing():
    tables = Tables(_tokens())

    result, later = _delete_account(tables, confirmation="nope")

    assert isinstance(result, DeletionNotConfirmed)
    assert tables.log == [] and later.calls == []


# ── the route: HTTP mapping only ────────────────────────────────────────────


def _route_delete(confirmation):
    from main import app

    with patch("routes.profile.require_self"), \
         patch("routes.profile._delete_account", return_value={"deleted": True}) as svc:
        r = TestClient(app).request(
            "DELETE", f"/api/profile/{USER}/account", json={"confirmation": confirmation},
        )
    return r, svc


def test_the_route_hands_the_delete_to_the_service():
    r, svc = _route_delete("DELETE")

    assert r.status_code == 200 and r.json() == {"deleted": True}
    args, kwargs = svc.call_args
    assert args == (USER, "DELETE") and callable(kwargs["after_response"])


def test_the_route_answers_an_unconfirmed_delete_400():
    from main import app

    tables = Tables()
    with patch("routes.profile.require_self"), patch_profile_table(side_effect=tables):
        r = TestClient(app).request(
            "DELETE", f"/api/profile/{USER}/account", json={"confirmation": "nope"},
        )
    assert r.status_code == 400 and r.json()["detail"] == "Confirmation must be 'DELETE'"
    assert tables.log == []


def test_a_credential_delete_failure_after_the_hide_is_retried_after_the_response():
    """Once the account is hidden the student cannot retry (the guard refuses
    the session), so a failed row delete does not fail the delete: the task
    that revokes the grant (with the tokens read before the hide) retries the
    delete first."""
    tables = Tables(_tokens())
    tables("gradescope_credentials").delete.side_effect = RuntimeError("db down")

    result, later = _delete_account(tables)

    assert result == {"deleted": True}
    assert ("update", "users") in [(op, name) for op, name, _ in tables.log]
    assert later.finishes() == [(USER, ["1//refresh", "ya29.access"], True)]


# ── finish_removal: the after-response half ─────────────────────────────────


@pytest.fixture
def no_sleep(monkeypatch):
    slept = []

    async def sleep(delay):
        slept.append(delay)

    monkeypatch.setattr(ac, "_sleep", sleep)
    return slept


def _finish(*args, **kwargs):
    return asyncio.run(ac.finish_removal(*args, **kwargs))


def test_finish_removal_is_an_async_background_task():
    """Starlette awaits an `async def` background task on the loop; its
    backoff is an `asyncio.sleep`, so a failed delete holds no threadpool
    worker for the ~10 s of retries."""
    assert inspect.iscoroutinefunction(ac.finish_removal)
    assert ac._sleep is asyncio.sleep


def test_finish_removal_retries_the_delete_with_backoff_then_revokes(monkeypatch, no_sleep):
    order = []
    attempts = iter([RuntimeError("db down"), None])

    def delete(uid):
        order.append(("delete", uid))
        exc = next(attempts)
        if exc:
            raise exc

    monkeypatch.setattr(ac, "delete_credentials", delete)
    monkeypatch.setattr(ac, "revoke_google_tokens", lambda t: order.append(("revoke", t)))

    _finish(USER, ["tok"], retry_delete=True)

    assert order == [("delete", USER), ("delete", USER), ("revoke", ["tok"])]
    assert no_sleep == list(ac.DELETE_RETRY_DELAYS_S[:2])
    assert no_sleep[0] < no_sleep[1]  # backoff


def test_finish_removal_keeps_the_loop_free_and_its_db_calls_off_it(monkeypatch):
    """The backoff yields to the loop (another task runs during it), and the
    sync delete and the revoke run on a worker thread, as the service role."""
    from db.scope import in_service_scope

    monkeypatch.setattr(ac, "DELETE_RETRY_DELAYS_S", (0.05, 0.05))
    seen = []
    attempts = iter([RuntimeError("db down"), None])

    def delete(uid):
        seen.append(("delete", threading.get_ident(), in_service_scope()))
        exc = next(attempts)
        if exc:
            raise exc

    def revoke(tokens):
        seen.append(("revoke", threading.get_ident(), None))

    monkeypatch.setattr(ac, "delete_credentials", delete)
    monkeypatch.setattr(ac, "revoke_google_tokens", revoke)

    async def run():
        loop_thread = threading.get_ident()
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0.005)

        tick = asyncio.create_task(ticker())
        await ac.finish_removal(USER, ["tok"], retry_delete=True)
        tick.cancel()
        return loop_thread, ticks

    loop_thread, ticks = asyncio.run(run())
    assert ticks >= 5  # the loop ran other work during the ~0.1 s of backoff
    assert [what for what, _, _ in seen] == ["delete", "delete", "revoke"]
    assert all(thread != loop_thread for _, thread, _ in seen)
    assert [scope for what, _, scope in seen if what == "delete"] == [True, True]


def test_finish_removal_logs_the_user_when_every_retry_fails(monkeypatch, no_sleep, caplog):
    calls = []

    def delete(uid):
        calls.append(uid)
        raise RuntimeError("db down")

    monkeypatch.setattr(ac, "delete_credentials", delete)
    revoke = MagicMock()
    monkeypatch.setattr(ac, "revoke_google_tokens", revoke)

    with caplog.at_level("ERROR", logger=ac.__name__):
        _finish(USER, ["tok"], retry_delete=True)  # never raises

    assert len(calls) == len(ac.DELETE_RETRY_DELAYS_S) >= 2
    revoke.assert_called_once_with(["tok"])  # the grant is revoked anyway
    (record,) = [r for r in caplog.records if r.levelname == "ERROR"]
    assert USER in record.getMessage()


def test_finish_removal_without_a_pending_delete_only_revokes(monkeypatch, no_sleep):
    delete = MagicMock()
    monkeypatch.setattr(ac, "delete_credentials", delete)
    revoke = MagicMock()
    monkeypatch.setattr(ac, "revoke_google_tokens", revoke)

    _finish(USER, ["tok"], retry_delete=False)

    delete.assert_not_called()
    revoke.assert_called_once_with(["tok"])
    assert no_sleep == []


def test_finish_removal_never_raises_when_the_revoke_does(monkeypatch, no_sleep):
    monkeypatch.setattr(ac, "revoke_google_tokens", MagicMock(side_effect=RuntimeError("boom")))
    _finish(USER, ["tok"], retry_delete=False)


# ── deleted_accounts_with_credentials ───────────────────────────────────────


def test_leftover_credentials_are_found_through_the_deleted_account(monkeypatch):
    reads = {}

    def tbl(name):
        m = MagicMock()

        def select(columns, filters=None, limit=None, **k):
            reads[name] = (columns, filters, limit)
            rows = {
                "oauth_tokens": [{"user_id": "u1", "users": {"deleted_at": "2026-11-01T00:00:00Z"}},
                                 # a non-!inner regression would return live rows too
                                 {"user_id": "live", "users": {"deleted_at": None}}],
                "gradescope_credentials": [{"user_id": "u1", "users": {"deleted_at": "x"}},
                                           {"user_id": "u2", "users": {"deleted_at": "x"}}],
            }
            return rows[name]
        m.select.side_effect = select
        return m

    monkeypatch.setattr(ac, "table", tbl)

    assert ac.deleted_accounts_with_credentials() == ["u1", "u2"]
    for name in ("oauth_tokens", "gradescope_credentials"):
        columns, filters, limit = reads[name]
        assert "users!inner(deleted_at)" in columns
        assert filters == {"users.deleted_at": "not.is.null"}
        assert limit == ac.LEFTOVER_SCAN_LIMIT


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
