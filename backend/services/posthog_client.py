"""The PostHog seam: one process-wide client, one gate, three uses (ADR 0028).

PostHog runs ALONGSIDE the in-house ``events`` / ``llm_usage`` tables
(``services/events_service.py``), not instead of them — admin analytics and
the Canopy metrics stay on ours. Everything PostHog-shaped in the backend goes
through this module:

* **Events** — ``mirror_event`` is called from exactly one place,
  ``events_service.log_event``, so PostHog sees the #117 taxonomy under the
  same names and payloads, honours ``EVENTS_LOGGING_ENABLED``, and there is no
  second taxonomy to drift. Routes never call PostHog directly.
* **Exceptions** — ``capture_exception`` from main.py's 500 handler. No local
  variables, and ``_scrub_event`` redacts exception messages before anything
  is queued (a pydantic ``ValidationError`` or a PostgREST error echoes its
  input, and inputs here include decrypted notes/messages/documents).
* **Account deletion** — ``delete_person`` (best-effort REST call).

AI tracing is the fourth use but is wired at ``logfire.configure`` time (see
``services/ai_observability.py``); it shares ``disabled_reason`` so the two
can never disagree about whether PostHog is on.

Privacy: ``distinct_id`` is always the user's UUID (or absent). No names,
emails, or free text are ever sent — the payloads are the #117 ones, which
are ids/counts/enums by contract.

Gating (``disabled_reason``): unset token, ``POSTHOG_DISABLED``, pytest,
``APP_ENV=test``, or any non-``real`` ``SAPLING_MODEL_MODE`` (the E2E and
explore lanes) all mean NO client is constructed: no consumer threads, no
network. Local dev with a token set does send.

Fire-and-forget: the posthog client is batched — ``capture`` does a
``queue.put(block=False)`` and a background consumer thread uploads — so a
mirror never blocks the request thread, and every entry point here swallows
its own failures.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from typing import Any, Mapping

import config

logger = logging.getLogger("sapling.posthog")

_client: Any = None
_client_lock = threading.Lock()

_TRUTHY = {"1", "true", "yes", "on"}

#: The one reason that does NOT block a person delete (see delete_person).
_NO_TOKEN = "POSTHOG_PROJECT_TOKEN is unset"


# ── Gate ────────────────────────────────────────────────────────────────────


def _disabled_reason_for(env: Mapping[str, str], *, under_pytest: bool) -> str | None:
    """Pure form of the gate, so tests can exercise every branch without
    un-importing pytest. Returns why PostHog is off, or None when it may run.

    Order matters only for the log line; any one reason is sufficient.
    """
    if (env.get("POSTHOG_DISABLED") or "").strip().lower() in _TRUTHY:
        return "POSTHOG_DISABLED is set"
    if under_pytest:
        return "running under pytest"
    if (env.get("APP_ENV") or "").strip().lower() == "test":
        return "APP_ENV=test"
    # The same normalization as agents/_providers._model_mode. Not imported
    # from there: this module is imported by events_service, which is
    # imported nearly everywhere, and _providers pulls in pydantic-ai.
    mode = (env.get("SAPLING_MODEL_MODE") or "real").strip().lower()
    if mode != "real":
        return f"SAPLING_MODEL_MODE={mode} (deterministic lane)"
    if not (env.get("POSTHOG_PROJECT_TOKEN") or "").strip():
        return _NO_TOKEN
    return None


def disabled_reason() -> str | None:
    """Why PostHog is off in this process right now, or None if it is on."""
    return _disabled_reason_for(os.environ, under_pytest="pytest" in sys.modules)


def is_enabled() -> bool:
    return disabled_reason() is None


# ── Event scrubbing (before_send) ───────────────────────────────────────────

_REDACTED = "[redacted]"


def _scrub_event(msg: dict) -> dict | None:
    """Last line of defence before an event is queued.

    ``$exception``: keep the type, module, mechanism and code-location frames
    (what issue grouping keys on), but drop the exception message and any
    frame locals. ``capture_exception_code_variables`` is already False; the
    ``vars`` strip is belt-and-braces so a future SDK default flip, or a
    context that enables it, still cannot ship locals.

    A scrub that fails drops the event (returns None) rather than letting an
    unscrubbed one through.
    """
    try:
        props = msg.get("properties") or {}
        for exc in props.get("$exception_list") or []:
            if not isinstance(exc, dict):
                continue
            if exc.get("value"):
                exc["value"] = _REDACTED
            frames = (exc.get("stacktrace") or {}).get("frames") or []
            for frame in frames:
                if isinstance(frame, dict):
                    frame.pop("vars", None)
                    frame.pop("code_variables", None)
        props.pop("$exception_message", None)
        return msg
    except Exception:
        logger.debug("posthog before_send scrub failed; dropping event", exc_info=True)
        return None


# ── Lifecycle ───────────────────────────────────────────────────────────────


def initialize_posthog() -> Any:
    """Construct the client once for this process, if the gate allows.

    Called from main.py's lifespan. Idempotent. Returns the client or None.
    """
    global _client
    reason = disabled_reason()
    if reason is not None:
        logger.info("PostHog disabled: %s", reason)
        return None
    with _client_lock:
        if _client is not None:
            return _client
        try:
            from posthog import Posthog

            _client = Posthog(
                project_api_key=config.posthog_project_token(),
                host=config.posthog_host(),
                # Explicit, not defaults: these are privacy properties.
                capture_exception_code_variables=False,
                # Exceptions are captured at ONE site (main.py's 500 handler)
                # with the user attached; autocapture would add a second,
                # anonymous path through the sys/threading excepthooks.
                enable_exception_autocapture=False,
                disable_geoip=True,
                privacy_mode=True,
                before_send=_scrub_event,
            )
            logger.info("PostHog enabled (host=%s)", config.posthog_host())
        except Exception:
            logger.warning("PostHog client init failed; analytics off", exc_info=True)
            _client = None
    return _client


def get_posthog_client() -> Any:
    """The lifespan-managed client, or None when PostHog is off."""
    return _client


def shutdown_posthog() -> None:
    """Flush and stop the consumer threads (lifespan shutdown). Never raises."""
    global _client
    with _client_lock:
        client, _client = _client, None
    if client is None:
        return
    try:
        client.shutdown()
    except Exception:
        logger.warning("PostHog shutdown failed", exc_info=True)


def set_client_for_tests(client: Any) -> None:
    """Install a fake client (or None). Test-only."""
    global _client
    _client = client


# ── Uses ────────────────────────────────────────────────────────────────────


def mirror_event(
    event_type: str,
    *,
    category: str,
    user_id: str | None,
    request_id: str | None,
    payload: dict | None,
) -> None:
    """Mirror one #117 event to PostHog. Never raises, never blocks.

    Called only from ``events_service.log_event``, after its kill-switch
    check. The ``content_fp`` fingerprint is deliberately NOT forwarded: it
    is a hash of student text (a chat message, a session topic), useful for
    joins inside our own DB and nothing PostHog needs.

    ``user_id`` None (sweeper, background work with no actor) becomes a
    personless event — posthog-python assigns a random id and skips the
    person profile.
    """
    client = _client
    if client is None:
        return
    try:
        properties: dict[str, Any] = {**(payload or {}), "category": category}
        if request_id:
            properties["request_id"] = request_id
        client.capture(
            event_type,
            distinct_id=str(user_id) if user_id else None,
            properties=properties,
        )
    except Exception:
        logger.debug("PostHog mirror failed for %s; dropped", event_type, exc_info=True)


def capture_exception(
    exc: BaseException, *, user_id: str | None, request_id: str | None,
) -> None:
    """Send an unhandled exception to PostHog error tracking. Never raises."""
    client = _client
    if client is None:
        return
    try:
        properties = {"request_id": request_id} if request_id else {}
        client.capture_exception(
            exc,
            distinct_id=str(user_id) if user_id else None,
            properties=properties,
        )
    except Exception:
        logger.debug("PostHog capture_exception failed", exc_info=True)


_PERSON_DELETE_TIMEOUT_S = 10.0


def delete_person(user_id: str) -> None:
    """Best-effort: delete this user's PostHog person and their events.

    Runs as a post-response BackgroundTask from account deletion, so it never
    adds latency and can never fail the deletion — every path returns None and
    logs. Needs the private REST API (a personal API key with ``person:write``
    plus the project id); without them it WARNs and skips, which leaves a
    manual deletion to do in the PostHog UI.

    Gated like everything else: under pytest / APP_ENV=test / function mode /
    the kill switch it makes no request. A deletion skipped that way is logged
    at WARNING with the reason, because in production it is a privacy to-do.
    """
    try:
        reason = disabled_reason()
        # An unset project token only means nothing is being captured NOW;
        # a person captured before it was unset still exists, so it does not
        # block the delete. Every other reason (tests, E2E, kill switch) does.
        if reason is not None and reason != _NO_TOKEN:
            logger.warning("PostHog person delete skipped for %s: %s", user_id, reason)
            return
        key = config.posthog_personal_api_key()
        project_id = config.posthog_project_id()
        if not key or not project_id:
            logger.warning(
                "PostHog person delete skipped for %s: POSTHOG_PERSONAL_API_KEY "
                "and POSTHOG_PROJECT_ID must both be set — delete the person "
                "manually in PostHog",
                user_id,
            )
            return

        # Not a Supabase client: the table() rule is about Supabase. This is a
        # third-party REST API, like the OAuth exchange in routes/auth.py.
        import httpx

        url = f"{config.posthog_api_host()}/api/projects/{project_id}/persons/bulk_delete/"
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {key}"},
            json={"distinct_ids": [str(user_id)], "delete_events": True},
            timeout=_PERSON_DELETE_TIMEOUT_S,
        )
        if resp.status_code < 300:
            logger.info("PostHog person delete queued for %s", user_id)
        elif resp.status_code == 400:
            # With delete_events=True PostHog 400s a distinct id that matches
            # no person — a user who never produced an event. Nothing to do,
            # but say so: a 400 for any other reason reads the same.
            logger.warning(
                "PostHog person delete for %s returned 400 (usually: no person "
                "for this id)", user_id,
            )
        else:
            # Status only — never the body.
            logger.warning(
                "PostHog person delete for %s failed: HTTP %s", user_id, resp.status_code,
            )
    except Exception as exc:
        logger.warning(
            "PostHog person delete for %s failed: %s", user_id, type(exc).__name__,
        )
