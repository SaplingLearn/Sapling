"""LLM call resilience for the real provider models (#119).

The pieces `agents/_providers.py::_ResilientModelMixin` composes around every
real (Anthropic or Google) model request:

* **Retries** — exponential backoff with FULL jitter, on retryable provider
  errors only (408/409/429/5xx incl. Anthropic's 529 "overloaded", connection
  failures, timeouts). A 400/401/403/404, a validation error, or anything else
  is raised on the first attempt; output-validation retries stay pydantic-ai's
  job (they are a different layer: the model answered, its answer was wrong).
  A `retry-after` / `retry-after-ms` header on the provider's response is
  honoured when the SDK exposes it, up to `MAX_RETRY_AFTER_S`.
* **One attempt budget** — the SDKs' own retries are switched OFF where the
  model is built (`_providers._new_anthropic_provider` sets the Anthropic
  client's `max_retries=0`; google-genai makes a single attempt unless given
  `retry_options`, which we never pass), so `RETRY_ATTEMPTS` is the TOTAL
  number of HTTP attempts per model request, not a multiplier on a hidden
  inner budget. (Before #119 the Anthropic SDK made 1 + 2 attempts on its
  own; the total for Claude is unchanged, Gemini gains the same budget.)
* **A per-provider circuit breaker** — process-local and thread-safe (sync
  routes drive agents on worker threads through `run_agent_sync`, each with
  its own throwaway loop). CLOSED → OPEN after `BREAKER_FAILURE_THRESHOLD`
  consecutive retryable failures within `BREAKER_WINDOW_S`; OPEN fails fast
  with :class:`CircuitOpenError` for `BREAKER_COOLDOWN_S`; then HALF-OPEN lets
  exactly one probe through — success closes, a retryable failure re-opens.
* **The `llm_fallback` flag read** — see :func:`fallback_enabled`.

Nothing here builds a client or touches the network, and none of it is
reachable in function mode: only the real `_LoopSafe*` models carry the
mixin, and `model_for` never builds one outside `SAPLING_MODEL_MODE=real`.
"""

from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TypeVar

import httpx
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError

logger = logging.getLogger("sapling.agents.resilience")

T = TypeVar("T")

# ── Tuning (code constants, not env: #119 / CLAUDE.md "flags gate") ─────────

#: Total HTTP attempts per model request (first try + retries).
RETRY_ATTEMPTS = 3
#: Full-jitter backoff: sleep ~ U(0, min(BACKOFF_CAP_S, BACKOFF_BASE_S * 2**n))
#: before retry n (n = 0, 1, ...): ≤0.5 s, then ≤1 s.
BACKOFF_BASE_S = 0.5
BACKOFF_CAP_S = 4.0
#: A provider-sent retry-after up to this is honoured (the retry waits at
#: least that long). Longer than this and the retry is abandoned: holding a
#: request open 20 s+ on one provider's say-so is worse than failing (or
#: falling back) now. The Anthropic SDK honoured up to 60 s before #119.
MAX_RETRY_AFTER_S = 20.0

#: Statuses worth another attempt. Every other 5xx is retryable too.
RETRYABLE_STATUS = frozenset({408, 409, 429})

BREAKER_FAILURE_THRESHOLD = 8
BREAKER_WINDOW_S = 60.0
BREAKER_COOLDOWN_S = 30.0
#: A half-open probe that has not reported back within this long (a hung or
#: abandoned call) no longer blocks the next probe.
BREAKER_PROBE_TTL_S = 300.0

FALLBACK_FLAG = "llm_fallback"

#: Injected for tests (no real sleeping, deterministic jitter).
_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
_rng = random.Random()


class CircuitOpenError(ModelHTTPError):
    """The provider's breaker is open: failed fast without a request.

    A `ModelHTTPError(503)` so every existing `except ModelAPIError` /
    `except ModelHTTPError` handler treats it exactly like the upstream 503 it
    stands in for."""

    def __init__(self, provider: str, model_name: str):
        self.provider = provider
        super().__init__(
            status_code=503,
            model_name=model_name,
            body={"error": "circuit_open", "provider": provider},
        )

    def __reduce__(self):
        return self.__class__, (self.provider, self.model_name)


class DeadlineExceeded(ModelAPIError):
    """Our own per-request deadline (not an SDK timeout) fired."""


# ── Classification ───────────────────────────────────────────────────────


