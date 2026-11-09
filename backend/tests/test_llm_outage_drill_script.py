"""#119: `scripts/llm_outage_drill.py`, the drill client, against an
`httpx.MockTransport` standing in for the backend (it never runs remotely in
tests). Pins the localhost guard, the session sources, how it tells a
user-facing error from a served request (JSON and SSE), and its exit codes."""
from __future__ import annotations

import json

import httpx
import pytest

from scripts import llm_outage_drill as drill


def _backend(*, fail: set[str] = frozenset(), sse_error: bool = False, admin: bool = True):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen.append(f"{request.method} {path}")
        if path == "/api/auth/test-login":
            return httpx.Response(200, json={"token": "tok"})
        assert request.headers.get("cookie") == "sapling_session=tok" or path == "/api/auth/test-login"
        if path.startswith("/api/admin/"):
            if not admin:
                return httpx.Response(403, json={"detail": "Admin access required"})
            if path == "/api/admin/llm/drill":
                return httpx.Response(200, json={
                    "forced_outage": {"variant": "anthropic", "providers": ["anthropic"], "refused": None},
                    "llm_fallback": "on", "breakers": {"anthropic": "open"}})
            return httpx.Response(200, json={"rows": [
                {"key": "gemini-2.5-pro", "calls": 4}, {"key": "gemini-2.5-flash-lite", "calls": 1}]})
        for key in fail:
            if path.endswith(key):
                return httpx.Response(502, json={"detail": "The tutor had trouble answering that."})
        if path == "/api/learn/start-session":
            return httpx.Response(200, json={"session_id": "s1", "initial_message": "hi"})
        if path == "/api/learn/chat/stream":
            ev = ({"event": "error", "data": {"type": "error", "message": "The tutor is unavailable. Please retry."}}
                  if sse_error else {"event": "done", "data": {"type": "done", "message": "Complete."}})
            body = (f"event: token\ndata: {json.dumps({'type': 'token'})}\n\n"
                    f"event: {ev['event']}\ndata: {json.dumps(ev['data'])}\n\n")
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        if path.startswith("/api/graph/"):
            return httpx.Response(200, json={"nodes": [{"id": "node-1"}]})
        return httpx.Response(200, json={"ok": True})

    return httpx.MockTransport(handler), seen


@pytest.fixture(autouse=True)
def _no_session_env(monkeypatch):
    monkeypatch.delenv("SAPLING_DRILL_SESSION", raising=False)


def _run(monkeypatch, transport, *args):
    monkeypatch.setattr(drill, "_transport", transport)
    return drill.main(["--settle", "0", *args])


def test_a_non_localhost_url_needs_i_know(monkeypatch, capsys):
    transport, seen = _backend()
    assert _run(monkeypatch, transport, "--url", "https://api.staging.example") == 2
    assert seen == []  # nothing was sent
    assert "--i-know" in capsys.readouterr().err


def test_a_remote_drill_takes_the_session_from_the_env_never_test_login(monkeypatch):
    transport, seen = _backend()
    with pytest.raises(SystemExit):
        _run(monkeypatch, transport, "--url", "https://api.staging.example", "--i-know")
    assert seen == []
    monkeypatch.setenv("SAPLING_DRILL_SESSION", "tok")
    assert _run(monkeypatch, transport, "--url", "https://api.staging.example", "--i-know") == 0
    assert "POST /api/auth/test-login" not in seen


def test_a_clean_fallback_drill_exits_zero_and_reports_the_served_models(monkeypatch, capsys):
    transport, seen = _backend()
    assert _run(monkeypatch, transport) == 0
    out = capsys.readouterr().out
    assert "forced outage: ['anthropic']" in out
    assert "0 user-facing error(s)" in out
    assert "gemini-2.5-pro" in out
    assert "POST /api/quiz/generate" in seen  # discovered the user's first concept node
    assert "POST /api/learn/chat/stream" in seen


def test_a_user_facing_error_fails_the_fallback_expectation(monkeypatch, capsys):
    transport, _ = _backend(fail={"/api/learn/chat"})
    assert _run(monkeypatch, transport) == 1
    assert "ERROR" in capsys.readouterr().out


def test_an_sse_error_event_counts_as_user_facing(monkeypatch, capsys):
    transport, _ = _backend(sse_error=True)
    assert _run(monkeypatch, transport) == 1
    assert "SSE error: The tutor is unavailable" in capsys.readouterr().out


def test_expect_errors_needs_every_request_to_fail(monkeypatch):
    every = {"/start-session", "/api/quiz/generate"}
    transport, _ = _backend(fail=every)
    assert _run(monkeypatch, transport, "--expect", "errors") == 0
    transport, _ = _backend(fail={"/api/quiz/generate"})
    assert _run(monkeypatch, transport, "--expect", "errors") == 1


def test_without_admin_it_still_runs_and_says_what_it_cannot_see(monkeypatch, capsys):
    transport, _ = _backend(admin=False)
    assert _run(monkeypatch, transport) == 0
    out = capsys.readouterr().out
    assert "drill state: unknown" in out and "Served models: unknown" in out
