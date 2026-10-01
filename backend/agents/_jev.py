"""The Jev decision backend (learning loop PKG-15; spec §3.6, §8.24, §13 A24, A98; ADR 0027).

TypeSafe's Jev answers typed questions about a `state` with calibrated
probabilities: one `POST /v1/systemone` per decision, made here through the
official Python SDK, `typesafe-sdk==0.7.2` (pinned exactly in requirements.txt).
This is the ONLY module that imports it (invariant 24).

What this module owns, and nothing else:
- the build guard: a client exists only when `model_mode() == "real"` AND
  `services.decisions.JEV_ENABLED` (`enabled()`; checked by `_client`, the only
  constructor site). `SAPLING_MODEL_MODE=function` never reaches Jev, and
  `JEV_ENABLED=false` (the default) never builds a client.
- the pin: model `JEV_MODEL` ("jev-1.13.0", never an alias), a per-attempt
  timeout of `JEV_TIMEOUT_MS`, `JEV_MAX_RETRIES` retries on a connection error
  or a 500/502/503/504 only (never a timeout, a 429 or a 529: those repeat, and a
  sub-second decision with a fallback must not sleep — no backoff, no
  Retry-After), and a wall-clock deadline over the whole call.
- the circuit breaker: `JEV_CIRCUIT_FAILS` consecutive failed calls open it for
  `JEV_CIRCUIT_COOLDOWN_S`; after that one probe goes out (success closes it,
  failure re-opens it). In-process, like every other limiter here.
- the budget: a state whose pessimistic estimate (state + longest question,
  `CHARS_PER_TOKEN` chars per token) exceeds `JEV_STATE_MAX_TOKENS` is refused
  (`oversize`) before any call and is NEVER truncated — the caller serves it
  from Gemini.
- the wire shape: every question is a Choice (A24: never a Noul, whose answer
  carries no confidence); an answer outside the listed options, or a question
  left unanswered, is `bad_answer` (a failure, never a default).

What it does not own: fallbacks, events and llm_usage rows are
services/decisions.py's (it has the deps). A failure is one `JevUnavailable`
whose `code` is an event enum (`jev_absent`, `oversize`, `circuit_open`,
`timeout`, `transport`, `http_<status>`, `bad_answer`), never a message: the
SDK's own errors can quote the response body, which can echo the state.

No PII: the request body is exactly {state, model, questions}; the state is a
decision State's text fields (invariant 25: no identifier fields), and no
user, request or session id is sent in a header or a body. The SDK logs request
and response BODIES at DEBUG, so its logger is floored at WARNING here.

Privacy gate (spec §13 A24): until it passes, Jev may see only synthetic or
consented de-identified text. Code cannot check a contract, so `JEV_ENABLED`
stays false wherever student traffic flows until the owner records the gate.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import weakref
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agents._providers import model_mode
from config import LOCAL_APP_ENVS

if TYPE_CHECKING:  # pragma: no cover
    import httpx2

logger = logging.getLogger("sapling.jev")

PROVIDER = "typesafe"  # llm_usage.provider for every Jev row
API_KEY_ENV = "TYPESAFE_API_KEY"  # the SDK's own name (typesafe_sdk.constants.API_KEY_ENV)
SDK_LOGGER = "typesafe_sdk"
# Spec §13 A24's privacy gate, in code (A98 (k), A104): an ALLOWLIST. Only the APP_ENVs
# config.py treats as local (config.LOCAL_APP_ENVS, i.e. config.IS_LOCAL) are ungated;
# every other value (production, staging, prod, preview, unknown, unset) sends no Jev
# call, serve or shadow, until the owner records the gate.
PRIVACY_UNGATED_ENVS = LOCAL_APP_ENVS
PRIVACY_GATE_ENV = "JEV_PRIVACY_GATE_RECORDED"
CHARS_PER_TOKEN = 3  # † pessimistic (English runs ~4): Jev's tokenizer is unpublished (#672)
RETRY_STATUSES = frozenset({500, 502, 503, 504})  # never 429 / 529 (they repeat)
_MS_PER_S = 1000

#: Test seam: an httpx2 transport every client is built on (MockTransport in the
#: hermetic suite; the conftest guard installs one that refuses). Never set in production.
_transport_override: httpx2.AsyncBaseTransport | None = None

# The SDK is imported LAZILY, at the first Jev call past the build guard (A98 (j)): app
# start with JEV_ENABLED=false never depends on typesafe_sdk importing. Its names are
# always read as attributes of the loaded module (no rebinding, no getattr: invariant 24).
_SDK: Any = None
#: Test seam: the client class `_client()` builds instead of the SDK's. Never set in production.
_client_class_override: Any = None


def _load_sdk():
    """Import typesafe_sdk (once); a missing or broken SDK is `jev_absent` (the seam falls
    back), never an import error at app start."""
    global _SDK
    if _SDK is None:
        try:
            import typesafe_sdk
        except Exception:  # ImportError, or the SDK failing at its own import
            logger.warning("typesafe_sdk unavailable; Jev is absent")
            raise JevUnavailable("jev_absent") from None
        _SDK = typesafe_sdk
    _floor_sdk_logging()  # after the SDK's own import-time TYPESAFE_LOG_LEVEL handling
    return _SDK


def privacy_gate_open() -> bool:
    """A24 in code (A104): open only in a local APP_ENV (config.IS_LOCAL's set, read per
    call), or once the owner sets JEV_PRIVACY_GATE_RECORDED=true (only `true`, any case).
    Every other APP_ENV, unknown or unset, is gated: fail closed."""
    app_env = (os.getenv("APP_ENV") or "production").strip().lower()
    if app_env in PRIVACY_UNGATED_ENVS:
        return True
    return (os.getenv(PRIVACY_GATE_ENV) or "").strip().lower() == "true"


def _settings():
    """services.decisions owns the §3.6 settings; read at call time (tests patch them)."""
    from services import decisions

    return decisions


def enabled() -> bool:
    """The invariant-24 build guard: real model mode AND JEV_ENABLED."""
    return model_mode() == "real" and bool(_settings().JEV_ENABLED)


def _below_warning_dropped(record: logging.LogRecord) -> bool:
    return record.levelno >= logging.WARNING


def _floor_sdk_logging() -> None:
    """typesafe_sdk logs request/response BODIES (student text) at DEBUG and URLs at INFO.
    Unconditionally (A98 (l)): its logger is set to WARNING whatever root or
    TYPESAFE_LOG_LEVEL say, and a filter on it drops every record below WARNING even if
    someone lowers the level later. Records are created on that logger itself, so the
    filter runs before any propagation to a handler."""
    sdk = logging.getLogger(SDK_LOGGER)
    sdk.setLevel(logging.WARNING)
    if _below_warning_dropped not in sdk.filters:
        sdk.addFilter(_below_warning_dropped)


_floor_sdk_logging()


# ── vocabulary ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Question:
    """One Choice question: `options` maps each label Jev may answer to its description."""

    instructions: str
    options: dict[str, str]


@dataclass(frozen=True)
class Answer:
    choice: str
    confidence: float
    probabilities: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Result:
    answers: dict[str, Answer]
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


class JevUnavailable(Exception):
    """No usable Jev answer. `code` is an event enum; the billed tokens ride along
    when a response came back (an unusable 200 still costs)."""

    def __init__(
        self,
        code: str,
        *,
        latency_ms: int = 0,
        model: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.latency_ms = latency_ms
        self.model = model
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


def estimate_tokens(state: Any, questions: dict[str, Any]) -> int:
    """Pessimistic tokens for the state plus the single longest question (Jev's 32k
    budget is counted that way, docs.typesafe.ai/models)."""

    def chars(v: Any) -> int:
        if hasattr(v, "model_dump"):
            v = v.model_dump()
        return len(json.dumps(v, ensure_ascii=False, default=str))

    longest = max((chars(q) for q in questions.values()), default=0)
    return (chars(state) + longest) // CHARS_PER_TOKEN + 1


# ── the circuit breaker ───────────────────────────────────────────────────────
def _clock() -> float:
    return time.monotonic()


class _Breaker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.fails = 0
        self.opened_at: float | None = None
        self.probing = False

    def allow(self) -> bool:
        s = _settings()
        with self._lock:
            if self.opened_at is None:
                return True
            if _clock() - self.opened_at < s.JEV_CIRCUIT_COOLDOWN_S or self.probing:
                return False
            self.probing = True  # half-open: exactly one probe
            return True

    def success(self) -> None:
        with self._lock:
            self.fails, self.opened_at, self.probing = 0, None, False

    def failure(self) -> None:
        s = _settings()
        with self._lock:
            self.fails += 1
            if self.probing or self.fails >= s.JEV_CIRCUIT_FAILS:
                if self.opened_at is None or self.probing:
                    logger.warning(
                        "jev circuit open for %ss after %d consecutive failures",
                        s.JEV_CIRCUIT_COOLDOWN_S,
                        self.fails,
                    )
                self.opened_at, self.probing = _clock(), False

    def is_open(self) -> bool:
        with self._lock:
            return self.opened_at is not None


_breaker = _Breaker()


def circuit_open() -> bool:
    return _breaker.is_open()


# ── the client: one per running event loop (the #354 lesson; #672's pattern) ──
_clients: dict[int, tuple[weakref.ref, Any]] = {}
_clients_lock = threading.Lock()


def _retry_policy(sdk):
    return sdk.RetryPolicy(
        max_retries=_settings().JEV_MAX_RETRIES,
        backoff_initial=0.0,
        backoff_max=0.0,
        respect_retry_after=False,
        http_statuses=set(RETRY_STATUSES),
        api_timeout_error=False,
        api_connection_error=True,
        timeout=_settings().JEV_TIMEOUT_MS / _MS_PER_S,  # a retry only inside the budget
    )


def _client():
    """The ONLY client constructor site (invariant 24): refused unless `enabled()` and
    a key is set. An httpx2 pool binds to the loop that first uses it, so each running
    loop gets its own client; entries for closed or collected loops are pruned."""
    if not enabled():
        raise JevUnavailable("jev_absent")
    key = (os.getenv(API_KEY_ENV) or "").strip()
    if not key:
        raise JevUnavailable("jev_absent")
    sdk = _load_sdk()
    s = _settings()
    loop = asyncio.get_running_loop()
    with _clients_lock:
        for lid, (ref, _c) in list(_clients.items()):
            dead = ref()
            if dead is None or dead.is_closed():
                del _clients[lid]
        entry = _clients.get(id(loop))
        if entry is not None and entry[0]() is loop:
            return entry[1]
        cls = _client_class_override or sdk.AsyncTypeSafeClient
        client = cls(
            api_key=key,
            model=s.JEV_MODEL,
            retry=_retry_policy(sdk),
            timeout=s.JEV_TIMEOUT_MS / _MS_PER_S,
            transport=_transport_override,
        )
        _clients[id(loop)] = (weakref.ref(loop), client)
        return client


def reset_for_tests() -> None:
    global _breaker
    with _clients_lock:
        _clients.clear()
    _breaker = _Breaker()


async def aclose_clients() -> None:
    """App shutdown: close the running loop's client; other loops' clients cannot be
    awaited from here and are dropped. Never raises."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # pragma: no cover
        loop = None
    with _clients_lock:
        entries = list(_clients.values())
        _clients.clear()
    for ref, client in entries:
        if loop is not None and ref() is loop:
            try:
                await client.aclose()
            except Exception:  # pragma: no cover - shutdown is best effort
                logger.debug("jev client close failed", exc_info=True)


