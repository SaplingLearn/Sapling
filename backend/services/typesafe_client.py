"""Thin async client for TypeSafe's Jev decision model (#642, ADR 0027).

Jev is NOT a chat model and not OpenAI-compatible: one endpoint evaluates a
``state`` against a map of typed ``questions`` and returns typed ``answers``
with calibrated probabilities. Verified against the primary docs
(docs.typesafe.ai/api, /models, /sdk/python/api/constants, 2026-09-26):

    POST {base}/v1/systemone
    Authorization: Bearer $TYPESAFE_API_KEY
    {"state": <str|object|array>, "model": "jev-latest",
     "questions": {"<key>": {"type": "noul"|"choice"|"score",
                              "instructions": ..., "criteria": ...}}}
    -> {"model": "jev-1.13.0",
        "answers": {"<key>": {"type": "noul", "noul": 0.95}
                   | {"type": "choice", "choice": "billing",
                      "probabilities": {...}, "confidence": 0.81}
                   | {"type": "score", "score": 1.05, "legend": {"0": ...},
                      "probabilities": {"0": ...}, "confidence": 0.92}},
        "usage": {"input_tokens": 296, "output_tokens": 20}}

Errors are plain HTTP statuses (401 bad key, 422 validation, 429 rate limit,
529 overloaded). The context budget is 64k tokens per request and **32k for
the state plus the single longest question** (docs.typesafe.ai/models).

Why bespoke rather than the official ``typesafe-sdk`` (PyPI 0.7.2, released
2026-09-26): this module is ~one POST. The SDK is pre-1.0 and days old, would
add a dependency to both ``requirements.txt`` and ``requirements.lock``, and
its headline feature — automatic 429/529 backoff — is exactly what a
sub-second decision on the tutor's hot path must NOT do: a throttled Jev call
should degrade to the fallback backend immediately, not sleep. The env var
names match the SDK's (``TYPESAFE_API_KEY`` / ``TYPESAFE_BASE_URL``), so an
operator's configuration carries over if we ever switch.

This module speaks the wire format and nothing else. It never falls back,
never applies confidence floors, never logs usage — `services/decisions.py`
owns all of that. Every failure is a :class:`JevError` whose ``kind`` is a
short, enum-like string safe to put in an event payload (never a message).

Not a Supabase client: the CLAUDE.md rule that all Supabase access goes
through ``db/connection.py::table()`` is about Supabase. This is a third-party
HTTP API, like the OAuth exchange in ``routes/auth.py``.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import weakref
from typing import Any

import httpx

API_KEY_ENV = "TYPESAFE_API_KEY"
BASE_URL_ENV = "TYPESAFE_BASE_URL"
DEFAULT_BASE_URL = "https://api.typesafe.ai"
EVALUATE_PATH = "/v1/systemone"
# Pinned, not the `jev-latest` alias: the docs advise pinning the versioned id
# once confidence thresholds are tuned against it, because an alias moves
# (and its answers can change) without a change on our side. The shadow-mode
# agreement report is exactly that tuning. Overridable via SAPLING_JEV_MODEL.
DEFAULT_MODEL = "jev-1.13.0"
MODEL_ENV = "SAPLING_JEV_MODEL"

#: Tokens for the state plus the single longest question (docs: /models).
STATE_TOKEN_BUDGET = 32_000


class JevError(Exception):
    """A Jev call that produced no usable answers.

    ``kind`` is a short machine-readable reason (``no_key``, ``timeout``,
    ``http_429``, ``transport``, ``bad_payload``, ...) — the value that lands
    in the ``decision.made`` event's ``fallback_reason``. Never put response
    bodies in it: they can echo the state (student text) back.
    """

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


def api_key() -> str:
    return (os.getenv(API_KEY_ENV) or "").strip()


def base_url() -> str:
    return (os.getenv(BASE_URL_ENV) or DEFAULT_BASE_URL).strip().rstrip("/")


def model_name() -> str:
    return (os.getenv(MODEL_ENV) or DEFAULT_MODEL).strip()


def estimate_tokens(text: str) -> int:
    """A deliberately PESSIMISTIC token estimate (~3 chars/token).

    Jev's tokenizer isn't published, and English prose runs ~4 chars/token, so
    this overestimates — which is the safe direction for a hard budget: a
    request we wrongly think is too big gets truncated or degrades to the
    fallback; one we wrongly think fits gets a 422 and degrades anyway, only
    slower and after spending a round trip.
    """
    return tokens_for_chars(len(text))


def tokens_for_chars(chars: int) -> int:
    """:func:`estimate_tokens` for a text of ``chars`` characters, without
    the text — the estimate depends on length only, so a caller that tracks
    a running length (decisions._fit_state) never has to build a string."""
    return chars // 3 + 1


# ── Per-event-loop client (the #354 lesson, applied to httpx) ──────────────
#
# An httpx.AsyncClient's connection pool binds to the event loop that first
# uses it. The app has one long-lived loop, but `run_agent_sync` and tests
# spin up throwaway loops; sharing one client across them is the "Event loop
# is closed" bug `_providers._LoopSafeGoogleModel` exists to prevent. Same
# shape of fix: one client per running loop, looked up at the moment of use.
# The app loop keeps its pooled TLS connection — which matters here, because a
# fresh handshake per call would eat a real share of Jev's sub-second budget.
#
# Keyed on id(loop) with only a WEAK reference to the loop, and every access
# prunes entries whose loop is closed or gone. (A WeakKeyDictionary keyed on
# the loop is not enough: a client whose pool touched the loop holds a strong
# path back to it, so its entry could never expire, pinning every throwaway
# loop and its client for the life of the process.) A pruned client belongs
# to a loop that can no longer run its aclose(); dropping it is all that is
# left to do. The app loop's client is closed by aclose_clients() on shutdown.

_clients: dict[int, tuple["weakref.ref[Any]", httpx.AsyncClient]] = {}
_clients_lock = threading.Lock()

#: Test seam: when set, every call uses a client built on this transport
#: (``httpx.MockTransport`` in the hermetic suite). Never set in production.
_transport_override: httpx.AsyncBaseTransport | None = None


def _prune_locked() -> None:
    for key, (loop_ref, _client_) in list(_clients.items()):
        loop = loop_ref()
        if loop is None or loop.is_closed():
            del _clients[key]


def _client() -> httpx.AsyncClient:
    if _transport_override is not None:
        return httpx.AsyncClient(transport=_transport_override)
    loop = asyncio.get_running_loop()
    with _clients_lock:
        _prune_locked()
        entry = _clients.get(id(loop))
        if entry is not None and entry[0]() is loop and not entry[1].is_closed:
            return entry[1]
        client = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        _clients[id(loop)] = (weakref.ref(loop), client)
        return client


async def aclose_clients() -> None:
    """Close the clients this module holds (app shutdown). The running loop's
    client is closed properly; clients of other loops cannot be awaited from
    here and are dropped. Never raises."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    with _clients_lock:
        entries = list(_clients.values())
        _clients.clear()
    for loop_ref, client in entries:
        if loop is not None and loop_ref() is loop and not client.is_closed:
            try:
                await client.aclose()
            except Exception:
                pass