def is_retryable(exc: BaseException) -> bool:
    """Would another attempt plausibly succeed? Provider-side trouble only."""
    if isinstance(exc, CircuitOpenError):
        return False  # our own fast-fail: never count it as a provider failure
    if isinstance(exc, ModelHTTPError):
        return exc.status_code in RETRYABLE_STATUS or exc.status_code >= 500
    if isinstance(exc, ModelAPIError):
        # pydantic-ai raises the bare class for connection failures and SDK
        # timeouts (Anthropic's APIConnectionError/APITimeoutError), and for
        # our own DeadlineExceeded.
        return True
    # google-genai lets raw httpx transport errors through (pydantic-ai only
    # maps its `errors.APIError`).
    return isinstance(exc, (httpx.TimeoutException, httpx.NetworkError,
                            httpx.RemoteProtocolError, TimeoutError))


def provider_answered(exc: BaseException) -> bool:
    """A non-retryable HTTP error is still proof the provider is up."""
    return isinstance(exc, ModelHTTPError) and not isinstance(exc, CircuitOpenError) \
        and not is_retryable(exc)


def retry_after_s(exc: BaseException) -> float | None:
    """The provider's retry-after, in seconds, when the SDK error carries the
    HTTP response (Anthropic's `APIStatusError.response`, google-genai's
    `APIError.response`) as pydantic-ai's `__cause__`. Never raises."""
    try:
        headers = getattr(getattr(exc.__cause__, "response", None), "headers", None)
        if headers is None:
            return None
        ms = headers.get("retry-after-ms")
        if ms is not None:
            return max(0.0, float(ms) / 1000.0)
        secs = headers.get("retry-after")
        if secs is not None:
            return max(0.0, float(secs))
    except Exception:
        return None
    return None


def backoff_delay(retry_index: int) -> float:
    """Full-jitter exponential backoff before retry `retry_index` (0-based)."""
    ceiling = min(BACKOFF_CAP_S, BACKOFF_BASE_S * (2 ** retry_index))
    return _rng.uniform(0.0, ceiling)


def retry_delay(exc: BaseException, retry_index: int) -> float | None:
    """How long to wait before the next attempt, or None to give up now."""
    delay = backoff_delay(retry_index)
    after = retry_after_s(exc)
    if after is not None:
        if after > MAX_RETRY_AFTER_S:
            return None
        delay = max(delay, after)
    return delay


def describe(exc: BaseException) -> str:
    """Log-safe one-liner: the error class and status — never a body (which
    could echo prompt content)."""
    status = getattr(exc, "status_code", None)
    return f"{type(exc).__name__}" + (f"({status})" if status is not None else "")


# ── Circuit breaker ──────────────────────────────────────────────────────

CLOSED, OPEN, HALF_OPEN = "closed", "open", "half_open"


class CircuitBreaker:
    """Per-provider breaker. Every method takes the lock; nothing awaits
    under it, so it is safe across threads and event loops alike."""

    def __init__(self, provider: str, *, clock: Callable[[], float] = time.monotonic):
        self.provider = provider
        self.clock = clock
        self._lock = threading.Lock()
        self.state = CLOSED
        self._failures = 0
        self._streak_started = 0.0
        self._opened_at = 0.0
        self._probe_started: float | None = None

    def _transition(self, new: str, why: str) -> None:
        old, self.state = self.state, new
        logger.warning("llm circuit breaker %s: %s -> %s (%s)", self.provider, old, new, why)

    def allow(self) -> bool:
        """May a request go out now? In HALF_OPEN, True for exactly one
        caller at a time (the probe)."""
        with self._lock:
            now = self.clock()
            if self.state == CLOSED:
                return True
            if self.state == OPEN:
                if now - self._opened_at < BREAKER_COOLDOWN_S:
                    return False
                self._transition(HALF_OPEN, f"cooldown {BREAKER_COOLDOWN_S:.0f}s elapsed")
                self._probe_started = now
                return True
            # HALF_OPEN
            if self._probe_started is not None and now - self._probe_started < BREAKER_PROBE_TTL_S:
                return False
            self._probe_started = now
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            if self.state != CLOSED:
                self._probe_started = None
                self._transition(CLOSED, "probe succeeded")

    def record_failure(self) -> None:
        with self._lock:
            now = self.clock()
            if self.state == HALF_OPEN:
                self._opened_at = now
                self._probe_started = None
                self._transition(OPEN, "probe failed")
                return
            if self.state == OPEN:
                return  # a request that was already in flight when it opened
            if self._failures == 0 or now - self._streak_started > BREAKER_WINDOW_S:
                self._failures = 0
                self._streak_started = now
            self._failures += 1
            if self._failures >= BREAKER_FAILURE_THRESHOLD:
                self._opened_at = now
                self._failures = 0
                self._transition(
                    OPEN, f"{BREAKER_FAILURE_THRESHOLD} consecutive retryable failures"
                )

    def release(self) -> None:
        """The call ended with no verdict on the provider (cancelled, or a
        local error): free the half-open probe slot without a transition."""
        with self._lock:
            if self.state == HALF_OPEN:
                self._probe_started = None


