"""Sapling API load test (#117, docs/design/async-db-client.md §1 "Measurement").

A fixed mix against ONE target you name explicitly:

* ``GET /api/health``                 -- unauthenticated liveness
* ``GET /api/flags``                  -- an authenticated read (flag snapshot +
                                         session guard)
* ``GET /api/quiz/attempts``          -- the quiz history list (the first read
                                         on the async DB seam)
* ``POST /api/learn/chat/stream``     -- a tutor turn over SSE; reported twice:
                                         ``chat_stream TTFT`` (time to the first
                                         token event) and ``chat_stream full``

Point it at the local deterministic stack (``make e2e-up`` with
``SAPLING_MODEL_MODE=function``: no LLM cost, fixed replies) and never at a
real environment without the owner's say-so: the chat task writes messages
and, in real model mode, spends money.

Configuration (environment):

``LOADTEST_USER_IDS``     comma list of seeded user ids (default
                          ``rich-user-active``); each simulated user takes one
``LOADTEST_TEST_LOGIN``   ``1`` (default) mints sessions via
                          ``POST /api/auth/test-login`` -- exists only when the
                          target runs ``APP_ENV=local|test``
``LOADTEST_SESSION_TOKEN`` a ``sapling_session`` token to use instead. One
                          token is ONE student: every simulated user then acts
                          as the token's own ``user_id`` (single-user mode;
                          ``LOADTEST_USER_IDS`` and ``LOADTEST_TEST_LOGIN`` are
                          ignored), so no request names a user the session is
                          not (each would 403 at ``require_self``)
``LOADTEST_TUTOR_SESSION`` an existing tutor session id for the chat task;
                          unset, each user starts one (``/api/learn/start-session``)
``LOADTEST_CHAT``         ``0`` drops the chat task (reads only)

Run (see loadtest/README.md):

    locust -f loadtest/locustfile.py --host http://localhost:5000 \\
        --headless -u 20 -r 5 -t 2m --csv loadtest/out/run
"""
from __future__ import annotations

import base64
import itertools
import json
import os
import time
import uuid

from locust import HttpUser, between, events, task

SESSION_COOKIE = "sapling_session"

_TOKEN = (os.getenv("LOADTEST_SESSION_TOKEN") or "").strip()


def _token_user_id(token: str) -> str:
    """The ``user_id`` a ``sapling_session`` token names (its payload is
    base64url JSON before the ``.``; services/session_tokens.py). Read only:
    the server still verifies the signature on every request."""
    payload_b64 = token.split(".", 1)[0]
    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4)))
    except ValueError as exc:
        raise SystemExit(f"loadtest: LOADTEST_SESSION_TOKEN is not a sapling_session token ({exc})")
    user_id = payload.get("user_id") if isinstance(payload, dict) else None
    if not isinstance(user_id, str) or not user_id:
        raise SystemExit("loadtest: LOADTEST_SESSION_TOKEN names no user_id")
    return user_id


if _TOKEN:
    # Single-user mode: one token is one student, so every simulated user is
    # that student (asking for anyone else's data would only measure 403s).
    _USER_IDS = [_token_user_id(_TOKEN)]
else:
    _USER_IDS = [u.strip() for u in
                 os.getenv("LOADTEST_USER_IDS", "rich-user-active").split(",") if u.strip()]
_next_user = itertools.cycle(_USER_IDS or ["rich-user-active"])


def _flag(name: str, default: str) -> bool:
    return (os.getenv(name, default) or "").strip().lower() in {"1", "true", "yes", "on"}


@events.init.add_listener
def _require_host(environment, **_kw):
    """There is deliberately no default target: refuse to start without one."""
    if not (environment.host or "").strip():
        raise SystemExit("loadtest: no target. Pass --host (e.g. http://localhost:5000); "
                         "there is deliberately no default.")
    if _TOKEN:
        print(f"loadtest: LOADTEST_SESSION_TOKEN set -- single-user mode, every simulated "
              f"user acts as {_USER_IDS[0]} (LOADTEST_USER_IDS ignored)")


class SaplingUser(HttpUser):
    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
        self.user_id = next(_next_user)
        self.tutor_session = None
        token = _TOKEN
        if not token and _flag("LOADTEST_TEST_LOGIN", "1"):
            with self.client.post("/api/auth/test-login", json={"user_id": self.user_id},
                                  name="auth test-login", catch_response=True) as r:
                if r.status_code != 200:
                    r.failure(f"test-login {r.status_code}: is APP_ENV local/test?")
                    return
                token = r.json().get("token", "")
        if token:
            self.client.cookies.set(SESSION_COOKIE, token)
        self.tutor_session = (os.getenv("LOADTEST_TUTOR_SESSION") or "").strip() or None
        if self.tutor_session is None and _flag("LOADTEST_CHAT", "1"):
            with self.client.post("/api/learn/start-session", json={
                "user_id": self.user_id, "topic": "Load test", "mode": "socratic",
            }, name="learn start-session", catch_response=True) as r:
                if r.status_code == 200:
                    self.tutor_session = r.json().get("session_id")
                else:
                    r.failure(f"start-session {r.status_code}")

    @task(2)
    def health(self) -> None:
        self.client.get("/api/health", name="GET /api/health")

    @task(4)
    def flags(self) -> None:
        self.client.get("/api/flags", name="GET /api/flags")

    @task(4)
    def quiz_list(self) -> None:
        self.client.get("/api/quiz/attempts", params={"user_id": self.user_id, "limit": 20},
                        name="GET /api/quiz/attempts")

    @task(1)
    def chat_stream(self) -> None:
        if not self.tutor_session or not _flag("LOADTEST_CHAT", "1"):
            return
        body = {
            "session_id": self.tutor_session, "user_id": self.user_id,
            "message": "Can you give me one practice question?", "mode": "socratic",
            "turn_id": uuid.uuid4().hex,
        }
        start = time.perf_counter()
        ttft_ms = None
        error: Exception | None = None
        length = 0
        try:
            with self.client.post("/api/learn/chat/stream", json=body, stream=True,
                                  name="POST /api/learn/chat/stream (connect)",
                                  headers={"Accept": "text/event-stream"},
                                  catch_response=True) as r:
                if r.status_code != 200:
                    r.failure(f"chat/stream {r.status_code}")
                    return
                # chunk_size=None: hand over bytes as they arrive (the default
                # 512-byte chunks would hold the first token back).
                for line in r.iter_lines(chunk_size=None, decode_unicode=True):
                    length += len(line or "")
                    if ttft_ms is None and _is_token(line):
                        ttft_ms = (time.perf_counter() - start) * 1000
                r.success()
        except Exception as exc:  # report, never crash the user
            error = exc
        total_ms = (time.perf_counter() - start) * 1000
        _report("chat_stream TTFT", ttft_ms if ttft_ms is not None else total_ms,
                length, error or (None if ttft_ms is not None else RuntimeError("no token event")))
        _report("chat_stream full", total_ms, length, error)


def _is_token(line: str | None) -> bool:
    """A token event on the SSE wire: ``event: token`` or a ``data:`` JSON
    payload whose ``type`` is ``token``."""
    if not line:
        return False
    if line.startswith("event:"):
        return line.split(":", 1)[1].strip() == "token"
    if line.startswith("data:"):
        try:
            payload = json.loads(line.split(":", 1)[1].strip())
        except ValueError:
            return False
        return isinstance(payload, dict) and payload.get("type") == "token"
    return False


def _report(name: str, ms: float, length: int, exc: Exception | None) -> None:
    events.request.fire(request_type="SSE", name=name, response_time=ms,
                        response_length=length, exception=exc, context={})