async def evaluate(
    state: Any,
    questions: dict[str, dict],
    *,
    timeout_s: float,
    model: str | None = None,
) -> dict:
    """POST one evaluation and return the parsed JSON body.

    Raises :class:`JevError` for every failure — missing key (without a
    network call), timeout, transport error, non-2xx status, non-JSON body, or
    a body without an ``answers`` object. Deliberately NO retries: the caller
    has a fallback backend and a latency budget, and a retry spends the budget
    on the failure mode (429/529) most likely to repeat.
    """
    key = api_key()
    if not key:
        raise JevError("no_key")
    body = {"state": state, "model": model or model_name(), "questions": questions}
    # Serialized exactly as the budget estimate and the agent prompt are
    # (decisions._fit_state / _agent_prompt): default=str, so a datetime or
    # UUID in a caller's state is sent as its string, not a TypeError that
    # would fail the call before it leaves.
    payload = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
    client = _client()
    try:
        # Two layers: httpx's per-phase timeout (connect/read/write each), and
        # a hard wall-clock deadline over the whole call — a slow trickle of
        # bytes can satisfy every per-phase timeout and still blow the budget.
        resp = await asyncio.wait_for(
            client.post(
                base_url() + EVALUATE_PATH,
                content=payload,
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                timeout=httpx.Timeout(timeout_s),
            ),
            timeout=timeout_s,
        )
    except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
        raise JevError("timeout") from exc
    except httpx.HTTPError as exc:
        raise JevError("transport") from exc
    finally:
        if _transport_override is not None:
            await client.aclose()
    if resp.status_code != 200:
        raise JevError(f"http_{resp.status_code}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise JevError("bad_payload") from exc
    if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
        raise JevError("bad_payload")
    return data
