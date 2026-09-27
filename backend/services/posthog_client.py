"""The PostHog seam: one gate, one queue, one worker (ADR 0028).

PostHog runs ALONGSIDE the in-house ``events`` / ``llm_usage`` tables
(``services/events_service.py``), not instead of them — admin analytics and
the Canopy metrics stay on ours. Everything PostHog-shaped in the backend goes
through this module, and every send goes through ONE path:

    request path                         worker thread (one, daemon)
    ────────────                         ───────────────────────────
    mirror_event / capture_ai_generation
    / capture_exception
      → drop if DNT/GPC or error.4xx
      → build properties (route template,
        no foreign ids, event_category)
      → resolve the ACTOR (the event's
        user, else the request's session
        user from scope["state"])
      → enqueue ─────────────────────────→ consent_for(actor) (may block: it
        (bounded; drop-oldest)               is this thread's job) → capture
                                             to posthog-python, or drop

The request path does no consent work and no I/O, so no event-loop thread
ever waits on the database, and a cold consent cache DELAYS an event on the
worker instead of dropping it.

Uses:

* **Events** — ``mirror_event``, called only from ``events_service.log_event``:
  same #117 names and payloads, same ``EVENTS_LOGGING_ENABLED`` kill switch,
  no second taxonomy. Routes never call PostHog directly.
* **LLM analytics** — ``capture_ai_generation``, called only from
  ``agents/usage.py::record_agent_usage`` (the chokepoint every agent run
  already reports through): a ``$ai_generation`` with model, provider,
  tokens, cost and trace id — never ``$ai_input`` / ``$ai_output``.
* **Exceptions** — ``capture_exception`` from main.py's 500 handler. No
  local variables, and ``_scrub_event`` redacts exception messages before
  the SDK queues anything.
* **Account deletion** — ``delete_person`` (best-effort REST call, twice).

Privacy: ``distinct_id`` is always a real ``users.id`` (``user_<google id>``
— opaque TEXT, not UUIDs) that ``analytics_consent.consent_for`` said ALLOWED
for, or absent. Nothing is sent for a student who opted out
(``user_settings.analytics_opt_out``), a soft-deleted account, an unknown id,
an unreadable answer, or a request carrying ``Sec-GPC: 1`` / ``DNT: 1``.

Gating (``disabled_reason``): unset token, ``POSTHOG_DISABLED``, pytest,
``APP_ENV=test``, or any non-``real`` seam mode (the E2E and explore lanes)
all mean NO client is constructed and nothing is enqueued: no threads, no
network. Local dev with a token set does send.
"""

from __future__ import annotations