def _code(exc: BaseException, sdk) -> str:
    if isinstance(exc, (asyncio.TimeoutError, sdk.TypeSafeAPITimeoutError)):
        return "timeout"
    if isinstance(exc, sdk.TypeSafeAPIResponseValidationError):
        return "bad_answer"
    if isinstance(exc, sdk.TypeSafeAPIError):
        return f"http_{exc.status}"
    if isinstance(exc, sdk.TypeSafeAPIConnectionError):
        return "transport"
    return "bad_answer"  # a TypeSafeError before the wire (encoding): ours to fix, fail closed


def _parse(resp, questions: dict[str, Question], ms: int) -> Result:
    model = resp.model or _settings().JEV_MODEL
    usage = resp.usage
    tokens = dict(input_tokens=int(usage.input_tokens or 0), output_tokens=int(usage.output_tokens or 0))
    answers: dict[str, Answer] = {}
    for name, q in questions.items():
        a = resp.choices.get(name)
        if a is None or a.choice not in q.options:
            raise JevUnavailable("bad_answer", latency_ms=ms, model=model, **tokens)
        probs = {k: float(v) for k, v in (a.probabilities or {}).items() if k in q.options}
        answers[name] = Answer(a.choice, min(1.0, max(0.0, float(a.confidence))), probs)
    if model != _settings().JEV_MODEL:
        logger.warning("jev served %s, pinned %s", model, _settings().JEV_MODEL)
    return Result(answers=answers, model=model, latency_ms=ms, **tokens)


