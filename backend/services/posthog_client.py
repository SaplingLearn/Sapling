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

Privacy: ``distinct_id`` is always a real ``users.id`` (``user_<google id>``
— the app's ids are opaque TEXT, not UUIDs) or absent. No names, emails, or
free text are ever sent — the payloads are the #117 ones, which are
ids/counts/enums by contract. Before any user id is sent,
``services/analytics_consent.consent_for`` must say ALLOWED: nothing is sent
for a student who opted out (``user_settings.analytics_opt_out``), a
soft-deleted account, an unknown id, or a request carrying ``Sec-GPC: 1`` /
``DNT: 1``; and an unreadable answer is a "no".

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


def _disabled_reason_for(
    env: Mapping[str, str], *, under_pytest: bool, model_mode: str,
) -> str | None:
    """Pure form of the gate, so tests can exercise every branch without
    un-importing pytest. Returns why PostHog is off, or None when it may run.

    ``model_mode`` is the ALREADY-NORMALIZED seam mode
    (``agents._providers.model_mode()``) — never re-parsed here, so the
    PostHog gate and the LLM seam cannot disagree about which lane this is.

    Order matters only for the log line; any one reason is sufficient.
    """
    if (env.get("POSTHOG_DISABLED") or "").strip().lower() in _TRUTHY:
        return "POSTHOG_DISABLED is set"
    if under_pytest:
        return "running under pytest"
    if (env.get("APP_ENV") or "").strip().lower() == "test":
        return "APP_ENV=test"
    if model_mode != "real":
        return f"SAPLING_MODEL_MODE={model_mode} (deterministic lane)"
    if not (env.get("POSTHOG_PROJECT_TOKEN") or "").strip():
        return _NO_TOKEN
    return None


def disabled_reason() -> str | None:
    """Why PostHog is off in this process right now, or None if it is on."""
    # Lazy: this module is imported by events_service (imported nearly
    # everywhere), and _providers pulls in pydantic-ai.
    from agents._providers import model_mode

    return _disabled_reason_for(
        os.environ, under_pytest="pytest" in sys.modules, model_mode=model_mode(),
    )


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
    """Mirror one #117 event to PostHog. Never raises.

    Called only from ``events_service.log_event``, after its kill-switch
    check. The ``content_fp`` fingerprint is deliberately NOT forwarded: it
    is a hash of student text (a chat message, a session topic), useful for
    joins inside our own DB and nothing PostHog needs.

    Consent first (``_sendable_distinct_id``): opted-out / deleted / unknown
    users and DNT/GPC requests are skipped. That check is a per-process
    cached read, so at most one DB round trip per user per TTL — never one
    per event; the capture itself is an enqueue for posthog's consumer.

    ``user_id`` None (sweeper, background work with no actor) becomes a
    personless event — posthog-python assigns a random id and skips the
    person profile.

    The event's #117 category is sent as ``event_category`` (the payload's
    own ``category`` key, where one exists, is left alone); ``error.4xx`` is
    not mirrored; any ``path`` / ``route`` becomes the route template
    (``_mirrored_properties``).

    This check runs at ENQUEUE time for every event, so a user deleted or
    opted out a moment ago is refused from the next event on (in this
    process at once; in others once their cached answer expires).
    """
    client = _client
    if client is None:
        return
    try:
        distinct_id = _sendable_distinct_id(event_type, user_id)
        if distinct_id is _SKIP:
            return
        properties = _mirrored_properties(payload, category=category, request_id=request_id)
        client.capture(event_type, distinct_id=distinct_id, properties=properties)
    except Exception:
        logger.debug("PostHog mirror failed for %s; dropped", event_type, exc_info=True)


#: Payload keys that carry a request path. Whatever the emitter put there (a
#: raw path like auth.permission_denied's `/api/profile/<another user's id>`,
#: or error.5xx's already-templated route), PostHog gets the MATCHED ROUTE
#: TEMPLATE of the current request (`/api/profile/{user_id}`) or
#: "<unmatched>" — bounded cardinality, and no ids in a path segment.
_PATH_KEYS: frozenset[str] = frozenset({"path", "route"})

#: Payload keys naming a user other than the event's own `distinct_id`. None
#: of today's #117 payloads carry one (audited: the admin role/achievement
#: `user_id`s go to admin_audit_log, not log_event); dropped here so a future
#: payload that adds one cannot leak a second person into PostHog.
_USER_ID_KEYS: frozenset[str] = frozenset({
    "user_id", "target_user_id", "actor_id", "friend_id", "peer_user_id", "owner_id",
})


def _mirrored_properties(
    payload: dict | None, *, category: str, request_id: str | None,
) -> dict[str, Any]:
    from services.request_context import current_route_template

    properties: dict[str, Any] = {
        k: v for k, v in (payload or {}).items() if k not in _USER_ID_KEYS
    }
    if _PATH_KEYS & properties.keys():
        template = current_route_template() or "<unmatched>"
        for key in _PATH_KEYS & properties.keys():
            properties[key] = template
    # The #117 category rides under its own key: several payloads carry a
    # `category` of their own (document.processed's document category,
    # rag.relevance_scored's chunk category) that must survive intact.
    properties["event_category"] = category
    if request_id:
        properties["request_id"] = request_id
    return properties


#: Events that stay in our own table only. error.4xx is every 401 from an
#: expired cookie, every 404 probe and every 422: high volume, no product
#: signal, and a raw path per row.
_NOT_MIRRORED: frozenset[str] = frozenset({"error.4xx"})

_SKIP = object()


def _sendable_distinct_id(event_type: str, user_id: str | None) -> Any:
    """The distinct_id to mirror under, None for a personless event, or
    ``_SKIP`` when nothing may be sent.

    Skips: events in ``_NOT_MIRRORED``; any request that sent DNT / GPC; a
    user who opted out, was deleted, is unknown, or whose consent could not be
    read (fail closed — ``analytics_consent``). When the event names no user
    (None, or a placeholder like "anonymous"/"backfill"), the request's
    session user still decides: an opted-out student's request mirrors
    nothing, even events that do not carry their id. A genuinely actor-less
    event (the sweeper) is sent personless.
    """
    from services.analytics_consent import Consent, consent_for
    from services.request_context import current_session_user, request_has_privacy_signal

    if event_type in _NOT_MIRRORED or request_has_privacy_signal():
        return _SKIP
    consent = consent_for(user_id)
    if consent is Consent.ALLOWED:
        return str(user_id).strip()
    if consent is Consent.DENIED:
        return _SKIP
    # NO_USER: the event names nobody; the request's own user may still object.
    if consent_for(current_session_user()) is Consent.DENIED:
        return _SKIP
    return None


def flush(timeout_seconds: float = 10.0) -> None:
    """Deliver everything queued so far (bounded). Never raises.

    Used before a person delete, so an event captured before the account was
    deleted cannot arrive AFTER the delete and re-create the person.
    """
    client = _client
    if client is None:
        return
    try:
        client.flush(timeout_seconds=timeout_seconds)
    except TypeError:  # pragma: no cover - an SDK without the timeout kwarg
        client.flush()
    except Exception:
        logger.warning("PostHog flush before person delete failed", exc_info=True)


def capture_exception(
    exc: BaseException,
    *,
    user_id: str | None,
    request_id: str | None,
    privacy_signal: bool = False,
) -> None:
    """Send an unhandled exception to PostHog error tracking. Never raises.

    ``privacy_signal``: the request sent DNT/GPC. Passed explicitly because
    the 500 handler runs outside RequestIDMiddleware, after the per-request
    contextvar has been reset; the contextvar is still consulted too.
    """
    client = _client
    if client is None:
        return
    if privacy_signal:
        return
    try:
        # Same consent rule as the mirror: an opted-out, deleted or DNT/GPC
        # request sends no exception either (a person would be created).
        distinct_id = _sendable_distinct_id("$exception", user_id)
        if distinct_id is _SKIP:
            return
        properties = {"request_id": request_id} if request_id else {}
        client.capture_exception(exc, distinct_id=distinct_id, properties=properties)
    except Exception:
        logger.debug("PostHog capture_exception failed", exc_info=True)


_PERSON_DELETE_TIMEOUT_S = 10.0

#: The second delete waits out every other process's cached "allowed"
#: (analytics_consent.TTL_S) plus a margin for their SDK queues to deliver
#: (posthog-python flushes every ~0.5 s; the margin also covers a slow batch).
_SECOND_DELETE_MARGIN_S = 30.0


def _second_delete_delay_s() -> float:
    from services.analytics_consent import TTL_S

    return TTL_S + _SECOND_DELETE_MARGIN_S


def delete_person(user_id: str) -> None:
    """Best-effort: delete this user's PostHog person and their events —
    now, and once more after every process has stopped sending for them.

    Runs as a post-response BackgroundTask from account deletion, so it never
    adds latency and can never fail the deletion — every path returns None and
    logs. Needs the private REST API (a personal API key with ``person:write``
    plus the project id); without them it WARNs and skips, which leaves a
    manual deletion to do in the PostHog UI.

    Why twice: after the soft delete, THIS process refuses the user at once
    (the route clears its cached consent), but another replica may still hold
    a cached "allowed" for up to ``analytics_consent.TTL_S``, and an agent run
    in flight re-checks consent only when its spans end. Anything those send
    after the first ``bulk_delete`` re-creates the person, so a second pass
    runs after TTL + margin (a daemon timer: lost if this process exits
    first, which is logged at scheduling time and in the ADR).

    Gated like everything else: under pytest / APP_ENV=test / function mode /
    the kill switch it makes no request. A deletion skipped that way is logged
    at WARNING with the reason, because in production it is a privacy to-do.
    """
    if _delete_pass(user_id, label="first"):
        _schedule_second_pass(user_id)


def _schedule_second_pass(user_id: str) -> None:
    try:
        delay = _second_delete_delay_s()
        timer = threading.Timer(delay, _delete_pass, args=(user_id,), kwargs={"label": "second"})
        timer.daemon = True
        timer.start()
        logger.info(
            "PostHog second person delete for %s scheduled in %.0fs (best-effort; "
            "lost if this process stops first)", user_id, delay,
        )
    except Exception as exc:  # pragma: no cover - thread start failure
        logger.warning(
            "PostHog second person delete for %s not scheduled: %s",
            user_id, type(exc).__name__,
        )


def _delete_pass(user_id: str, *, label: str) -> bool:
    """One flush + ``bulk_delete``. Returns whether the request was ISSUED
    (False = skipped as unconfigured/gated, so no second pass is scheduled).
    Never raises."""
    try:
        reason = disabled_reason()
        # An unset project token only means nothing is being captured NOW;
        # a person captured before it was unset still exists, so it does not
        # block the delete. Every other reason (tests, E2E, kill switch) does.
        if reason is not None and reason != _NO_TOKEN:
            logger.warning("PostHog person delete skipped for %s: %s", user_id, reason)
            return False
        key = config.posthog_personal_api_key()
        project_id = config.posthog_project_id()
        if not key or not project_id:
            logger.warning(
                "PostHog person delete skipped for %s: POSTHOG_PERSONAL_API_KEY "
                "and POSTHOG_PROJECT_ID must both be set — delete the person "
                "manually in PostHog",
                user_id,
            )
            return False
        api_host = config.posthog_api_host()
        if not api_host:
            # Never guess where the personal key goes (config.posthog_api_host).
            logger.warning(
                "PostHog person delete skipped for %s: POSTHOG_HOST is not a "
                "PostHog-cloud ingestion host, so POSTHOG_API_HOST must be set "
                "explicitly — delete the person manually in PostHog",
                user_id,
            )
            return False

        # Anything THIS process captured before now is still in the SDK
        # queues; delivered after the delete, it would re-create the person.
        # Drain both (events + AI spans), bounded, first.
        flush(timeout_seconds=_PERSON_DELETE_TIMEOUT_S)
        from services.ai_observability import flush_ai_spans

        flush_ai_spans(timeout_millis=int(_PERSON_DELETE_TIMEOUT_S * 1000))

        # Not a Supabase client: the table() rule is about Supabase. This is a
        # third-party REST API, like the OAuth exchange in routes/auth.py.
        import httpx

        url = f"{api_host}/api/projects/{project_id}/persons/bulk_delete/"
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {key}"},
            json={"distinct_ids": [str(user_id)], "delete_events": True},
            timeout=_PERSON_DELETE_TIMEOUT_S,
        )
        if resp.status_code < 300:
            logger.info("PostHog person delete (%s pass) queued for %s", label, user_id)
        elif resp.status_code == 400:
            # With delete_events=True PostHog 400s a distinct id that matches
            # no person — a user who never produced an event (or, on the
            # second pass, the normal case: nothing re-created it). Say so: a
            # 400 for any other reason reads the same.
            logger.warning(
                "PostHog person delete (%s pass) for %s returned 400 (usually: "
                "no person for this id)", label, user_id,
            )
        else:
            # Status only — never the body.
            logger.warning(
                "PostHog person delete (%s pass) for %s failed: HTTP %s",
                label, user_id, resp.status_code,
            )
        return True
    except Exception as exc:
        logger.warning(
            "PostHog person delete (%s pass) for %s failed: %s",
            label, user_id, type(exc).__name__,
        )
        return True
