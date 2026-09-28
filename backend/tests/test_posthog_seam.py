"""The PostHog seam (ADR 0028): gating, the one event mirror, the AI-span
allowlist, exception-capture safety, and best-effort account deletion.

Everything here runs hermetically: under pytest the real gate says "off", so
tests that need an "on" seam install a fake client or patch the gate
explicitly, and the no-network tests assert that no socket is ever opened.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import socket
import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import BackgroundTasks, Depends, FastAPI, Request
from fastapi.testclient import TestClient

from services import analytics_consent, events_service, feature_flags, posthog_client
from services.analytics_consent import Consent

# The shape production actually issues (routes/auth.py: f"user_{google_id}").
# users.id is TEXT, not a UUID — a UUID-only rule would drop every real user.
USER_ID = "user_109876543210987654321"
# Stands in for decrypted student text (a note body, a chat message, a name).
SECRET = "SECRET-student-note-Ada-Lovelace-4471"


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def fake_client(monkeypatch):
    """Install a fake PostHog client, with the gate saying "on" (under pytest
    the real gate is always off, and it is re-read on every submit)."""
    client = MagicMock(name="PosthogClient")
    monkeypatch.setattr(posthog_client, "disabled_reason", lambda **k: None)
    posthog_client.set_client_for_tests(client)
    try:
        yield client
    finally:
        posthog_client.flush_queue(timeout_seconds=5)
        posthog_client.set_client_for_tests(None)


def _drain():
    """Wait for the PostHog worker to deliver (or drop) everything queued."""
    assert posthog_client.flush_queue(timeout_seconds=5), "PostHog queue did not drain"


_REAL_LOOKUP = analytics_consent._lookup
_REAL_SCHEDULE = posthog_client._schedule_second_pass


@pytest.fixture(autouse=True)
def no_second_delete_timer(monkeypatch):
    """delete_person schedules a real 90 s daemon timer for its second pass;
    record the request instead (TestNoRecreateAfterDelete drives the real one
    with a fake Timer)."""
    scheduled: list[str] = []
    monkeypatch.setattr(posthog_client, "_schedule_second_pass", scheduled.append)
    return scheduled


@pytest.fixture(autouse=True)
def consent_db(monkeypatch):
    """Stand-in for the users/user_settings read behind analytics_consent:
    user id -> Consent. Anything not listed is DENIED, exactly as a missing
    users row is. Records every lookup so tests can count round trips."""
    answers: dict[str, Consent] = {USER_ID: Consent.ALLOWED}
    calls: list[str] = []

    def fake_lookup(uid):
        calls.append(uid)
        answer = answers.get(uid, Consent.DENIED)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(analytics_consent, "_lookup", fake_lookup)
    analytics_consent.clear_analytics_consent_cache()
    # Start from the request-free defaults (no request scope, no DNT/GPC),
    # as the sweeper or a script does.
    from services.request_context import _PRIVACY_SIGNAL_CTX, _REQUEST_CTX

    scope_token = _REQUEST_CTX.set(None)
    signal_token = _PRIVACY_SIGNAL_CTX.set(False)
    try:
        yield SimpleNamespace(answers=answers, calls=calls)
    finally:
        # Deliver anything still queued against THIS test's fake lookup.
        posthog_client.flush_queue(timeout_seconds=5)
        _PRIVACY_SIGNAL_CTX.reset(signal_token)
        _REQUEST_CTX.reset(scope_token)
        analytics_consent.clear_analytics_consent_cache()


@pytest.fixture
def no_network(monkeypatch):
    """Record (and refuse) every outbound socket connect."""
    attempts: list = []

    def _refuse(self, address, *a, **k):
        attempts.append(address)
        raise OSError("network disabled by test")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    return attempts


@pytest.fixture(autouse=True)
def product_analytics_on(monkeypatch):
    """The hermetic DB has no `feature_flags` row, so `product_analytics`
    resolves to its off default (#620); every existing test in this module
    predates the flag and expects delivery, so default it to on here.
    ``TestProductAnalyticsFlag`` overrides this per-test to exercise the
    real gating behaviour."""
    monkeypatch.setattr(feature_flags, "flag_on", lambda key, user_id: True)


_ON_ENV = {
    "POSTHOG_PROJECT_TOKEN": "phc_test",
    "SAPLING_MODEL_MODE": "real",
    "APP_ENV": "local",
}


# ── 1. Gating ───────────────────────────────────────────────────────────────


def _gate(env, *, under_pytest=False, for_erasure=False):
    """The pure gate, with the mode resolved by the LLM seam itself
    (agents._providers.model_mode) from the env under test."""
    from agents import _providers

    with patch.dict("os.environ", {"SAPLING_MODEL_MODE": env.get("SAPLING_MODEL_MODE", "")}):
        mode = _providers.model_mode()
    return posthog_client._disabled_reason_for(
        env, under_pytest=under_pytest, model_mode=mode, for_erasure=for_erasure,
    )


class TestGate:
    def test_token_set_real_mode_local_is_on(self):
        assert _gate(_ON_ENV) is None

    def test_production_with_token_is_on(self):
        env = {**_ON_ENV, "APP_ENV": "production"}
        assert _gate(env) is None

    @pytest.mark.parametrize(
        "override, expect",
        [
            ({"POSTHOG_PROJECT_TOKEN": ""}, "POSTHOG_PROJECT_TOKEN"),
            ({"POSTHOG_PROJECT_TOKEN": "   "}, "POSTHOG_PROJECT_TOKEN"),
            ({"SAPLING_MODEL_MODE": "function"}, "SAPLING_MODEL_MODE"),
            ({"SAPLING_MODEL_MODE": " Function "}, "SAPLING_MODEL_MODE"),
            ({"APP_ENV": "test"}, "APP_ENV=test"),
            ({"POSTHOG_DISABLED": "1"}, "POSTHOG_DISABLED"),
            ({"POSTHOG_DISABLED": "true"}, "POSTHOG_DISABLED"),
        ],
    )
    def test_each_forced_off_rule(self, override, expect):
        env = {**_ON_ENV, **override}
        reason = _gate(env)
        assert reason is not None and expect in reason

    def test_pytest_forces_off_even_when_everything_else_says_on(self):
        reason = _gate(_ON_ENV, under_pytest=True)
        assert reason == "running under pytest"

    def test_real_gate_is_off_in_this_process(self, monkeypatch):
        # The live gate, with a token deliberately present: pytest wins.
        monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "phc_test")
        monkeypatch.setenv("SAPLING_MODEL_MODE", "real")
        assert posthog_client.disabled_reason() is not None

    def test_kill_switch_zero_is_not_truthy(self):
        env = {**_ON_ENV, "POSTHOG_DISABLED": "0"}
        assert _gate(env) is None


@pytest.mark.parametrize(
    "override",
    [
        {"POSTHOG_PROJECT_TOKEN": ""},
        {"SAPLING_MODEL_MODE": "function"},
        {"APP_ENV": "test"},
        {"POSTHOG_DISABLED": "1"},
    ],
)
def test_disabled_means_no_client_no_processor_no_network(override, monkeypatch, no_network):
    """Every forced-off rule, evaluated as if NOT under pytest: no Posthog()
    constructed, no AI span processor, and no socket opened by any seam use."""
    env = {**_ON_ENV, **override}
    monkeypatch.setattr(
        posthog_client, "disabled_reason",
        lambda **k: _gate(env, **k),
    )
    with patch("posthog.Posthog") as ctor:
        assert posthog_client.initialize_posthog() is False
        ctor.assert_not_called()
    assert posthog_client._client is None

    events_service.log_event("note.created", category="usage", user_id=USER_ID, payload={})
    posthog_client.capture_exception(ValueError("x"), user_id=USER_ID, request_id=None)
    with patch("httpx.post") as post:
        posthog_client.delete_person(USER_ID)
    if "POSTHOG_PROJECT_TOKEN" not in override:
        post.assert_not_called()
    assert no_network == []


def test_enabled_client_is_constructed_with_privacy_settings(monkeypatch):
    monkeypatch.setattr(posthog_client, "disabled_reason", lambda **k: None)
    monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "phc_test")
    monkeypatch.delenv("POSTHOG_HOST", raising=False)
    with patch("posthog.Posthog") as ctor:
        try:
            assert posthog_client.initialize_posthog() is True
            client = posthog_client._client
            assert client is ctor.return_value
            kwargs = ctor.call_args.kwargs
            assert kwargs["project_api_key"] == "phc_test"
            assert kwargs["host"] == "https://us.i.posthog.com"  # US cloud default
            assert kwargs["capture_exception_code_variables"] is False
            assert kwargs["enable_exception_autocapture"] is False
            assert kwargs["before_send"] is posthog_client._scrub_event
            # A personal key must never reach the capture client (it would
            # start feature-flag polling = background network).
            assert "personal_api_key" not in kwargs and "secret_key" not in kwargs
            # Idempotent.
            assert posthog_client.initialize_posthog() is True
            assert posthog_client._client is client
            assert ctor.call_count == 1
        finally:
            posthog_client.shutdown_posthog()
    assert posthog_client._client is None


def test_lifespan_under_pytest_builds_no_client():
    """The app's own lifespan runs initialize_posthog; under pytest it must
    leave the client None even with a token in the environment."""
    with patch.dict("os.environ", {"POSTHOG_PROJECT_TOKEN": "phc_test"}), \
         patch("posthog.Posthog") as ctor:
        assert posthog_client.initialize_posthog() is False
        ctor.assert_not_called()


# ── 2. The chokepoint mirror ────────────────────────────────────────────────


class TestMirror:
    def test_log_event_mirrors_same_name_payload_and_uuid(self, fake_client, sink):
        events_service.log_event(
            "note.created",
            category="usage",
            user_id=USER_ID,
            request_id="req-123",
            payload={"note_id": "n1", "has_body": True},
            content=SECRET,
        )
        _drain()
        fake_client.capture.assert_called_once()
        _drain()
        call = fake_client.capture.call_args
        assert call.args == ("note.created",)
        assert call.kwargs["distinct_id"] == USER_ID
        assert call.kwargs["properties"] == {
            "note_id": "n1", "has_body": True, "event_category": "usage",
            "request_id": "req-123",
        }
        # Neither the content nor its fingerprint is forwarded.
        assert SECRET not in json.dumps(call.kwargs, default=str)
        assert "content_fp" not in call.kwargs["properties"]
        # And our own table still got its row.
        events_service.flush_now()
        assert [r["event_type"] for r in sink] == ["note.created"]

    def test_kill_switch_stops_the_mirror_too(self, fake_client, monkeypatch, sink):
        monkeypatch.setenv("EVENTS_LOGGING_ENABLED", "false")
        events_service.log_event("note.created", category="usage", user_id=USER_ID)
        _drain()
        fake_client.capture.assert_not_called()

    def test_no_user_and_no_session_user_sends_nothing(self, fake_client, consent_db, sink):
        """No personless events: sweeper/DBOS-style work that names nobody,
        outside any request, is not sent at all — our own row is kept."""
        events_service.log_event("rag.index_failed", category="error", payload={"doc_id": "d"})
        _drain()
        fake_client.capture.assert_not_called()
        assert consent_db.calls == []
        events_service.flush_now()
        assert [r["event_type"] for r in sink] == ["rag.index_failed"]

    def test_a_failing_client_never_raises_or_costs_the_db_row(self, fake_client, sink):
        fake_client.capture.side_effect = RuntimeError("posthog down")
        events_service.log_event("note.created", category="usage", user_id=USER_ID)
        events_service.flush_now()
        assert [r["event_type"] for r in sink] == ["note.created"]

    def test_no_client_is_a_no_op(self, sink):
        assert posthog_client._client is None
        events_service.log_event("note.created", category="usage", user_id=USER_ID)
        events_service.flush_now()
        assert len(sink) == 1

    def test_real_client_capture_is_non_blocking(self, monkeypatch, no_network):
        """The request thread only enqueues onto OUR queue; our worker hands
        the event to posthog-python, whose own consumer uploads. With every
        socket refused, log_event still returns immediately."""
        from posthog import Posthog

        monkeypatch.setattr(posthog_client, "disabled_reason", lambda **k: None)
        client = Posthog(
            "phc_test", host="https://us.i.posthog.com", flush_interval=60, max_retries=0,
        )
        try:
            import threading

            threads: list[str] = []
            real_capture = client.capture
            monkeypatch.setattr(
                client, "capture",
                lambda *a, **k: threads.append(threading.current_thread().name)
                or real_capture(*a, **k),
            )
            posthog_client.set_client_for_tests(client)
            started = time.monotonic()
            events_service.log_event("note.created", category="usage", user_id=USER_ID)
            elapsed = time.monotonic() - started
            assert elapsed < 0.5
            # Handed to the SDK by OUR worker, not on the request thread.
            _drain()
            assert threads == ["posthog-send"]
        finally:
            posthog_client.set_client_for_tests(None)
            # The consumer's one upload attempt hits the refused socket and
            # gives up (max_retries=0); shutdown then returns promptly.
            client.shutdown()


class TestFlashcardEvents:
    """The two events added to the taxonomy for ADR 0028 are emitted through
    events_service (so both pipelines see them)."""

    def test_generate_emits_flashcard_generated(self, sink):
        from main import app

        with patch("routes.flashcards._get_course_documents", return_value=[{"x": 1}]), \
             patch("routes.flashcards._get_weak_concepts", return_value=["a", "b"]), \
             patch("routes.flashcards._generate", return_value=[{"front": SECRET, "back": "b"}]), \
             patch("routes.flashcards.table") as t, \
             patch("services.achievement_service.check_achievements"):
            t.return_value.select.return_value = []
            r = TestClient(app).post("/api/flashcards/generate", json={
                "user_id": USER_ID, "topic": "CS", "count": 1,
            })
        assert r.status_code == 200
        events_service.flush_now()
        rows = [x for x in sink if x["event_type"] == "flashcard.generated"]
        assert len(rows) == 1
        assert rows[0]["user_id"] == USER_ID
        assert rows[0]["payload"] == {
            "card_count": 1, "documents_used": 1, "weak_concepts_used": 2,
        }
        assert SECRET not in json.dumps(rows[0])

    def test_rate_emits_flashcard_reviewed(self, sink):
        from main import app

        with patch("routes.flashcards.table") as t, \
             patch("routes.flashcards.check_achievements"):
            t.return_value.select.return_value = [{"id": "c1", "times_reviewed": 2}]
            r = TestClient(app).post("/api/flashcards/rate", json={
                "user_id": USER_ID, "card_id": "c1", "rating": 3,
            })
        assert r.status_code == 200
        events_service.flush_now()
        rows = [x for x in sink if x["event_type"] == "flashcard.reviewed"]
        assert [x["payload"] for x in rows] == [{"card_id": "c1", "rating": 3}]


# ── 3. AI-span allowlist ────────────────────────────────────────────────────


# ── 4. Exception capture ────────────────────────────────────────────────────


class TestExceptionCapture:
    def test_real_sdk_event_has_no_locals_and_no_message(self, monkeypatch):
        """Through the real posthog SDK (send=False): the queued $exception
        event carries type + frames, but not the message or any local."""
        import posthog as posthog_pkg

        captured: list[dict] = []
        real_scrub = posthog_client._scrub_event

        def spy(msg):
            out = real_scrub(msg)
            captured.append(out)
            return out

        monkeypatch.setattr(posthog_client, "_scrub_event", spy)
        monkeypatch.setattr(posthog_client, "disabled_reason", lambda **k: None)
        monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "phc_test")
        real_ctor = posthog_pkg.Posthog
        monkeypatch.setattr(
            posthog_pkg, "Posthog", lambda **kw: real_ctor(**kw, send=False),
        )
        try:
            posthog_client.initialize_posthog()

            def handler_with_decrypted_locals():
                note_body = SECRET  # noqa: F841 - the local that must not ship
                raise ValueError(f"bad input: {SECRET}")

            try:
                handler_with_decrypted_locals()
            except ValueError as exc:
                posthog_client.capture_exception(exc, user_id=USER_ID, request_id="req-5")
        finally:
            posthog_client.shutdown_posthog()

        # [0] is our enqueue-time scrub of the bare list; [-1] is the SDK's
        # before_send on the real event.
        event = captured[-1]
        assert event["event"] == "$exception"
        assert event["distinct_id"] == USER_ID
        assert event["properties"]["request_id"] == "req-5"
        assert SECRET not in json.dumps(event, default=str)
        exc_list = event["properties"]["$exception_list"]
        assert exc_list[0]["type"] == "ValueError"
        assert exc_list[0]["value"] == "[redacted]"
        frames = exc_list[0]["stacktrace"]["frames"]
        assert frames and all("vars" not in f for f in frames)

    def test_scrub_strips_vars_even_if_present(self):
        msg = {"properties": {"$exception_list": [{
            "type": "KeyError", "value": SECRET,
            "stacktrace": {"frames": [{"function": "f", "vars": {"x": SECRET}}]},
        }]}}
        out = posthog_client._scrub_event(msg)
        assert SECRET not in json.dumps(out)

    def test_500_handler_captures_with_the_session_user(self, fake_client):
        from main import unhandled_exception_handler


        request = SimpleNamespace(
            state=SimpleNamespace(user_id=USER_ID, request_id="rid-1"),
            url=SimpleNamespace(path="/api/notes"),
        )
        exc = RuntimeError("boom")
        resp = asyncio.run(unhandled_exception_handler(request, exc))
        assert resp.status_code == 500
        _drain()
        fake_client.capture.assert_called_once()
        call = fake_client.capture.call_args
        assert call.args == ("$exception",)
        assert call.kwargs["distinct_id"] == USER_ID
        assert call.kwargs["properties"]["request_id"] == "rid-1"
        assert call.kwargs["properties"]["$exception_list"][0]["type"] == "RuntimeError"
        assert call.kwargs["properties"]["$exception_list"][0]["value"] == "[redacted]"

    def test_500_handler_is_inert_when_disabled(self):
        from main import unhandled_exception_handler

        request = SimpleNamespace(
            state=SimpleNamespace(request_id="rid-2"), url=SimpleNamespace(path="/x"),
        )
        resp = asyncio.run(unhandled_exception_handler(request, RuntimeError("x")))
        assert resp.status_code == 500

    def test_a_failing_capture_never_raises(self, fake_client):
        fake_client.capture.side_effect = RuntimeError("down")
        posthog_client.capture_exception(ValueError("x"), user_id=None, request_id=None)


# ── 5. Account deletion ─────────────────────────────────────────────────────


class TestDeletePerson:
    @pytest.fixture
    def on(self, monkeypatch):
        monkeypatch.setattr(posthog_client, "disabled_reason", lambda **k: None)
        monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_key")
        monkeypatch.setenv("POSTHOG_PROJECT_ID", "4242")
        monkeypatch.setenv("POSTHOG_HOST", "https://us.i.posthog.com")
        monkeypatch.delenv("POSTHOG_API_HOST", raising=False)

    def test_posts_bulk_delete_to_the_app_host(self, on):
        with patch("httpx.post", return_value=MagicMock(status_code=202)) as post:
            posthog_client.delete_person(USER_ID)
        post.assert_called_once()
        assert post.call_args.args[0] == (
            "https://us.posthog.com/api/projects/4242/persons/bulk_delete/"
        )
        assert post.call_args.kwargs["json"] == {
            "distinct_ids": [USER_ID], "delete_events": True,
        }
        assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer phx_key"}
        assert post.call_args.kwargs["timeout"] > 0

    def test_runs_even_with_no_project_token(self, monkeypatch, on):
        monkeypatch.setattr(
            posthog_client, "disabled_reason",
            lambda *, for_erasure=False: None if for_erasure else posthog_client._NO_TOKEN,
        )
        with patch("httpx.post", return_value=MagicMock(status_code=202)) as post:
            posthog_client.delete_person(USER_ID)
        post.assert_called_once()

    @pytest.mark.parametrize("unset", ["POSTHOG_PERSONAL_API_KEY", "POSTHOG_PROJECT_ID"])
    def test_unconfigured_warns_and_skips(self, on, monkeypatch, caplog, unset):
        monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "phc_test")  # PostHog WAS configured
        monkeypatch.delenv(unset)
        with patch("httpx.post") as post, caplog.at_level(logging.WARNING, "sapling.posthog"):
            posthog_client.delete_person(USER_ID)
        post.assert_not_called()
        assert "skipped" in caplog.text

    def test_under_pytest_the_real_gate_skips_the_request(self, monkeypatch, caplog):
        monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_key")
        monkeypatch.setenv("POSTHOG_PROJECT_ID", "4242")
        with patch("httpx.post") as post, caplog.at_level(logging.WARNING, "sapling.posthog"):
            posthog_client.delete_person(USER_ID)
        post.assert_not_called()
        assert "pytest" in caplog.text

    @pytest.mark.parametrize(
        "outcome",
        [RuntimeError("dns"), MagicMock(status_code=500), MagicMock(status_code=400)],
    )
    def test_failures_never_raise(self, on, outcome, caplog):
        kwargs = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
        with patch("httpx.post", **kwargs), caplog.at_level(logging.WARNING, "sapling.posthog"):
            posthog_client.delete_person(USER_ID)
        assert "PostHog person delete" in caplog.text

    def test_account_route_schedules_the_delete_after_the_soft_delete(self):
        from main import app

        order: list[str] = []

        def table_side_effect(name):
            m = MagicMock()
            m.update.side_effect = lambda *a, **k: order.append(f"update:{name}") or [{}]
            return m

        with patch("routes.profile.require_self"), \
             patch("routes.profile.table", side_effect=table_side_effect), \
             patch("routes.profile.delete_posthog_person",
                   side_effect=lambda uid: order.append(f"posthog:{uid}")):
            r = TestClient(app).request(
                "DELETE", f"/api/profile/{USER_ID}/account", json={"confirmation": "DELETE"},
            )
        assert r.status_code == 200 and r.json() == {"deleted": True}
        assert order == ["update:users", f"posthog:{USER_ID}"]

    def test_wrong_confirmation_never_touches_posthog(self):
        from main import app

        with patch("routes.profile.require_self"), \
             patch("routes.profile.table"), \
             patch("routes.profile.delete_posthog_person") as delete:
            r = TestClient(app).request(
                "DELETE", f"/api/profile/{USER_ID}/account", json={"confirmation": "nope"},
            )
        assert r.status_code == 400
        delete.assert_not_called()


# ── 6. Review fixes (PR #677) ───────────────────────────────────────────────
#
# One class per /code-review finding, so each regression is findable.


class TestConsentLookup:
    """analytics_consent: the one read behind every "may this user be named"
    decision — shape, placeholders, deletion, opt-out, failure, caching."""

    def _real(self, monkeypatch, rows=None, exc=None):
        monkeypatch.setattr(analytics_consent, "_lookup", _REAL_LOOKUP)
        t = MagicMock()
        if exc is not None:
            t.return_value.select.side_effect = exc
        else:
            t.return_value.select.return_value = rows
        monkeypatch.setattr("db.connection.table", t)
        return t

    @pytest.mark.parametrize("rows, expect", [
        ([{"id": USER_ID, "deleted_at": None, "user_settings": {"analytics_opt_out": False}}],
         Consent.ALLOWED),
        ([{"id": USER_ID, "deleted_at": None, "user_settings": [{"analytics_opt_out": False}]}],
         Consent.ALLOWED),
        # No settings row yet = the column default (not opted out).
        ([{"id": USER_ID, "deleted_at": None, "user_settings": None}], Consent.ALLOWED),
        ([{"id": USER_ID, "deleted_at": None, "user_settings": {"analytics_opt_out": True}}],
         Consent.DENIED),
        # Soft-deleted: a new event would re-create the deleted person.
        ([{"id": USER_ID, "deleted_at": "2026-09-26T00:00:00Z",
           "user_settings": {"analytics_opt_out": False}}], Consent.DENIED),
        # Unknown id.
        ([], Consent.DENIED),
        # A row that does not answer the question fails closed.
        ([{"id": USER_ID, "deleted_at": None, "user_settings": {}}], Consent.DENIED),
    ])
    def test_row_shapes(self, monkeypatch, rows, expect):
        t = self._real(monkeypatch, rows=rows)
        assert analytics_consent.consent_for(USER_ID) is expect
        t.assert_called_once_with("users")
        cols = t.return_value.select.call_args.args[0]
        assert "deleted_at" in cols and "user_settings(analytics_opt_out)" in cols

    def test_lookup_failure_fails_closed(self, monkeypatch, caplog):
        self._real(monkeypatch, exc=RuntimeError("postgrest down"))
        with caplog.at_level(logging.WARNING, "sapling.analytics_consent"):
            assert analytics_consent.consent_for(USER_ID) is Consent.DENIED
        assert "not sending" in caplog.text

    @pytest.mark.parametrize("uid", [
        None, "", "  ", "anonymous", "Anonymous", "backfill", "system", "unknown",
        "has space", "semi;colon", "x" * 200, 42,
    ])
    def test_placeholders_are_no_user_without_a_lookup(self, uid, consent_db):
        assert analytics_consent.consent_for(uid) is Consent.NO_USER
        assert consent_db.calls == []

    @pytest.mark.parametrize("uid", [
        # Real id shapes in this codebase: production google ids, the seeded
        # e2e/staging users, and a UUID. None of these may be dropped by shape.
        "user_109876543210987654321", "seed-user-demo", "rich-student-1",
        "9b2f6a3e-1c1d-4c55-9a8e-2f1f0e6b7a10",
    ])
    def test_real_id_shapes_are_looked_up(self, uid, consent_db):
        consent_db.answers[uid] = Consent.ALLOWED
        assert analytics_consent.consent_for(uid) is Consent.ALLOWED
        assert consent_db.calls == [uid]

    def test_cached_per_process_and_cleared_by_the_hook(self, consent_db):
        for _ in range(5):
            assert analytics_consent.consent_for(USER_ID) is Consent.ALLOWED
        assert consent_db.calls == [USER_ID]  # one round trip, not five
        consent_db.answers[USER_ID] = Consent.DENIED
        assert analytics_consent.consent_for(USER_ID) is Consent.ALLOWED  # still cached
        analytics_consent.clear_analytics_consent_cache(USER_ID)
        assert analytics_consent.consent_for(USER_ID) is Consent.DENIED
        assert consent_db.calls == [USER_ID, USER_ID]

    def test_entries_expire(self, consent_db, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr(analytics_consent.time, "monotonic", lambda: now[0])
        analytics_consent.consent_for(USER_ID)
        now[0] += analytics_consent._TTL_S + 1
        analytics_consent.consent_for(USER_ID)
        assert consent_db.calls == [USER_ID, USER_ID]


class TestOptOut:
    """Finding 1: the mirror, exceptions and AI spans honour the stored
    opt-out and the DNT / GPC request headers."""

    def test_opted_out_user_is_not_mirrored_but_our_row_is_kept(
        self, fake_client, consent_db, sink,
    ):
        consent_db.answers[USER_ID] = Consent.DENIED
        events_service.log_event("note.created", category="usage", user_id=USER_ID)
        _drain()
        fake_client.capture.assert_not_called()
        events_service.flush_now()
        assert [r["event_type"] for r in sink] == ["note.created"]

    def test_unreadable_consent_sends_nothing(self, fake_client, consent_db, sink):
        consent_db.answers[USER_ID] = RuntimeError("db down")
        events_service.log_event("note.created", category="usage", user_id=USER_ID)
        _drain()
        fake_client.capture.assert_not_called()

    def test_per_event_reads_are_cached(self, fake_client, consent_db, sink):
        for _ in range(20):
            events_service.log_event("note.created", category="usage", user_id=USER_ID)
        _drain()
        assert fake_client.capture.call_count == 20
        assert consent_db.calls == [USER_ID]

    def test_session_user_opt_out_covers_events_without_a_user(
        self, fake_client, consent_db, sink,
    ):
        from services.request_context import _REQUEST_CTX, RequestView

        consent_db.answers[USER_ID] = Consent.DENIED
        token = _REQUEST_CTX.set(RequestView({"state": {"user_id": USER_ID}}))
        try:
            events_service.log_event("rag.index_failed", category="error", payload={})
        finally:
            _REQUEST_CTX.reset(token)
        _drain()
        fake_client.capture.assert_not_called()

    def test_opted_out_exception_is_not_captured(self, fake_client, consent_db):
        consent_db.answers[USER_ID] = Consent.DENIED
        posthog_client.capture_exception(ValueError("x"), user_id=USER_ID, request_id="r")
        _drain()
        fake_client.capture.assert_not_called()

    @pytest.mark.parametrize("headers, signal", [
        ({"Sec-GPC": "1"}, True),
        ({"DNT": "1"}, True),
        ({"DNT": "0"}, False),
        ({"Sec-GPC": "0"}, False),
        ({}, False),
    ])
    def test_privacy_headers_through_the_middleware(
        self, headers, signal, fake_client, sink,
    ):
        """End to end through RequestIDMiddleware: an event logged inside the
        handler, and the middleware's own error.5xx, are both skipped for a
        DNT/GPC request."""
        from fastapi import FastAPI

        from services.request_context import RequestIDMiddleware

        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        @app.get("/api/thing/{thing_id}")
        async def thing(thing_id: str, request: Request):
            request.state.user_id = USER_ID  # what auth_guard does
            events_service.log_event("note.created", category="usage", user_id=USER_ID)
            raise RuntimeError("boom")

        r = TestClient(app, raise_server_exceptions=False).get("/api/thing/abc", headers=headers)
        assert r.status_code == 500
        _drain()
        sent = [c.args[0] for c in fake_client.capture.call_args_list]
        assert sent == ([] if signal else ["note.created", "error.5xx"])
        events_service.flush_now()
        # Our own table is unaffected by the browser signal.
        assert {"note.created", "error.5xx"} <= {r["event_type"] for r in sink}

    @pytest.mark.parametrize("headers, captured", [
        ({"Sec-GPC": "1"}, False), ({"DNT": "1"}, False), ({}, True),
    ])
    def test_500_handler_honours_privacy_headers(self, headers, captured, fake_client, sink):
        """The exception handler runs in ServerErrorMiddleware, OUTSIDE
        RequestIDMiddleware (whose contextvar is reset by then) — it must
        read the signal off the request itself."""
        from fastapi import FastAPI

        from main import unhandled_exception_handler
        from services.request_context import RequestIDMiddleware

        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)
        app.add_exception_handler(Exception, unhandled_exception_handler)

        @app.get("/boom")
        async def boom(request: Request):
            request.state.user_id = USER_ID  # what auth_guard does
            raise RuntimeError("boom")

        r = TestClient(app, raise_server_exceptions=False).get("/boom", headers=headers)
        assert r.status_code == 500
        _drain()
        assert fake_client.capture.called is captured

class TestSettingsContract:
    """The shared contract with the frontend (PR #675): PATCH accepts
    analytics_opt_out, GET returns it, and the PATCH invalidates the cache."""

    def _tables(self, row):
        captured: dict = {}

        def table_side_effect(name):
            m = MagicMock()
            if name == "user_settings":
                m.select.return_value = [row]
                m.update.side_effect = (
                    lambda data, filters: captured.update({"data": data}) or [{}]
                )
            else:
                m.select.return_value = []
            return m

        return table_side_effect, captured

    def test_patch_accepts_and_invalidates(self, consent_db):
        from main import app

        analytics_consent.consent_for(USER_ID)  # warm the cache: ALLOWED
        consent_db.answers[USER_ID] = Consent.DENIED  # the DB after the write
        table_side_effect, captured = self._tables({"user_id": USER_ID})
        with patch("routes.profile.require_self"), \
             patch("routes.profile.table", side_effect=table_side_effect):
            r = TestClient(app).patch(
                f"/api/profile/{USER_ID}/settings", json={"analytics_opt_out": True},
            )
        assert r.status_code == 200
        assert captured["data"]["analytics_opt_out"] is True
        # The very next read in this process sees the opt-out.
        assert analytics_consent.consent_for(USER_ID) is Consent.DENIED

    def test_other_fields_do_not_invalidate(self, consent_db):
        from main import app

        table_side_effect, _ = self._tables({"user_id": USER_ID})
        with patch("routes.profile.require_self"), \
             patch("routes.profile.table", side_effect=table_side_effect), \
             patch("routes.profile.clear_analytics_consent_cache") as clear:
            TestClient(app).patch(f"/api/profile/{USER_ID}/settings", json={"theme": "dark"})
        clear.assert_not_called()

    def test_get_selects_and_returns_the_column(self):
        from main import app
        from routes.profile import _SETTINGS_COLS

        assert "analytics_opt_out" in _SETTINGS_COLS.split(",")
        table_side_effect, _ = self._tables({"user_id": USER_ID, "analytics_opt_out": True})
        with patch("routes.profile.require_self"), \
             patch("routes.profile.table", side_effect=table_side_effect):
            r = TestClient(app).get(f"/api/profile/{USER_ID}/settings")
        assert r.status_code == 200 and r.json()["analytics_opt_out"] is True

    def test_non_boolean_is_rejected(self):
        from main import app

        table_side_effect, captured = self._tables({"user_id": USER_ID})
        with patch("routes.profile.require_self"), \
             patch("routes.profile.table", side_effect=table_side_effect):
            r = TestClient(app).patch(
                f"/api/profile/{USER_ID}/settings", json={"analytics_opt_out": "maybe"},
            )
        assert r.status_code == 422 and "data" not in captured

    def test_migration_adds_the_column(self):
        from pathlib import Path

        migrations = Path(__file__).resolve().parents[1] / "db" / "migrations"
        hits = [
            p for p in migrations.glob("2*.sql")
            if "analytics_opt_out" in p.read_text()
        ]
        assert len(hits) == 1
        sql = " ".join(
            line for line in hits[0].read_text().splitlines()
            if not line.lstrip().startswith("--")
        )
        sql = " ".join(sql.split()).lower()
        assert (
            "alter table user_settings add column if not exists analytics_opt_out "
            "boolean not null default false"
        ) in sql


class TestCategoryKey:
    """Finding 2: the #117 category no longer clobbers a payload's own."""

    def test_payload_category_survives(self, fake_client, sink):
        events_service.log_event(
            "document.processed", category="usage", user_id=USER_ID,
            payload={"category": "syllabus", "doc_id": "d1"},
        )
        _drain()
        props = fake_client.capture.call_args.kwargs["properties"]
        assert props["category"] == "syllabus"
        assert props["event_category"] == "usage"


class TestDeletedUsers:
    """Finding 3: no event re-creates a deleted person; queues drain first."""

    def test_deleted_user_is_skipped(self, fake_client, consent_db, sink):
        consent_db.answers[USER_ID] = Consent.DENIED  # deleted_at is set
        events_service.log_event("note.created", category="usage", user_id=USER_ID)
        _drain()
        fake_client.capture.assert_not_called()

    def test_account_delete_invalidates_the_cached_yes(self, consent_db):
        from main import app

        analytics_consent.consent_for(USER_ID)  # cached ALLOWED
        consent_db.answers[USER_ID] = Consent.DENIED  # the row after the soft delete
        with patch("routes.profile.require_self"), \
             patch("routes.profile.table"), \
             patch("routes.profile.delete_posthog_person"):
            r = TestClient(app).request(
                "DELETE", f"/api/profile/{USER_ID}/account", json={"confirmation": "DELETE"},
            )
        assert r.status_code == 200
        assert analytics_consent.consent_for(USER_ID) is Consent.DENIED

    def test_person_delete_flushes_both_queues_before_the_request(
        self, monkeypatch, fake_client,
    ):
        monkeypatch.setattr(posthog_client, "disabled_reason", lambda **k: None)
        monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_key")
        monkeypatch.setenv("POSTHOG_PROJECT_ID", "4242")
        monkeypatch.setenv("POSTHOG_HOST", "https://us.i.posthog.com")
        monkeypatch.delenv("POSTHOG_API_HOST", raising=False)
        order: list[str] = []
        gate = __import__("threading").Event()

        def slow_lookup(uid):  # keeps the event in OUR queue when delete starts
            gate.wait(2)
            return Consent.ALLOWED

        monkeypatch.setattr(analytics_consent, "_lookup", slow_lookup)
        fake_client.capture.side_effect = lambda *a, **k: order.append("our-queue")
        fake_client.flush.side_effect = lambda **k: order.append("sdk-flush")
        events_service.log_event("note.created", category="usage", user_id=USER_ID)
        __import__("threading").Timer(0.2, gate.set).start()
        with patch("httpx.post", side_effect=lambda *a, **k: order.append("bulk_delete")
                   or MagicMock(status_code=202)):
            posthog_client.delete_person(USER_ID)
        assert order == ["our-queue", "sdk-flush", "bulk_delete"]
        assert fake_client.flush.call_args.kwargs["timeout_seconds"] > 0


class TestSentinelIds:
    """Finding 4: only a real users.id becomes a distinct_id."""

    @pytest.mark.parametrize("uid", ["anonymous", "backfill", None, "has space"])
    def test_placeholder_or_none_sends_nothing(self, uid, fake_client, consent_db, sink):
        events_service.log_event("note.created", category="usage", user_id=uid)
        _drain()
        fake_client.capture.assert_not_called()
        assert consent_db.calls == []

    def test_unknown_id_is_skipped(self, fake_client, consent_db, sink):
        events_service.log_event("note.created", category="usage", user_id="quizfix-user-0001")
        _drain()
        fake_client.capture.assert_not_called()

    def test_real_non_uuid_id_is_attributed(self, fake_client, sink):
        events_service.log_event("note.created", category="usage", user_id=USER_ID)
        _drain()
        assert fake_client.capture.call_args.kwargs["distinct_id"] == USER_ID

class TestErrorEvents:
    """Finding 5: error.4xx stays home; error.5xx carries the route template."""

    def test_4xx_is_not_mirrored(self, fake_client, sink):
        events_service.log_event(
            "error.4xx", category="error", user_id=USER_ID,
            payload={"path": f"/api/profile/{USER_ID}", "status_code": 404},
        )
        _drain()
        fake_client.capture.assert_not_called()
        events_service.flush_now()
        assert [r["event_type"] for r in sink] == ["error.4xx"]

    def test_5xx_path_is_the_matched_template(self, fake_client, sink):
        """Through the middleware: the mirrored path/route are the matched
        route template, never the raw path (which embeds an id)."""
        from fastapi import FastAPI

        from services.request_context import RequestIDMiddleware

        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        @app.get("/api/profile/{user_id}/thing")
        def thing(user_id: str, request: Request):
            request.state.user_id = USER_ID  # what auth_guard does
            raise RuntimeError("boom")

        r = TestClient(app, raise_server_exceptions=False).get(f"/api/profile/{USER_ID}/thing")
        assert r.status_code == 500
        _drain()
        props = fake_client.capture.call_args.kwargs["properties"]
        _drain()
        assert fake_client.capture.call_args.args[0] == "error.5xx"
        assert props["path"] == props["route"] == "/api/profile/{user_id}/thing"
        assert USER_ID not in json.dumps(props)
        events_service.flush_now()
        assert sink[0]["payload"]["path"] == f"/api/profile/{USER_ID}/thing"  # our row keeps it

    def test_path_outside_a_request_is_unmatched(self, fake_client, sink):
        events_service.log_event(
            "error.5xx", category="error", user_id=USER_ID,
            payload={"path": f"/api/profile/{USER_ID}", "route": "/api/profile/{user_id}"},
        )
        _drain()
        props = fake_client.capture.call_args.kwargs["properties"]
        assert props["path"] == props["route"] == "<unmatched>"


class TestApiHost:
    """Finding 7: the personal key only ever goes to a PostHog app host."""

    @pytest.mark.parametrize("ingest, expect", [
        ("https://us.i.posthog.com", "https://us.posthog.com"),
        ("https://eu.i.posthog.com/", "https://eu.posthog.com"),
        ("https://US.I.POSTHOG.COM", "https://us.posthog.com"),
        ("https://ph.example.com", None),
        ("https://evil.i.posthog.com.attacker.net", None),
        ("http://us.i.posthog.com", None),
    ])
    def test_derivation(self, ingest, expect, monkeypatch):
        import config

        monkeypatch.setenv("POSTHOG_HOST", ingest)
        monkeypatch.delenv("POSTHOG_API_HOST", raising=False)
        assert config.posthog_api_host() == expect

    def test_explicit_host_wins(self, monkeypatch):
        import config

        monkeypatch.setenv("POSTHOG_HOST", "https://ph.example.com")
        monkeypatch.setenv("POSTHOG_API_HOST", "https://ph-app.example.com/")
        assert config.posthog_api_host() == "https://ph-app.example.com"

    def test_unknown_host_skips_the_delete_with_a_warning(self, monkeypatch, caplog):
        monkeypatch.setattr(posthog_client, "disabled_reason", lambda **k: None)
        monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_key")
        monkeypatch.setenv("POSTHOG_PROJECT_ID", "4242")
        monkeypatch.setenv("POSTHOG_HOST", "https://ph.example.com")
        monkeypatch.delenv("POSTHOG_API_HOST", raising=False)
        with patch("httpx.post") as post, caplog.at_level(logging.WARNING, "sapling.posthog"):
            posthog_client.delete_person(USER_ID)
        post.assert_not_called()
        assert "POSTHOG_API_HOST" in caplog.text and "skipped" in caplog.text


class TestRequestIdOnce:
    """Finding 10: log_event resolves the ambient request id once."""

    def test_single_resolution_shared_by_row_and_mirror(self, fake_client, sink, monkeypatch):
        calls: list[int] = []

        def rid():
            calls.append(1)
            return f"rid-{len(calls)}"

        monkeypatch.setattr(events_service, "current_request_id", rid)
        events_service.log_event("note.created", category="usage", user_id=USER_ID)
        assert len(calls) == 1
        events_service.flush_now()
        assert sink[0]["request_id"] == "rid-1"
        _drain()
        assert fake_client.capture.call_args.kwargs["properties"]["request_id"] == "rid-1"


# ── 7. Second-round review fixes (PR #677) ──────────────────────────────────


OTHER_USER = "user_555555555555555555555"


class TestPathTemplating:
    """R1: no raw path — and so no other user's id — reaches PostHog from ANY
    event, not just error.5xx."""

    def test_403_on_another_users_path_mirrors_no_foreign_id(
        self, monkeypatch, fake_client, sink,
    ):
        from main import app
        from services import auth_guard
        from services.session_tokens import SESSION_COOKIE_NAME, mint_session

        # The REAL guard (conftest stubs it for route tests) — this test is
        # about the real 403 path and what it emits.
        monkeypatch.setattr(auth_guard, "_decode_session", auth_guard._real_decode_session)
        monkeypatch.setattr(auth_guard, "get_session_user_id", auth_guard._real_get_session_user_id)
        monkeypatch.setattr("routes.profile.require_self", auth_guard._real_require_self)
        monkeypatch.setattr(auth_guard, "SESSION_SECRET", "test-secret")
        token = mint_session(USER_ID, ttl=300, secret="test-secret")
        client = TestClient(app)
        client.cookies.set(SESSION_COOKIE_NAME, token)
        r = client.get(f"/api/profile/{OTHER_USER}/settings")
        assert r.status_code == 403
        _drain()
        sent = [(c.args[0], c.kwargs) for c in fake_client.capture.call_args_list]
        denied = [kw for name, kw in sent if name == "auth.permission_denied"]
        assert len(denied) == 1
        assert denied[0]["distinct_id"] == USER_ID
        assert denied[0]["properties"]["route"] == "/api/profile/{user_id}/settings"
        assert OTHER_USER not in json.dumps([kw for _, kw in sent], default=str)
        # Our own audit row keeps the raw path (first-party).
        events_service.flush_now()
        rows = [x for x in sink if x["event_type"] == "auth.permission_denied"]
        assert rows[0]["payload"]["route"] == f"/api/profile/{OTHER_USER}/settings"

    def test_user_id_keys_never_ride_in_properties(self, fake_client, sink):
        events_service.log_event(
            "note.created", category="usage", user_id=USER_ID,
            payload={"note_id": "n1", "user_id": OTHER_USER, "target_user_id": OTHER_USER},
        )
        _drain()
        props = fake_client.capture.call_args.kwargs["properties"]
        assert OTHER_USER not in json.dumps(props)
        assert props["note_id"] == "n1"


class TestInvalidationRace:
    """R3: a clear that lands while a read is in flight wins."""

    def test_clear_during_lookup_is_not_overwritten(self, monkeypatch):
        calls: list[str] = []

        def lookup(uid):
            calls.append(uid)
            if len(calls) == 1:
                # The settings PATCH / account delete lands mid-read.
                analytics_consent.clear_analytics_consent_cache(uid)
                return Consent.ALLOWED  # the stale answer this read saw
            return Consent.DENIED  # what the DB says now

        monkeypatch.setattr(analytics_consent, "_lookup", lookup)
        # The stale ALLOWED is neither stored nor returned: re-read -> DENIED.
        assert analytics_consent.consent_for(USER_ID) is Consent.DENIED
        assert analytics_consent.consent_for(USER_ID) is Consent.DENIED  # now cached
        assert calls == [USER_ID, USER_ID]

    def test_a_read_that_keeps_racing_fails_closed(self, monkeypatch):
        def lookup(uid):
            analytics_consent.clear_analytics_consent_cache(uid)  # every time
            return Consent.ALLOWED

        monkeypatch.setattr(analytics_consent, "_lookup", lookup)
        assert analytics_consent.consent_for(USER_ID) is Consent.DENIED

    def test_clear_all_during_lookup_is_not_overwritten(self, monkeypatch):
        calls: list[str] = []

        def lookup(uid):
            calls.append(uid)
            if len(calls) == 1:
                analytics_consent.clear_analytics_consent_cache()
            return Consent.ALLOWED

        monkeypatch.setattr(analytics_consent, "_lookup", lookup)
        assert analytics_consent.consent_for(USER_ID) is Consent.ALLOWED  # re-read
        assert analytics_consent.consent_for(USER_ID) is Consent.ALLOWED  # cached
        assert len(calls) == 2


class TestNoRecreateAfterDelete:
    """R4: consent is re-checked at span END; a second bulk_delete follows."""

    def _on(self, monkeypatch):
        monkeypatch.setattr(posthog_client, "disabled_reason", lambda **k: None)
        monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_key")
        monkeypatch.setenv("POSTHOG_PROJECT_ID", "4242")
        monkeypatch.setenv("POSTHOG_HOST", "https://us.i.posthog.com")
        monkeypatch.delenv("POSTHOG_API_HOST", raising=False)

    def test_second_delete_is_scheduled_after_the_ttl(self, monkeypatch):
        self._on(monkeypatch)
        monkeypatch.setattr(posthog_client, "_schedule_second_pass", _REAL_SCHEDULE)
        timers: list = []

        class FakeTimer:
            def __init__(self, delay, fn, args=(), kwargs=None):
                self.delay, self.fn, self.args, self.kwargs = delay, fn, args, kwargs or {}
                self.daemon = False
                timers.append(self)

            def start(self):
                pass

        monkeypatch.setattr(posthog_client.threading, "Timer", FakeTimer)
        with patch("httpx.post", return_value=MagicMock(status_code=202)) as post:
            posthog_client.delete_person(USER_ID)
            assert post.call_count == 1
            assert len(timers) == 1 and timers[0].daemon is True
            assert timers[0].delay >= analytics_consent._TTL_S + 1
            # When it fires: a full second pass (flush + bulk_delete).
            timers[0].fn(*timers[0].args, **timers[0].kwargs)
            assert post.call_count == 2
            assert post.call_args.kwargs["json"] == {
                "distinct_ids": [USER_ID], "delete_events": True,
            }

    def test_no_second_delete_when_the_first_was_skipped(self, monkeypatch):
        self._on(monkeypatch)
        monkeypatch.delenv("POSTHOG_PERSONAL_API_KEY")
        scheduled = MagicMock()
        monkeypatch.setattr(posthog_client, "_schedule_second_pass", scheduled)
        with patch("httpx.post") as post:
            posthog_client.delete_person(USER_ID)
        post.assert_not_called()
        scheduled.assert_not_called()


class TestLaneSilence:
    """R6: the local E2E / explore stacks turn PostHog off explicitly, not
    only by inference from function mode."""

    @pytest.mark.parametrize("script", ["scripts/e2e-up.sh", "scripts/explore.sh"])
    def test_scripts_export_posthog_disabled(self, script):
        from pathlib import Path

        text = (Path(__file__).resolve().parents[2] / script).read_text()
        assert re.search(r"^\s*export POSTHOG_DISABLED=1\s*$", text, re.M), script


class TestGateUsesTheSeam:
    """R7: the gate reads the mode from agents._providers.model_mode()."""

    def test_disabled_reason_passes_the_seams_mode(self, monkeypatch):
        from agents import _providers

        monkeypatch.setattr(_providers, "model_mode", lambda: "sentinel-mode")
        seen = {}

        def spy(env, *, under_pytest, model_mode, for_erasure=False):
            seen["mode"] = model_mode
            return None

        monkeypatch.setattr(posthog_client, "_disabled_reason_for", spy)
        posthog_client.disabled_reason()
        assert seen["mode"] == "sentinel-mode"

    def test_no_second_mode_parser(self):
        import inspect

        assert "SAPLING_MODEL_MODE\") or" not in inspect.getsource(posthog_client)


# ── 8. Round 3: one queue, one worker; AI analytics from the usage chokepoint ─


def _authed_app(consent_db):
    """A small app behind the real RequestIDMiddleware whose handlers sign
    the user in the way the real guard does (``request.state.user_id``)."""

    from services.request_context import RequestIDMiddleware

    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    def signed_in(request: Request) -> str:  # a SYNC Depends -> threadpool
        request.state.user_id = USER_ID  # what auth_guard.get_session_user_id does
        return USER_ID

    def background_work():
        # No user_id of its own (like the sweeper-style events).
        events_service.log_event("rag.index_failed", category="error", payload={"doc_id": "d"})

    @app.post("/bg")
    async def with_background(bt: BackgroundTasks, user: str = Depends(signed_in)):
        bt.add_task(background_work)
        return {"ok": True}

    @app.post("/dep")
    def with_sync_dep(user: str = Depends(signed_in)):
        events_service.log_event("note.created", category="usage", user_id=None)
        return {"ok": True}

    return app


class TestRequestScopedActor:
    """An event that names no user belongs to the request's signed-in user —
    read from scope["state"], which BackgroundTasks and sync Depends share."""

    @pytest.mark.parametrize("path", ["/bg", "/dep"])
    def test_opted_out_students_userless_event_is_dropped(
        self, path, fake_client, consent_db, sink,
    ):
        consent_db.answers[USER_ID] = Consent.DENIED
        r = TestClient(_authed_app(consent_db)).post(path)
        assert r.status_code == 200
        _drain()
        fake_client.capture.assert_not_called()
        events_service.flush_now()
        assert sink  # our own table still has the row

    @pytest.mark.parametrize("path", ["/bg", "/dep"])
    def test_allowed_students_userless_event_is_attributed(
        self, path, fake_client, consent_db, sink,
    ):
        r = TestClient(_authed_app(consent_db)).post(path)
        assert r.status_code == 200
        _drain()
        fake_client.capture.assert_called_once()
        assert fake_client.capture.call_args.kwargs["distinct_id"] == USER_ID


class TestColdCacheDelivers:
    """A cold consent cache DELAYS an event on the worker; it never drops it."""

    def test_first_event_is_delivered(self, fake_client, consent_db, monkeypatch, sink):
        import threading

        release = threading.Event()
        real = analytics_consent._lookup

        def slow(uid):
            release.wait(2)
            return real(uid)

        monkeypatch.setattr(analytics_consent, "_lookup", slow)

        async def route():
            events_service.log_event("note.created", category="usage", user_id=USER_ID)

        asyncio.run(route())  # returns at once: nothing on the request path waits
        fake_client.capture.assert_not_called()
        release.set()
        _drain()
        fake_client.capture.assert_called_once()
        assert fake_client.capture.call_args.kwargs["distinct_id"] == USER_ID


class TestNoReadOnTheLoop:
    """No thread running an event loop ever performs the consent read."""

    def test_reads_happen_only_on_the_worker(self, fake_client, monkeypatch, sink):
        import threading

        seen: list[tuple[str, bool]] = []

        def lookup(uid):
            try:
                asyncio.get_running_loop()
                on_loop = True
            except RuntimeError:
                on_loop = False
            seen.append((threading.current_thread().name, on_loop))
            return Consent.ALLOWED

        monkeypatch.setattr(analytics_consent, "_lookup", lookup)

        async def async_paths():
            events_service.log_event("note.created", category="usage", user_id=USER_ID)
            posthog_client.capture_exception(ValueError("x"), user_id=USER_ID, request_id="r")
            events_service.log_llm_usage(
                feature="tutor", task="chat", model="gemini-2.5-flash",
                usage={"input_tokens": 3, "output_tokens": 2}, user_id=USER_ID,
            )

        asyncio.run(async_paths())
        _drain()
        assert seen and all(name == "posthog-send" and not loop for name, loop in seen)
        assert [c.args[0] for c in fake_client.capture.call_args_list] == [
            "note.created", "$exception", "$ai_generation",
        ]


class TestAiGeneration:
    """$ai_generation comes from the usage chokepoint and carries no content."""

    _ALLOWED_KEYS = {
        "$ai_model", "$ai_provider", "$ai_input_tokens", "$ai_output_tokens",
        "$ai_total_cost_usd", "$ai_latency", "$ai_trace_id", "$ai_span_name",
        "feature", "task",
    }

    def _run(self):
        from pydantic_ai import Agent
        from pydantic_ai.messages import ModelResponse, TextPart
        from pydantic_ai.models.function import FunctionModel

        agent = Agent(
            FunctionModel(lambda messages, info: ModelResponse(parts=[TextPart(f"out {SECRET}")])),
            system_prompt=f"You tutor {SECRET}.",
        )
        return asyncio.run(agent.run(f"hello {SECRET}"))

    def test_record_agent_usage_sends_a_content_free_generation(
        self, fake_client, monkeypatch, sink,
    ):
        from agents.usage import record_agent_usage

        monkeypatch.setattr(events_service, "current_request_id", lambda: "req-ai-1")
        result = self._run()
        assert SECRET in result.output
        record_agent_usage(result, feature="tutor", task="chat", user_id=USER_ID)
        _drain()
        fake_client.capture.assert_called_once()
        call = fake_client.capture.call_args
        assert call.args == ("$ai_generation",)
        assert call.kwargs["distinct_id"] == USER_ID
        props = call.kwargs["properties"]
        assert set(props) <= self._ALLOWED_KEYS
        assert props["$ai_trace_id"] == "req-ai-1"
        assert props["$ai_input_tokens"] > 0 and props["$ai_output_tokens"] > 0
        assert props["feature"] == "tutor" and props["task"] == "chat"
        assert "$ai_input" not in props and "$ai_output_choices" not in props
        assert SECRET not in json.dumps(call.kwargs, default=str)

    def test_priced_model_carries_cost_and_provider(self, fake_client, sink):
        events_service.log_llm_usage(
            feature="quiz", task="quiz", model="gemini-2.5-flash",
            usage={"input_tokens": 1000, "output_tokens": 500}, user_id=USER_ID,
        )
        _drain()
        props = fake_client.capture.call_args.kwargs["properties"]
        assert props["$ai_provider"] == "gemini"
        assert props["$ai_model"] == "gemini-2.5-flash"
        assert props["$ai_total_cost_usd"] > 0

    def test_opted_out_student_sends_no_generation(self, fake_client, consent_db, sink):
        from agents.usage import record_agent_usage

        consent_db.answers[USER_ID] = Consent.DENIED
        record_agent_usage(self._run(), feature="tutor", task="chat", user_id=USER_ID)
        _drain()
        fake_client.capture.assert_not_called()
        events_service.flush_now()
        assert [r for r in sink if r.get("feature") == "tutor"]  # our llm_usage row

    def test_kill_switch_stops_it(self, fake_client, monkeypatch, sink):
        monkeypatch.setenv("EVENTS_LOGGING_ENABLED", "false")
        events_service.log_llm_usage(
            feature="quiz", task="quiz", model="m", usage={}, user_id=USER_ID,
        )
        _drain()
        fake_client.capture.assert_not_called()

    def test_no_otel_export_and_no_agent_monkeypatch(self):
        """The OTel span export, its allowlist processor and the Agent.iter
        wrapper are gone: importing the app leaves pydantic-ai untouched."""
        import importlib.util

        from pydantic_ai import Agent

        import main  # noqa: F401

        assert importlib.util.find_spec("services.ai_observability") is None
        assert not getattr(Agent.iter, "__sapling_ai_attribution__", False)


class TestPrivacySignalDrops:
    """DNT/GPC captured at enqueue: nothing is queued at all."""

    @pytest.mark.parametrize("header", [{"Sec-GPC": "1"}, {"DNT": "1"}])
    def test_events_and_generations_are_dropped(self, header, fake_client, sink):
        from fastapi import FastAPI

        from services.request_context import RequestIDMiddleware

        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        @app.post("/work")
        def work():
            events_service.log_event("note.created", category="usage", user_id=USER_ID)
            events_service.log_llm_usage(
                feature="tutor", task="chat", model="gemini-2.5-flash",
                usage={"input_tokens": 1, "output_tokens": 1}, user_id=USER_ID,
            )
            return {}

        TestClient(app).post("/work", headers=header)
        _drain()
        fake_client.capture.assert_not_called()
        assert posthog_client._queue.unfinished_tasks == 0


class TestBoundedQueue:
    """The queue is bounded and drops the OLDEST item when full."""

    def test_drop_oldest_with_a_warning(self, fake_client, monkeypatch, caplog):
        import queue as queue_mod

        small: queue_mod.Queue = queue_mod.Queue(maxsize=3)
        monkeypatch.setattr(posthog_client, "_queue", small)
        monkeypatch.setattr(posthog_client, "_ensure_worker", lambda: None)  # nobody drains
        monkeypatch.setattr(posthog_client, "_dropped", 0)
        with caplog.at_level(logging.WARNING, "sapling.posthog"):
            for i in range(5):
                posthog_client.mirror_event(
                    f"e{i}", category="usage", user_id=USER_ID, request_id=None, payload={},
                )
        names = [small.get_nowait().name for _ in range(small.qsize())]
        assert names == ["e2", "e3", "e4"]
        assert posthog_client._dropped == 2
        assert caplog.text.count("PostHog queue full") == 1  # warn once, not per drop
        for _ in names:
            small.task_done()


# ── 9. Final hardening (PR #677) ────────────────────────────────────────────


def _postgrest_error(body: str):
    """What db/connection.py raises: httpx's HTTPStatusError, whose str() is
    only the status line — the column is named in the RESPONSE BODY."""
    import httpx

    request = httpx.Request("GET", "http://supabase.test/rest/v1/user_settings")
    response = httpx.Response(400, text=body, request=request)
    return httpx.HTTPStatusError("Client error '400 Bad Request'", request=request, response=response)


_MISSING_OPT_OUT_BODY = json.dumps({
    "code": "42703",
    "message": "column user_settings_1.analytics_opt_out does not exist",
})


class TestQueueMaxParsing:
    """POSTHOG_QUEUE_MAX never raises at import and never unbounds the queue."""

    @pytest.mark.parametrize("raw, expect, warns", [
        ("", 10_000, False),
        ("  ", 10_000, False),
        ("25", 25, False),
        ("abc", 10_000, True),
        ("1e3", 10_000, True),
        ("0", 10_000, True),
        ("-5", 10_000, True),
    ])
    def test_parsing(self, raw, expect, warns, caplog):
        with caplog.at_level(logging.WARNING, "sapling.posthog"):
            got = posthog_client._queue_max_from_env({"POSTHOG_QUEUE_MAX": raw})
        assert got == expect
        assert ("POSTHOG_QUEUE_MAX" in caplog.text) is warns

    @pytest.mark.parametrize("raw", ["abc", "0", "-1", ""])
    def test_bad_value_at_import_neither_raises_nor_unbounds(self, raw):
        import subprocess
        from pathlib import Path

        backend = Path(__file__).resolve().parents[1]
        out = subprocess.run(
            [sys.executable, "-c",
             "import services.posthog_client as p; print(p._queue.maxsize)"],
            cwd=backend, env={**os.environ, "POSTHOG_QUEUE_MAX": raw},
            capture_output=True, text=True, timeout=60,
        )
        assert out.returncode == 0, out.stderr[-2000:]
        assert int(out.stdout.strip().splitlines()[-1]) == 10_000


class TestDeployOrderRace:
    """Code live before migration 20260927220057: settings keep working, the
    PATCH says 503, and consent treats the missing column as "no"."""

    def _tables(self, *, first_select_error=None, update_error=None):
        calls: dict = {"selects": [], "updates": []}

        def table_side_effect(name):
            m = MagicMock()
            if name == "user_settings":
                def select(cols, filters=None):
                    calls["selects"].append(cols)
                    if first_select_error is not None and len(calls["selects"]) == 1:
                        raise first_select_error
                    return [{"user_id": USER_ID, "theme": "dark"}]

                def update(data, filters=None):
                    calls["updates"].append(data)
                    if update_error is not None:
                        raise update_error
                    return [{}]

                m.select.side_effect = select
                m.update.side_effect = update
            else:
                m.select.return_value = []
            return m

        return table_side_effect, calls

    def test_get_retries_without_the_missing_column(self):
        from main import app

        table_side_effect, calls = self._tables(
            first_select_error=_postgrest_error(_MISSING_OPT_OUT_BODY),
        )
        with patch("routes.profile.require_self"), \
             patch("routes.profile.table", side_effect=table_side_effect):
            r = TestClient(app).get(f"/api/profile/{USER_ID}/settings")
        assert r.status_code == 200
        assert r.json()["theme"] == "dark" and "analytics_opt_out" not in r.json()
        assert "analytics_opt_out" in calls["selects"][0]
        assert "analytics_opt_out" not in calls["selects"][1]

    def test_pgrst204_shape_is_recognised_too(self):
        from services.analytics_consent import missing_opt_out_column

        assert missing_opt_out_column(_postgrest_error(json.dumps({
            "code": "PGRST204",
            "message": "Could not find the 'analytics_opt_out' column of "
                       "'user_settings' in the schema cache",
        })))
        # Another column missing is a real schema problem: not swallowed.
        assert not missing_opt_out_column(_postgrest_error(json.dumps({
            "code": "42703", "message": "column user_settings.theme does not exist",
        })))

    def test_an_unrelated_error_still_surfaces(self):
        from main import app

        table_side_effect, _ = self._tables(first_select_error=_postgrest_error(json.dumps({
            "code": "42703", "message": "column user_settings.theme does not exist",
        })))
        with patch("routes.profile.require_self"), \
             patch("routes.profile.table", side_effect=table_side_effect):
            r = TestClient(app, raise_server_exceptions=False).get(
                f"/api/profile/{USER_ID}/settings",
            )
        assert r.status_code == 500

    def test_patch_of_the_missing_column_is_a_503(self):
        from main import app

        table_side_effect, calls = self._tables(
            first_select_error=_postgrest_error(_MISSING_OPT_OUT_BODY),
            update_error=_postgrest_error(_MISSING_OPT_OUT_BODY),
        )
        with patch("routes.profile.require_self"), \
             patch("routes.profile.table", side_effect=table_side_effect):
            r = TestClient(app, raise_server_exceptions=False).patch(
                f"/api/profile/{USER_ID}/settings", json={"analytics_opt_out": True},
            )
        assert r.status_code == 503
        assert "not available yet" in r.json()["detail"]

    def test_consent_treats_the_missing_column_as_denied(self, monkeypatch, caplog):
        monkeypatch.setattr(analytics_consent, "_lookup", _REAL_LOOKUP)
        t = MagicMock()
        t.return_value.select.side_effect = _postgrest_error(_MISSING_OPT_OUT_BODY)
        monkeypatch.setattr("db.connection.table", t)
        with caplog.at_level(logging.WARNING, "sapling.analytics_consent"):
            assert analytics_consent.consent_for(USER_ID) is Consent.DENIED
        assert "migration pending" in caplog.text


class TestProviderPassthrough:
    """$ai_provider is the recorded provider; derived only when missing."""

    @pytest.mark.parametrize("provider", ["typesafe", "jev"])
    def test_recorded_provider_wins(self, provider, fake_client, sink):
        events_service.log_llm_usage(
            feature="tutor", task="chat", model="jev-1.13.0", provider=provider,
            usage={"input_tokens": 5, "output_tokens": 3}, user_id=USER_ID,
        )
        _drain()
        props = fake_client.capture.call_args.kwargs["properties"]
        assert props["$ai_provider"] == provider
        assert props["$ai_model"] == "jev-1.13.0"

    @pytest.mark.parametrize("provider, model, expect", [
        (None, "gemini-2.5-flash", "gemini"),
        ("", "google-gla:gemini-2.5-flash", "google-gla"),
        ("  ", "jev-1.13.0", "unknown"),
    ])
    def test_derived_only_when_missing(self, provider, model, expect, fake_client):
        posthog_client.capture_ai_generation(
            user_id=USER_ID, model=model, provider=provider, input_tokens=1,
            output_tokens=1, cost_usd=None, request_id="r", feature="f", task=None,
        )
        _drain()
        assert fake_client.capture.call_args.kwargs["properties"]["$ai_provider"] == expect

    def test_no_dead_latency_parameter(self):
        import inspect

        params = inspect.signature(posthog_client.capture_ai_generation).parameters
        assert "latency_s" not in params
        assert "log_llm_usage" in posthog_client.capture_ai_generation.__doc__


class TestConsentReadTimeout:
    """The worker's read fails fast instead of holding the queue for 30 s."""

    def test_lookup_passes_a_short_timeout(self, monkeypatch):
        monkeypatch.setattr(analytics_consent, "_lookup", _REAL_LOOKUP)
        t = MagicMock()
        t.return_value.select.return_value = []
        monkeypatch.setattr("db.connection.table", t)
        analytics_consent.consent_for(USER_ID)
        timeout = t.return_value.select.call_args.kwargs["timeout"]
        assert 0 < timeout <= 5

    def test_select_forwards_the_timeout_to_the_shared_client(self, monkeypatch):
        from db import connection

        fake = MagicMock()
        fake.get.return_value = MagicMock(json=lambda: [], raise_for_status=lambda: None)
        monkeypatch.setattr(connection, "_client", fake)
        connection.table("users").select("id", timeout=3.0)
        assert fake.get.call_args.kwargs["timeout"] == 3.0
        connection.table("users").select("id")
        assert "timeout" not in fake.get.call_args.kwargs  # default path unchanged

    def test_a_timeout_is_denied(self, monkeypatch):
        import httpx

        monkeypatch.setattr(analytics_consent, "_lookup", _REAL_LOOKUP)
        t = MagicMock()
        t.return_value.select.side_effect = httpx.ReadTimeout("slow")
        monkeypatch.setattr("db.connection.table", t)
        assert analytics_consent.consent_for(USER_ID) is Consent.DENIED


class TestErasureIsNotCapture:
    """delete_person runs whenever it is configured — the kill switch and a
    missing token stop capture, not erasure — and only WARNs where PostHog
    was ever configured."""

    @pytest.fixture
    def outside_pytest(self, monkeypatch):
        """The REAL gate, evaluated as if not under pytest."""
        monkeypatch.setattr(
            posthog_client, "disabled_reason",
            lambda *, for_erasure=False: posthog_client._disabled_reason_for(
                os.environ, under_pytest=False, model_mode="real", for_erasure=for_erasure,
            ),
        )
        for var in (
            "POSTHOG_PROJECT_TOKEN", "POSTHOG_PERSONAL_API_KEY", "POSTHOG_PROJECT_ID",
            "POSTHOG_API_HOST", "POSTHOG_DISABLED", "APP_ENV",
        ):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("POSTHOG_HOST", "https://us.i.posthog.com")

    def _configure(self, monkeypatch):
        monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_key")
        monkeypatch.setenv("POSTHOG_PROJECT_ID", "4242")

    @pytest.mark.parametrize("extra", [
        {"POSTHOG_DISABLED": "1"},                               # kill switch on
        {},                                                      # no project token
        {"POSTHOG_DISABLED": "1", "POSTHOG_PROJECT_TOKEN": "phc_x"},
    ])
    def test_configured_deletes_even_when_capture_is_off(
        self, extra, outside_pytest, monkeypatch,
    ):
        self._configure(monkeypatch)
        for k, v in extra.items():
            monkeypatch.setenv(k, v)
        with patch("httpx.post", return_value=MagicMock(status_code=202)) as post:
            posthog_client.delete_person(USER_ID)
        post.assert_called_once()

    def test_never_configured_deletes_nothing_and_says_nothing(
        self, outside_pytest, caplog,
    ):
        with patch("httpx.post") as post, caplog.at_level(logging.WARNING, "sapling.posthog"):
            posthog_client.delete_person(USER_ID)
        post.assert_not_called()
        assert caplog.records == []

    @pytest.mark.parametrize("env, needle", [
        ({"POSTHOG_PROJECT_TOKEN": "phc_x"}, "POSTHOG_PERSONAL_API_KEY"),
        ({"POSTHOG_PERSONAL_API_KEY": "phx_key"}, "POSTHOG_PROJECT_ID"),
        ({"POSTHOG_PERSONAL_API_KEY": "phx_key", "POSTHOG_PROJECT_ID": "4242",
          "POSTHOG_HOST": "https://ph.example.com"}, "POSTHOG_API_HOST"),
    ])
    def test_ever_configured_but_incomplete_warns(
        self, env, needle, outside_pytest, monkeypatch, caplog,
    ):
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        with patch("httpx.post") as post, caplog.at_level(logging.WARNING, "sapling.posthog"):
            posthog_client.delete_person(USER_ID)
        post.assert_not_called()
        assert "skipped" in caplog.text and needle in caplog.text

    def test_deterministic_lanes_still_block_erasure(self, monkeypatch, caplog):
        self._configure(monkeypatch)
        monkeypatch.setattr(
            posthog_client, "disabled_reason",
            lambda *, for_erasure=False: posthog_client._disabled_reason_for(
                os.environ, under_pytest=False, model_mode="function", for_erasure=for_erasure,
            ),
        )
        with patch("httpx.post") as post, caplog.at_level(logging.WARNING, "sapling.posthog"):
            posthog_client.delete_person(USER_ID)
        post.assert_not_called()
        assert "skipped" in caplog.text

    @pytest.mark.parametrize("script", ["scripts/e2e-up.sh", "scripts/explore.sh"])
    def test_lane_scripts_blank_the_personal_key(self, script):
        from pathlib import Path

        text = (Path(__file__).resolve().parents[2] / script).read_text()
        assert re.search(r"^\s*export POSTHOG_PERSONAL_API_KEY=(\s|$)", text, re.M), script


class TestExceptionPayloadAtEnqueue:
    """The queue holds plain data: no exception, traceback or frame object —
    those would keep every frame's locals (decrypted content) alive."""

    def test_queued_item_holds_no_live_objects(self, fake_client, monkeypatch):
        import types

        queued: list = []
        monkeypatch.setattr(posthog_client, "_enqueue", queued.append)

        def handler_with_decrypted_locals():
            note_body = SECRET  # noqa: F841 - must not be reachable from the queue
            raise ValueError(f"bad input: {SECRET}")

        try:
            handler_with_decrypted_locals()
        except ValueError as exc:
            posthog_client.capture_exception(exc, user_id=USER_ID, request_id="r")
        assert len(queued) == 1
        item = queued[0]

        def walk(obj):
            assert not isinstance(
                obj, (BaseException, types.TracebackType, types.FrameType),
            ), type(obj)
            if isinstance(obj, dict):
                for v in obj.values():
                    walk(v)
            elif isinstance(obj, (list, tuple)):
                for v in obj:
                    walk(v)

        walk(tuple(item))
        assert SECRET not in json.dumps(item.properties, default=str)
        exc_list = item.properties["$exception_list"]
        assert exc_list[0]["type"] == "ValueError"
        assert exc_list[0]["value"] == "[redacted]"
        assert exc_list[0]["stacktrace"]["frames"]


class TestMigrationHeader:
    def test_header_names_the_current_seam(self):
        from pathlib import Path

        sql = (
            Path(__file__).resolve().parents[1]
            / "db" / "migrations" / "20260927220057_llm_cost_precision_and_analytics_opt_out.sql"
        ).read_text()
        assert "ai_observability" not in sql
        assert "posthog_client" in sql and "analytics_consent" in sql


# ── 10. Convergence review (PR #677) ────────────────────────────────────────


def _signed_in_app(route_body):
    """An app behind the real RequestIDMiddleware whose one route runs
    ``route_body(request)`` after signing USER_ID in the way auth_guard does."""
    from services.request_context import RequestIDMiddleware

    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.post("/api/work/{item_id}")
    def work(item_id: str, request: Request):
        request.state.user_id = USER_ID
        route_body(request)
        return {}

    return app


class TestNoPersonlessEvents:
    """Every PostHog event is attributed to a consenting student, or not sent."""

    def _usage_result(self):
        from pydantic_ai import Agent
        from pydantic_ai.messages import ModelResponse, TextPart
        from pydantic_ai.models.function import FunctionModel

        agent = Agent(FunctionModel(lambda m, i: ModelResponse(parts=[TextPart("ok")])))
        return asyncio.run(agent.run("hi"))

    def test_opted_out_students_usage_outside_a_request_sends_nothing(
        self, fake_client, consent_db, sink,
    ):
        """The document pipeline / DBOS / sweeper case: no request scope."""
        from agents.usage import record_agent_usage

        consent_db.answers[USER_ID] = Consent.DENIED
        record_agent_usage(self._usage_result(), feature="documents", task="summary", user_id=USER_ID)
        _drain()
        fake_client.capture.assert_not_called()

    def test_userless_usage_outside_a_request_sends_nothing(self, fake_client, consent_db, sink):
        from agents.usage import record_agent_usage

        record_agent_usage(self._usage_result(), feature="documents", task="summary")
        _drain()
        fake_client.capture.assert_not_called()
        assert consent_db.calls == []
        events_service.flush_now()
        assert [r for r in sink if r.get("feature") == "documents"]  # our llm_usage row

    def test_userless_exception_outside_a_request_sends_nothing(self, fake_client):
        posthog_client.capture_exception(ValueError("x"), user_id=None, request_id="r")
        _drain()
        fake_client.capture.assert_not_called()


class TestNoMisattribution:
    """Only a ``user_id is None`` falls back to the session user. A caller that
    names someone — even a placeholder or a malformed id — is never
    re-attributed to whoever is signed in."""

    @pytest.mark.parametrize("uid", ["anonymous", "backfill", "has space", "", "x" * 200])
    def test_non_none_invalid_id_is_dropped_not_substituted(self, uid, fake_client, sink):
        app = _signed_in_app(lambda request: events_service.log_event(
            "note.created", category="usage", user_id=uid,
        ))
        assert TestClient(app).post("/api/work/1").status_code == 200
        _drain()
        fake_client.capture.assert_not_called()

    def test_none_falls_back_to_the_session_user(self, fake_client, sink):
        app = _signed_in_app(lambda request: events_service.log_event(
            "note.created", category="usage", user_id=None,
        ))
        assert TestClient(app).post("/api/work/1").status_code == 200
        _drain()
        assert fake_client.capture.call_args.kwargs["distinct_id"] == USER_ID

    def test_actor_rule_directly(self):
        from services.request_context import _REQUEST_CTX, RequestView

        token = _REQUEST_CTX.set(RequestView({"state": {"user_id": USER_ID}}))
        try:
            assert posthog_client._actor(None) == USER_ID
            assert posthog_client._actor("anonymous") is None
            assert posthog_client._actor("bad id") is None
            assert posthog_client._actor(" user_42 ") == "user_42"
        finally:
            _REQUEST_CTX.reset(token)
        assert posthog_client._actor(None) is None  # no request, nobody


class TestRuntimeKillSwitch:
    """POSTHOG_DISABLED takes effect without a restart — on submit AND for
    items already queued."""

    @pytest.fixture
    def real_gate(self, fake_client, monkeypatch):
        from agents._providers import model_mode

        monkeypatch.setattr(
            posthog_client, "disabled_reason",
            lambda *, for_erasure=False: posthog_client._disabled_reason_for(
                os.environ, under_pytest=False, model_mode=model_mode(),
                for_erasure=for_erasure,
            ),
        )
        monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "phc_test")
        monkeypatch.setenv("SAPLING_MODEL_MODE", "real")
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.delenv("POSTHOG_DISABLED", raising=False)
        return fake_client

    def test_flipping_the_switch_stops_new_events(self, real_gate, monkeypatch, sink):
        events_service.log_event("note.created", category="usage", user_id=USER_ID)
        _drain()
        assert real_gate.capture.call_count == 1
        monkeypatch.setenv("POSTHOG_DISABLED", "1")
        events_service.log_event("note.created", category="usage", user_id=USER_ID)
        _drain()
        assert real_gate.capture.call_count == 1
        assert posthog_client._queue.unfinished_tasks == 0

    def test_items_queued_before_the_switch_are_dropped(
        self, real_gate, monkeypatch, sink,
    ):
        import threading

        release = threading.Event()

        def slow(uid):
            release.wait(2)
            return Consent.ALLOWED

        monkeypatch.setattr(analytics_consent, "_lookup", slow)
        events_service.log_event("note.created", category="usage", user_id=USER_ID)
        events_service.log_event("note.created", category="usage", user_id=USER_ID)
        monkeypatch.setenv("POSTHOG_DISABLED", "1")
        release.set()
        _drain()
        # At most the one item already past the gate check when it flipped.
        assert real_gate.capture.call_count <= 1


class TestSettingsEtagShape:
    """The GET /settings ETag changes with the body's shape, not only its
    updated_at — a pre-migration / pre-deploy cached body must miss."""

    def _etag(self, row):
        from main import app

        def table_side_effect(name):
            m = MagicMock()
            m.select.return_value = [row] if name == "user_settings" else []
            return m

        with patch("routes.profile.require_self"), \
             patch("routes.profile.table", side_effect=table_side_effect):
            r = TestClient(app).get(f"/api/profile/{USER_ID}/settings")
        assert r.status_code == 200
        return r.headers["etag"]

    def test_with_and_without_the_column_differ(self):
        stamp = "2026-09-27T00:00:00Z"
        with_col = self._etag({"user_id": USER_ID, "updated_at": stamp, "analytics_opt_out": False})
        without = self._etag({"user_id": USER_ID, "updated_at": stamp})
        assert with_col != without

    def test_differs_from_the_pre_change_formula(self):
        from services.http_cache import make_etag

        stamp = "2026-09-27T00:00:00Z"
        old = make_etag("settings", USER_ID, stamp)
        assert self._etag({"user_id": USER_ID, "updated_at": stamp, "analytics_opt_out": False}) != old


class TestRequestContextIsNarrow:
    """The contextvar holds the request's state dict + a route accessor —
    never the ASGI scope with its headers and cookies."""

    def test_view_exposes_only_state_and_route(self, fake_client, sink):
        from services.request_context import _REQUEST_CTX, RequestView

        seen: dict = {}

        def body(request):
            view = _REQUEST_CTX.get()
            seen["type"] = type(view)
            seen["slots"] = RequestView.__slots__
            seen["user"] = view.state.get("user_id")
            seen["route"] = view.route_template()
            seen["has_headers"] = any(
                hasattr(view, a) for a in ("headers", "scope", "cookies", "query_string")
            )

        app = _signed_in_app(body)
        TestClient(app).post(
            "/api/work/42", headers={"Cookie": "sapling_session=SECRETCOOKIE"},
        )
        assert seen["type"] is RequestView
        assert set(seen["slots"]) == {"state", "_route_of"}
        assert seen["user"] == USER_ID  # request.state is the same dict
        assert seen["route"] == "/api/work/{item_id}"
        assert seen["has_headers"] is False


class TestOneSubmitPath:
    def test_all_three_uses_go_through_submit(self, fake_client, monkeypatch):
        calls: list[str] = []
        real = posthog_client._submit
        monkeypatch.setattr(
            posthog_client, "_submit",
            lambda name, *a, **k: calls.append(name) or real(name, *a, **k),
        )
        events_service.log_event("note.created", category="usage", user_id=USER_ID)
        events_service.log_llm_usage(
            feature="f", task="t", model="gemini-2.5-flash", usage={}, user_id=USER_ID,
        )
        posthog_client.capture_exception(ValueError("x"), user_id=USER_ID, request_id="r")
        assert calls == ["note.created", "$ai_generation", "$exception"]


class TestNoRawClientApi:
    def test_dead_public_api_is_gone(self):
        for name in ("is_enabled", "get_posthog_client", "queue_dropped_count"):
            assert not hasattr(posthog_client, name), name

    def test_initialize_returns_a_bool_not_the_client(self):
        assert posthog_client.initialize_posthog() is False  # pytest: gate is off


class TestProductAnalyticsFlag:
    """#620: `product_analytics` gates the worker's delivery, after the
    disabled_reason() re-check and before the consent read."""

    def test_worker_drops_when_flag_off(self, monkeypatch):
        from services import posthog_client as pc
        sent = []

        class _C:
            def capture(self, *a, **k):
                sent.append(a)

        monkeypatch.setattr(pc, "_client", _C())
        monkeypatch.setattr(pc, "disabled_reason", lambda **k: None)
        monkeypatch.setattr(pc, "_distinct_id_for", lambda actor: actor)
        item = pc._Item(name="x", properties={}, actor="u1", captured_at=0.0)
        monkeypatch.setattr("services.feature_flags.flag_on", lambda k, u: False)
        pc._deliver(item)
        assert sent == []
        monkeypatch.setattr("services.feature_flags.flag_on", lambda k, u: True)
        pc._deliver(item)
        assert len(sent) == 1