async def ask(state: dict[str, str], questions: dict[str, Question]) -> Result:
    """One Jev evaluation, or JevUnavailable. Order: the privacy gate, the build guard
    and the key (no call), the token budget (no call, never truncated, not a breaker
    failure), the breaker, then the call: JEV_TIMEOUT_MS bounds it IN TOTAL (the one
    retry included), after which the caller serves Gemini.

    Breaker accounting (review M1): once `allow()` lets the call out, EVERY exit but a
    parsed success counts a failure and releases a half-open probe — a JevUnavailable,
    any other exception (wrapped as `bad_answer`), and a cancellation (a client
    disconnect cancels the route), which still propagates."""
    s = _settings()
    if not privacy_gate_open():
        raise JevUnavailable("privacy_gate")
    client = _client()
    sdk = _load_sdk()
    wire = {name: sdk.Choice(instructions=q.instructions, criteria=dict(q.options)) for name, q in questions.items()}
    if estimate_tokens(state, wire) > s.JEV_STATE_MAX_TOKENS:
        raise JevUnavailable("oversize")
    if not _breaker.allow():
        raise JevUnavailable("circuit_open")
    deadline = s.JEV_TIMEOUT_MS / _MS_PER_S
    t0 = time.monotonic()
    succeeded = False

    def elapsed() -> int:
        return round((time.monotonic() - t0) * _MS_PER_S)

    try:
        try:
            resp = await asyncio.wait_for(client.system_one(state, wire, model=s.JEV_MODEL), timeout=deadline)
        except (asyncio.TimeoutError, sdk.TypeSafeError) as exc:
            # `from None`: the SDK error can quote the body, which can echo the state
            raise JevUnavailable(_code(exc, sdk), latency_ms=elapsed()) from None
        except Exception as exc:  # not the SDK's: still only "Jev answered nothing"
            logger.warning("jev call raised %s", type(exc).__name__)
            raise JevUnavailable("bad_answer", latency_ms=elapsed()) from None
        result = _parse(resp, questions, elapsed())
        succeeded = True
        return result
    finally:
        if succeeded:
            _breaker.success()
        else:
            _breaker.failure()