import logging
import os
import queue
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Mapping, NamedTuple

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
    """Last line of defence before the SDK queues an event.

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
    """Drain our queue, then flush and stop posthog's consumers (lifespan
    shutdown). Bounded; never raises."""
    global _client
    flush_queue(timeout_seconds=5.0)
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


# ── The queue and its worker ────────────────────────────────────────────────


class _Item(NamedTuple):
    kind: str                 # "event" | "exception"
    name: str                 # event name ("$exception" for exceptions)
    properties: dict
    actor: str | None         # the user to check consent for; None = no actor
    captured_at: float        # epoch seconds, so a delayed send keeps its time
    exc: BaseException | None = None


_QUEUE_MAX = int(os.getenv("POSTHOG_QUEUE_MAX", "10000"))
_queue: "queue.Queue[_Item]" = queue.Queue(maxsize=_QUEUE_MAX)
_queue_lock = threading.Lock()
_dropped = 0
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()


def _enqueue(item: _Item) -> None:
    """Non-blocking put; when full, drop the OLDEST item (the newest events
    are the ones anyone is looking at). Warns once, then every 1000th."""
    global _dropped
    _ensure_worker()
    with _queue_lock:
        while True:
            try:
                _queue.put_nowait(item)
                return
            except queue.Full:
                try:
                    _queue.get_nowait()
                    _queue.task_done()
                except queue.Empty:  # pragma: no cover - drained meanwhile
                    continue
                _dropped += 1
                if _dropped == 1 or _dropped % 1000 == 0:
                    logger.warning(
                        "PostHog queue full (max=%d); dropped %d oldest item(s) so far",
                        _queue.maxsize, _dropped,
                    )


def _ensure_worker() -> None:
    global _worker
    if _worker is not None and _worker.is_alive():
        return
    with _worker_lock:
        if _worker is not None and _worker.is_alive():
            return
        _worker = threading.Thread(target=_work, name="posthog-send", daemon=True)
        _worker.start()


def _work() -> None:
    while True:
        item = _queue.get()
        try:
            _deliver(item)
        except Exception:  # pragma: no cover - _deliver guards itself
            logger.debug("PostHog worker slipped; item dropped", exc_info=True)
        finally:
            _queue.task_done()


_SKIP = object()


def _distinct_id_for(actor: str | None) -> Any:
    """The distinct_id to send under, None for personless, or ``_SKIP``.
    Runs on the worker; may block on the consent read. Fails closed."""
    if actor is None:
        return None
    from services.analytics_consent import Consent, consent_for

    return str(actor).strip() if consent_for(actor) is Consent.ALLOWED else _SKIP


def _deliver(item: _Item) -> None:
    client = _client
    if client is None:
        return
    try:
        distinct_id = _distinct_id_for(item.actor)
        if distinct_id is _SKIP:
            return
        if item.kind == "exception":
            client.capture_exception(
                item.exc, distinct_id=distinct_id, properties=item.properties,
            )
        else:
            client.capture(
                item.name,
                distinct_id=distinct_id,
                properties=item.properties,
                timestamp=datetime.fromtimestamp(item.captured_at, tz=timezone.utc),
            )
    except Exception:
        logger.debug("PostHog send failed for %s; dropped", item.name, exc_info=True)


def flush_queue(timeout_seconds: float = 10.0) -> bool:
    """Block until every item enqueued so far has been delivered or dropped
    by the worker, or the timeout passes. Returns whether it drained."""
    deadline = time.monotonic() + timeout_seconds
    with _queue.all_tasks_done:
        while _queue.unfinished_tasks:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            _queue.all_tasks_done.wait(remaining)
    return True


def queue_dropped_count() -> int:
    return _dropped


# ── Actor + properties (request path: no I/O) ───────────────────────────────


def _actor(user_id: str | None) -> str | None:
    """The user this item is FOR: the event's own id if it is a real one,
    else the request's authenticated user (``request.state.user_id`` via the
    ASGI scope — visible in handlers, threadpool Depends and BackgroundTasks),
    else nobody. Placeholders (``anonymous``/``backfill``) are nobody."""
    from services.analytics_consent import is_placeholder
    from services.request_context import current_session_user

    if not is_placeholder(user_id):
        return str(user_id).strip()
    session_user = current_session_user()
    return None if is_placeholder(session_user) else str(session_user).strip()


def _request_opted_out() -> bool:
    from services.request_context import request_has_privacy_signal

    return request_has_privacy_signal()


#: Events that stay in our own table only. error.4xx is every 401 from an
#: expired cookie, every 404 probe and every 422: high volume, no product
#: signal, and a raw path per row.
_NOT_MIRRORED: frozenset[str] = frozenset({"error.4xx"})

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


# ── Uses ────────────────────────────────────────────────────────────────────


def mirror_event(
    event_type: str,
    *,
    category: str,
    user_id: str | None,
    request_id: str | None,
    payload: dict | None,
) -> None:
    """Queue one #117 event for PostHog. Never raises, never blocks, no I/O.

    Called only from ``events_service.log_event``, after its kill-switch
    check. ``content_fp`` is never forwarded (a hash of student text).
    ``error.4xx`` is not mirrored; ``path``/``route`` become the route
    template; the #117 category is sent as ``event_category``. Consent is
    decided on the worker, at send time.
    """
    if _client is None or event_type in _NOT_MIRRORED:
        return
    try:
        if _request_opted_out():
            return
        _enqueue(_Item(
            kind="event",
            name=event_type,
            properties=_mirrored_properties(payload, category=category, request_id=request_id),
            actor=_actor(user_id),
            captured_at=time.time(),
        ))
    except Exception:
        logger.debug("PostHog mirror failed for %s; dropped", event_type, exc_info=True)


def capture_ai_generation(
    *,
    user_id: str | None,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float | None,
    request_id: str | None,
    feature: str,
    task: str | None,
    latency_s: float | None = None,
) -> None:
    """Queue a privacy-mode ``$ai_generation`` for PostHog LLM analytics.

    Called only from ``agents/usage.py::record_agent_usage``. Carries ONLY
    model, provider, token counts, cost, latency (when known), the request id
    as trace id, and the feature/task name — never ``$ai_input`` /
    ``$ai_output`` or any other content. Same queue and consent path as
    events. Never raises.
    """
    if _client is None:
        return
    try:
        if _request_opted_out():
            return
        properties: dict[str, Any] = {
            "$ai_model": model,
            "$ai_provider": _provider_of(model),
            "$ai_input_tokens": int(input_tokens),
            "$ai_output_tokens": int(output_tokens),
            "$ai_span_name": task or feature,
            "feature": feature,
        }
        if task:
            properties["task"] = task
        if cost_usd is not None:
            properties["$ai_total_cost_usd"] = float(cost_usd)
        if latency_s is not None:
            properties["$ai_latency"] = float(latency_s)
        if request_id:
            properties["$ai_trace_id"] = request_id
        _enqueue(_Item(
            kind="event",
            name="$ai_generation",
            properties=properties,
            actor=_actor(user_id),
            captured_at=time.time(),
        ))
    except Exception:
        logger.debug("PostHog $ai_generation failed; dropped", exc_info=True)


def _provider_of(model: str) -> str:
    """``provider:model`` → provider; a bare Gemini id → gemini."""
    name = (model or "").strip().lower()
    if ":" in name:
        return name.split(":", 1)[0]
    if name.startswith("gemini"):
        return "gemini"
    return "unknown"


def capture_exception(
    exc: BaseException,
    *,
    user_id: str | None,
    request_id: str | None,
    privacy_signal: bool = False,
) -> None:
    """Queue an unhandled exception for PostHog error tracking. Never raises.

    Same consent path as events. ``privacy_signal`` (the request sent
    DNT/GPC) is passed explicitly because the 500 handler runs outside
    RequestIDMiddleware, after the per-request contextvar has been reset.
    """
    if _client is None or privacy_signal:
        return
    try:
        if _request_opted_out():
            return
        _enqueue(_Item(
            kind="exception",
            name="$exception",
            properties={"request_id": request_id} if request_id else {},
            actor=_actor(user_id),
            captured_at=time.time(),
            exc=exc,
        ))
    except Exception:
        logger.debug("PostHog capture_exception failed", exc_info=True)


def flush(timeout_seconds: float = 10.0) -> None:
    """Deliver everything queued so far — ours first, then the SDK's
    (bounded). Never raises."""
    flush_queue(timeout_seconds=timeout_seconds)
    client = _client
    if client is None:
        return
    try:
        client.flush(timeout_seconds=timeout_seconds)
    except Exception:
        logger.warning("PostHog flush failed", exc_info=True)


# ── Account deletion ────────────────────────────────────────────────────────

_PERSON_DELETE_TIMEOUT_S = 10.0

#: The second delete waits out every other process's cached "allowed"
#: (analytics_consent._TTL_S) plus a margin for their queues to deliver.
_SECOND_DELETE_MARGIN_S = 30.0


def _second_delete_delay_s() -> float:
    from services.analytics_consent import _TTL_S

    return _TTL_S + _SECOND_DELETE_MARGIN_S


def delete_person(user_id: str) -> None:
    """Best-effort: delete this user's PostHog person and their events —
    now, and once more after every process has stopped sending for them.

    Runs as a post-response BackgroundTask from account deletion, so it never
    adds latency and can never fail the deletion — every path returns None and
    logs. Needs the private REST API (a personal API key with ``person:write``
    plus the project id); without them it WARNs and skips, which leaves a
    manual deletion to do in the PostHog UI.

    Each pass drains OUR queue, then posthog's, then issues ``bulk_delete``,
    so nothing this process captured before the pass arrives after it. Why
    twice: THIS process refuses the user from the moment the route clears
    its cached consent, but another replica may hold a cached "allowed" for
    up to the consent TTL; anything it sends after the first ``bulk_delete``
    would re-create the person. The second pass runs after TTL + margin (a
    daemon timer: lost if this process exits first — logged, and in the ADR).

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
    """One drain + ``bulk_delete``. Returns whether the request was ISSUED
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

        # Our queue, then the SDK's — both bounded.
        flush(timeout_seconds=_PERSON_DELETE_TIMEOUT_S)

        # The one sanctioned direct httpx call outside db/ (CLAUDE.md): a
        # third-party REST API, not Supabase — like the OAuth exchange.
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