_breakers: dict[str, CircuitBreaker] = {}
_breakers_lock = threading.Lock()


def breaker_for(provider: str) -> CircuitBreaker:
    with _breakers_lock:
        breaker = _breakers.get(provider)
        if breaker is None:
            breaker = _breakers[provider] = CircuitBreaker(provider)
        return breaker


def reset_for_tests() -> None:
    with _breakers_lock:
        _breakers.clear()


# ── The retry loop ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class CallSite:
    """Who is calling, for the breaker and the logs (never prompt content)."""

    provider: str
    model_name: str
    task: str | None


async def call_with_retries(
    site: CallSite,
    attempt: Callable[[], Awaitable[T]],
    *,
    deadline_s: float | None,
) -> T:
    """Run `attempt` under the provider's breaker, retrying retryable
    failures up to `RETRY_ATTEMPTS` total. `deadline_s` bounds EACH attempt
    (None: no outer deadline — the HTTP client's own timeouts still apply).

    Raises the last attempt's error, or :class:`CircuitOpenError` when the
    breaker refuses an attempt (including a retry: a breaker that opened
    mid-call stops it there)."""
    breaker = breaker_for(site.provider)
    last_exc: Exception | None = None
    for index in range(RETRY_ATTEMPTS):
        if not breaker.allow():
            raise CircuitOpenError(site.provider, site.model_name) from last_exc
        try:
            if deadline_s is None:
                result = await attempt()
            else:
                try:
                    async with asyncio.timeout(deadline_s):
                        result = await attempt()
                except TimeoutError as exc:
                    raise DeadlineExceeded(
                        site.model_name, f"model request exceeded its {deadline_s:.0f}s deadline"
                    ) from exc
        except BaseException as exc:
            if not isinstance(exc, Exception) or not is_retryable(exc):
                if isinstance(exc, Exception) and provider_answered(exc):
                    breaker.record_success()
                else:
                    breaker.release()
                raise
            breaker.record_failure()
            last_exc = exc
            last = index == RETRY_ATTEMPTS - 1
            delay = None if last else retry_delay(exc, index)
            if delay is None:
                logger.warning(
                    "llm request failed, not retrying (task=%s provider=%s model=%s "
                    "attempt=%d/%d error=%s)",
                    site.task, site.provider, site.model_name, index + 1, RETRY_ATTEMPTS,
                    describe(exc),
                )
                raise
            logger.warning(
                "llm request failed, retrying in %.2fs (task=%s provider=%s model=%s "
                "attempt=%d/%d error=%s)",
                delay, site.task, site.provider, site.model_name, index + 1, RETRY_ATTEMPTS,
                describe(exc),
            )
            await _sleep(delay)
            continue
        breaker.record_success()
        return result
    raise AssertionError("unreachable")  # pragma: no cover - the loop always returns/raises


def fallback_eligible(exc: BaseException) -> bool:
    """Is this the provider being unavailable (vs. our request being wrong)?"""
    return isinstance(exc, CircuitOpenError) or (isinstance(exc, Exception) and is_retryable(exc))


# ── The `llm_fallback` flag ──────────────────────────────────────────────


async def fallback_enabled() -> bool:
    """`llm_fallback` resolved GLOBALLY (user_id=None): the model layer never
    sees a student, so only the env override (`SAPLING_FLAG_LLM_FALLBACK`,
    the kill switch) and the flag's stored default apply — per-user and role
    rules and rollouts are ignored. Read only after the primary has already
    failed, so the happy path never touches the flag store. The cached answer
    costs no I/O; a cold cache is read off the event loop (bounded by
    `feature_flags.STORE_TIMEOUT_S`). Any failure reads as off."""
    try:
        from services import feature_flags

        resolution = feature_flags.cached_explain(FALLBACK_FLAG, None)
        if resolution is None:
            resolution = await asyncio.to_thread(feature_flags.explain, FALLBACK_FLAG, None)
        return resolution.variant == "on"
    except Exception:
        logger.warning("llm_fallback flag unreadable; treating as off", exc_info=True)
        return False


def settings_without(settings: Any, own: Any) -> Any:
    """`settings` minus the keys that came from a model's own bottom-layer
    `settings` (the agent merges `model.settings` into every request's
    settings). Keeps an agent/run-level key that differs from the model's."""
    if not settings:
        return settings
    own = own or {}
    kept = {k: v for k, v in settings.items() if not (k in own and own[k] == v)}
    return kept or None
