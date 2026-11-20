"""The crisis-support path (docs/safety/crisis-support.md).

Every student-facing route that hands student-written text to a model screens
that text as the FIRST thing its handler does, before any rate limit, budget
or quota check and before its session or model work. A student in crisis must
never be answered with a 429 instead of the card, so no limiter may run
first. The call is one line at the top of the handler:

    if crisis := await crisis_support.screen_async(request, user_id, "tutor_chat", body.message):
        return crisis_support.turn_json(crisis)

(`screen` is the same for a sync `def` route).

A route whose limiters are ROUTE DEPENDENCIES (the learning loop's
`_RATE_LIMITED`) cannot screen in its handler, which runs after them: it
lists `screened(...)` as a dependency right after its kill switch and before
the rate limit. On a match the dependency authenticates the caller and raises
`CrisisAnswered`, whose response main.py's `answered_handler` returns as-is,
so neither a later dependency nor the handler runs.

The one exception is text the student STORED rather than typed: a note's
title and body, read by the notes agent actions. A match there never
blocks. The notes routes screen the note right after they read it (still
before any limit) with `screen_content_async`, then run their action
through `alongside`, which returns the action's own answer with the card
beside it: its result, or the error it raised (a 429, a 413, a 500),
answered by the app's own handler with the card added on the way out
(`ErrorCardMiddleware`). The
action itself is limited, budgeted and written exactly as without a match.
A note is often material the student quotes (a patient, a play), which no
phrase list can tell from their own words, so they get the result they
asked for and the resources with it. The note chat's typed message still
blocks. So does a tutor start's topic, unless it is the title of the
student's own note that Send to tutor handed over (`from_note_id`, checked
against the note): then the session starts with the card beside it. And a
flashcard generation's topic, unless it is one of the student's own graph
concepts (course material): then the cards are made with the card beside
them.

A crisis turn (a blocking screen) makes no model call, consumes no
rate-limit, budget, quota or tutor-call unit (the per-user LLM budget is
checked at the model chokepoint, which a crisis turn never reaches), and
writes nothing a turn writes: no message row, lazy session, summary,
concept, card or graph change, and on the learning loop no learning
evidence, grade, hint, help-ledger row, XP or streak. The triggering text is
never stored, logged, fingerprinted or sent anywhere (no `content=` on the
event either).

Order inside a screen: `crisis_detection.detect_any` first (pure: an ordinary
request pays only that, and reads no flag), then, on a match only, the caller
is AUTHENTICATED (`require_self` on the request's user id: a 401/403 for a
stranger, before anything is read or recorded about them), then the
`crisis_support` flag for this student (off by default: the route behaves
exactly as before), then the one `safety.crisis_support_shown` event and the
fixed response built from `services/crisis_support_copy.py`. The flag is read
with `feature_flags.last_known_flag_on` (sec2 M11): while the flag store is
unreadable it answers from the last snapshot this process read instead of
failing closed, so an outage cannot silently stop a card the owner switched
on; it never turns on a flag the last good read had off, and a process that
never read the store answers off.

The event is category `system` (not the student's activity, so the usage
rollups skip it) and is NOT mirrored to PostHog (`posthog_client.
_NOT_MIRRORED` says why): it stays in our own `events` table.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal, get_args

from fastapi import Depends, Request
from fastapi.responses import JSONResponse, Response
from sse_starlette.sse import EventSourceResponse

from db.connection import table
from services import auth_guard
from services import crisis_support_copy as crisis_copy
from services import events_service
from services.agent_events import SSE_CACHE_CONTROL, SaplingEvent, sapling_event_to_sse
from services.crisis_detection import CrisisMatch, detect_any
# Named `flag_on` here (the tests patch it); the store-outage behaviour is
# `last_known_flag_on`'s (see the module doc).
from services.feature_flags import last_known_flag_on as flag_on
from services.request_context import current_request_id

logger = logging.getLogger(__name__)

FLAG = "crisis_support"
EVENT = "safety.crisis_support_shown"

#: Where a screen ran: one name per student action (the JSON and streamed twin
#: of an action share it). The event's `surface` is one of these.
Surface = Literal[
    # /api/learn/* (the tutor; the quiz's "Ask about this" panel rides it too)
    "tutor_chat",
    "tutor_start",
    # /api/learn/loop/* (the learning loop)
    "loop_chat",
    "loop_start",
    "loop_goal",
    "loop_check_answer",
    "loop_step_attempt",
    "loop_probe_answer",
    "loop_review_answer",
    "loop_posttest_answer",
    # learning-loop spec §13 A138 / A139: a prequestion guess, a self-explanation reply
    "loop_prequestion_answer",
    "loop_self_explain",
    # /api/notes/*
    "note_chat",
    "note_send_to_tutor",
    "note_summarize",
    "note_extract_concepts",
    # /api/flashcards/*
    "flashcard_set_suggest",
    "flashcard_import_paste",
    "flashcard_import_cloze",
    "flashcard_generate",
]
SURFACES: tuple[str, ...] = get_args(Surface)

#: Above this many characters, detection runs off the event loop (a long note
#: takes milliseconds to scan; a chat message microseconds).
_INLINE_DETECT_CHARS = 4_000


@dataclass(frozen=True)
class CrisisSupport:
    """A screen that fired. `category` is for the event only — the client is
    never told which category matched."""

    surface: str
    category: str
    payload: dict[str, Any]
    reply: str


# ── Screening ──────────────────────────────────────────────────────────────


def screen(
    request: Request, user_id: str | None, surface: Surface, *texts: str | None,
) -> CrisisSupport | None:
    """The crisis response for this request, or None to carry on as before.
    Blocking on a match (the auth, flag and school reads): sync routes only.
    Never raises on a store outage — the flag fails closed and the school
    read falls back. Raises the route's own 401/403 for a caller who is not
    `user_id`, and only on a match."""
    _check_surface(surface)
    match = detect_any(texts)
    if match is None:
        return None
    auth_guard.require_self(user_id, request)
    return _resolve(user_id, surface, match)


async def screen_async(
    request: Request, user_id: str | None, surface: Surface, *texts: str | None,
) -> CrisisSupport | None:
    """`screen` for an `async def` route: no blocking read on the event loop."""
    return await _screen_async(request, user_id, surface, texts)


async def _match_async(
    request: Request, user_id: str | None, texts: tuple[str | None, ...],
) -> CrisisMatch | None:
    """Detection, then (on a match only) the caller's authentication."""
    if sum(len(t or "") for t in texts) > _INLINE_DETECT_CHARS:
        match = await asyncio.to_thread(detect_any, texts)
    else:
        match = detect_any(texts)
    if match is None:
        return None
    await auth_guard.guard_off_loop(auth_guard.require_self, user_id, request)
    return match


async def _screen_async(
    request: Request, user_id: str | None, surface: Surface, texts: tuple[str | None, ...],
    *, once_a_day: tuple[Any, ...] | None = None, hands_off_note: tuple[Any, ...] | None = None,
) -> CrisisSupport | None:
    _check_surface(surface)
    match = await _match_async(request, user_id, texts)
    if match is None:
        return None
    return await asyncio.to_thread(
        _resolve, user_id, surface, match, once_a_day=once_a_day, hands_off_note=hands_off_note,
    )


@dataclass(frozen=True)
class ContentScreen:
    """What `screen_content_async` answers: whether the student's STORED
    material matched (`support`, else None) and the request to answer on.
    Deliberately not a `CrisisSupport`, and never None: the blocking builders
    (`json_body`, `turn_json`, `start_json`, `sse_response`) refuse it, and
    `alongside`, the one thing that takes it, refuses anything else, so stored
    material can never be answered with the card INSTEAD of its result. Built
    by hand only where a route has shown that a typed-looking field holds
    stored material: a tutor start whose topic is the student's own note
    title (`screen_tutor_start_async`, `tutor.note_title_version`), and a flashcard
    generation whose topic is one of the student's own graph concepts
    (routes/flashcards.py, `concept_topic.topic_is_graph_concept`)."""

    request: Request
    support: CrisisSupport | None


async def screen_content_async(
    request: Request, user_id: str | None, surface: Surface, *texts: str | None,
    once_a_day: tuple[Any, ...] | None = None,
    hands_off_note: tuple[Any, ...] | None = None,
) -> ContentScreen:
    """`screen_async` for the student's STORED material (a note's title and
    body), which NEVER blocks: the caller runs its action as usual through
    `alongside(screen, action())`, which attaches the card to whatever answer
    goes back. The match is screened, authenticated, flagged and logged
    exactly as for a typed message.

    `once_a_day` names the material (the note's id and version) for a caller
    that re-screens the same material on every turn (the note chat): the card
    still goes beside every answer, but the event is recorded at most once a
    day for that student, surface and material, per process
    (`_first_today`). The key is a hash of ids, never of content.

    `hands_off_note` names the note version (id, updated_at) an action hands
    to the tutor (Send to tutor): its event is recorded as usual, and the
    version is remembered for the day, so the /learn start it hands over
    (`screen_tutor_start_async`) shows the card without recording it again.

    A typed message blocks (the card instead of the result): it is what the
    student is saying now. A note is material they stored, often quoting
    someone else (a patient, a play), and no pattern can tell those apart, so
    the student gets the result they asked for and the card beside it."""
    return ContentScreen(
        request,
        await _screen_async(request, user_id, surface, texts,
                            once_a_day=once_a_day, hands_off_note=hands_off_note),
    )


async def screen_tutor_start_async(
    request: Request, user_id: str | None, topic: str | None,
    *, note_version: Callable[[], Awaitable[tuple[Any, ...] | None]],
    surface: Surface = "tutor_start",
) -> CrisisSupport | ContentScreen | None:
    """The `surface` screen (the legacy start's `tutor_start`, or the loop's
    `loop_start`) of a session start's topic: None to carry on
    as before, a `CrisisSupport` to answer with the card INSTEAD of a session
    (`start_json`, `sse_response`), or a `ContentScreen` to start the session
    with the card beside it (`alongside`).

    The last only when `note_version()` (awaited on a match only, after the
    caller is authenticated and the flag is on) answers the version (id,
    updated_at) of the student's own note whose title the topic is: Send to
    tutor handed it over, so it is stored material. Its event is recorded
    once a day per student and note version, sharing the key Send to tutor
    remembered (`hands_off_note`), so the start right after it records no
    second card. A typed topic (`note_version()` answers None) records
    every match and blocks, as before. The hand-over key ignores `surface`, so
    a loop start after Send to tutor records no second card either."""
    _check_surface(surface)
    match = await _match_async(request, user_id, (topic,))
    if match is None:
        return None
    support = await asyncio.to_thread(_support, user_id, surface, match)
    if support is None:
        return None
    version = await note_version()
    once = None if version is None else _handoff_key(user_id, version)
    await asyncio.to_thread(_record, user_id, surface, match, once_a_day_key=once)
    return support if version is None else ContentScreen(request, support)


async def screen_quoting_async(
    request: Request, user_id: str | None, surface: Surface, message: str | None,
    *, quoted: Callable[[], Awaitable[list[str]]], once_a_day: tuple[Any, ...] | None = None,
) -> CrisisSupport | ContentScreen | None:
    """`screen_async` for a typed message that may QUOTE the student's stored
    material (#866 K12: the quiz Ask panel's first message quotes the quiz
    question, its explanation and the answer the student recorded): None to
    carry on as before, a `CrisisSupport` to answer INSTEAD of the turn, or a
    `ContentScreen` to run it with the card beside it (`alongside`).

    `quoted()` — awaited on a match only, after the caller is authenticated
    and the flag is on — answers the stored texts the message may quote, read
    by the caller off the student's own records, never taken from the client.
    Each one found in the message is stored material, screened as such (the
    card beside the answer); the rest of the message, with a sentence break
    where each quote was so no phrase spans one, is typed and blocks like any
    typed message. A quote found nowhere leaves the message typed, as before.
    The whole message's match decides nothing alone: a first-person frame
    around a quoted word ("I chose B: suicide") is not the student speaking.
    `once_a_day` names the material, for a client that re-sends it (Retry):
    the card goes beside every answer and its event is recorded once a day."""
    _check_surface(surface)
    if await _match_async(request, user_id, (message,)) is None:
        return None
    if not await asyncio.to_thread(flag_on, FLAG, user_id):
        return None
    stored = sorted({t for t in await quoted() if t and t in (message or "")}, key=len, reverse=True)
    typed = message or ""
    for text in stored:  # longest first: a quote inside a longer one goes with it
        typed = typed.replace(text, "\n.\n")
    if crisis := await _screen_async(request, user_id, surface, (typed,)):
        return crisis
    return ContentScreen(
        request, await _screen_async(request, user_id, surface, tuple(stored), once_a_day=once_a_day),
    )


def _check_surface(surface: str) -> None:
    if surface not in SURFACES:
        raise ValueError(f"unknown crisis-support surface {surface!r}")


def _resolve(
    user_id: str | None, surface: str, match: CrisisMatch,
    *, once_a_day: tuple[Any, ...] | None = None, hands_off_note: tuple[Any, ...] | None = None,
) -> CrisisSupport | None:
    support = _support(user_id, surface, match)
    if support is not None:
        _record(
            user_id, surface, match,
            once_a_day_key=None if once_a_day is None else (user_id, surface, *once_a_day),
            remember_key=None if hands_off_note is None else _handoff_key(user_id, hands_off_note),
        )
    return support


def _support(user_id: str | None, surface: str, match: CrisisMatch) -> CrisisSupport | None:
    """The card for a match, or None with the flag off. Records nothing."""
    if not flag_on(FLAG, user_id):
        return None
    payload = client_payload(counseling_for(user_id))
    return CrisisSupport(surface=surface, category=match.category, payload=payload,
                         reply=render_reply(payload))


def _record(
    user_id: str | None, surface: str, match: CrisisMatch,
    *, once_a_day_key: tuple[Any, ...] | None = None, remember_key: tuple[Any, ...] | None = None,
) -> None:
    """The one event for a shown card: always, or (with `once_a_day_key`)
    the first time that key is seen today. `remember_key` is marked seen
    without gating this event (Send to tutor, for the start it hands over)."""
    if once_a_day_key is None or _first_today(once_a_day_key):
        # No `content=`: not even a fingerprint of what the student wrote.
        events_service.log_event(
            EVENT,
            category=events_service.SYSTEM_CATEGORY,
            user_id=user_id,
            payload={"surface": surface, "category": match.category, "tier": match.tier},
        )
    if remember_key is not None:
        _first_today(remember_key)


#: The once-a-day scope Send to tutor and the tutor start it hands over share:
#: one recorded card per student and note version a day.
_NOTE_HANDOFF = "note_handoff"


def _handoff_key(user_id: str | None, note_version: tuple[Any, ...]) -> tuple[Any, ...]:
    return (user_id, _NOTE_HANDOFF, *note_version)


#: `once_a_day` keys already recorded in this process: sha256 of the ids →
#: when (time.monotonic) the key may be recorded again. Every key lives the
#: same `_ONCE_A_DAY_S` and is (re)inserted at the end, so the map is in
#: expiry order: eviction pops from the front only (expired keys, then the
#: oldest past `_ONCE_A_DAY_MAX`), amortized O(1) under the lock.
_ONCE_A_DAY_S = 24 * 3600
_ONCE_A_DAY_MAX = 10_000
_recorded_today: OrderedDict[str, float] = OrderedDict()
_recorded_lock = threading.Lock()


def _first_today(parts: tuple[Any, ...]) -> bool:
    """True (and remembered for a day) the first time `parts` is seen."""
    key = hashlib.sha256(json.dumps([str(p) for p in parts]).encode()).hexdigest()
    now = time.monotonic()
    with _recorded_lock:
        until = _recorded_today.get(key)
        if until is not None and until > now:
            return False
        _recorded_today.pop(key, None)  # an expired key goes back in at the end
        while _recorded_today:
            oldest, oldest_until = next(iter(_recorded_today.items()))
            if oldest_until > now and len(_recorded_today) < _ONCE_A_DAY_MAX:
                break
            del _recorded_today[oldest]
        _recorded_today[key] = now + _ONCE_A_DAY_S
        return True


def clear_once_a_day() -> None:
    """Forget every `once_a_day` key (tests)."""
    with _recorded_lock:
        _recorded_today.clear()


# ── Campus counseling (per school) ─────────────────────────────────────────


def counseling_for(user_id: str | None) -> crisis_copy.CampusCounseling:
    """The student's school's configured counseling service, else the default.
    No read at all while nothing is configured; any read failure → default."""
    if not user_id or not crisis_copy.CAMPUS_COUNSELING:
        return crisis_copy.DEFAULT_CAMPUS_COUNSELING
    try:
        rows = table("enrollments").select(
            "course_offerings(courses(schools(slug)))",
            filters={"user_id": f"eq.{user_id}"},
        ) or []
    except Exception:  # noqa: BLE001 — the card must render whatever the DB does
        logger.warning("crisis support: school lookup failed; showing the default counseling entry")
        return crisis_copy.DEFAULT_CAMPUS_COUNSELING
    for slug in sorted({s for s in map(_school_slug, rows) if s}):
        if slug in crisis_copy.CAMPUS_COUNSELING:
            return crisis_copy.CAMPUS_COUNSELING[slug]
    return crisis_copy.DEFAULT_CAMPUS_COUNSELING


def _school_slug(row: Any) -> str | None:
    node: Any = row
    for key in ("course_offerings", "courses", "schools"):
        node = node.get(key) if isinstance(node, dict) else None
    slug = node.get("slug") if isinstance(node, dict) else None
    return slug if isinstance(slug, str) and slug else None


# ── The response ───────────────────────────────────────────────────────────


def client_payload(counseling: crisis_copy.CampusCounseling) -> dict[str, Any]:
    """The `crisis_support` object the frontend card renders (all copy)."""
    return {
        "version": crisis_copy.COPY_VERSION,
        "title": crisis_copy.TITLE,
        "intro": list(crisis_copy.INTRO),
        "resources_heading": crisis_copy.RESOURCES_HEADING,
        "resources": [
            {
                "id": r.id,
                "name": r.name,
                "detail": r.detail,
                "actions": [{"kind": a.kind, "label": a.label, "href": a.href} for a in r.actions],
            }
            for r in crisis_copy.resources(counseling)
        ],
        "closing": list(crisis_copy.CLOSING),
        "dismiss_label": crisis_copy.DISMISS_LABEL,
    }


def render_reply(payload: dict[str, Any]) -> str:
    """The same copy as Markdown, for a client that renders only `reply`."""
    lines = [f"**{payload['title']}**", "", *_paragraphs(payload["intro"]), ""]
    lines += [f"- **{r['name']}**: {r['detail']}" for r in payload["resources"]]
    lines += ["", *_paragraphs(payload["closing"])]
    return "\n".join(lines).strip()


def _paragraphs(items: list[str]) -> list[str]:
    out: list[str] = []
    for text in items:
        out += [text, ""]
    return out[:-1]


def json_body(support: CrisisSupport, **neutral: Any) -> dict[str, Any]:
    """The body a JSON route returns instead of its result: `reply` (the copy
    as text), `crisis_support` (the card) and the route's own neutral keys, so
    a client that ignores `crisis_support` still reads a well-formed, empty
    result. Only for a blocking screen: a `ContentScreen` is refused."""
    _blocking(support)
    return {**neutral, "reply": support.reply, "crisis_support": support.payload}


def _blocking(support: Any) -> None:
    if not isinstance(support, CrisisSupport):
        raise TypeError(
            f"a blocking crisis answer needs a CrisisSupport, not {type(support).__name__} "
            "(stored material rides alongside its result: crisis_support.alongside)"
        )


def turn_json(support: CrisisSupport, **neutral: Any) -> dict[str, Any]:
    """`json_body` for a chat turn: the empty graph deltas a turn carries."""
    return json_body(support, graph_update={}, mastery_changes=[], **neutral)


def start_json(support: CrisisSupport) -> dict[str, Any]:
    """A session start: no session is opened (`session_id` null) and the copy
    stands in for the opener."""
    _blocking(support)
    return json_body(support, session_id=None, initial_message=support.reply, graph_state=None)


#: Marks a result that carries the card BESIDE it (`alongside`), not instead
#: of it (`json_body`): the note chat shows both the reply and the card.
ALONGSIDE = "crisis_support_alongside"


#: Where `alongside` leaves the card when the action raises: the request's
#: state (`scope["state"]`), read by `ErrorCardMiddleware` off the error answer.
ERROR_CARD_STATE = "crisis_support_card"


async def alongside(
    screen: ContentScreen, action: Awaitable[dict[str, Any] | EventSourceResponse],
) -> dict[str, Any] | EventSourceResponse:
    """Await `action` (the route's own work, limits included) and attach the
    card `screen` found to whatever answer goes back: its result
    (`crisis_support` plus `ALONGSIDE`; for a stream, in its `done` event's
    data), or the error it raises (a 429, a 413, a 500). An error is NOT
    answered here: the card is left on the request's state and the exception
    re-raised, so it reaches the app's own handler (and, for an unexpected
    one, ServerErrorMiddleware, the server's error log and the trace) exactly
    as without a match; `ErrorCardMiddleware`, outside the whole stack, adds
    the card to whatever JSON error answer goes back. Status, detail, headers
    and envelope are the handler's, and no handler needs to know about the
    card. With no card, just the action. `screen` must come from
    `screen_content_async`."""
    if not isinstance(screen, ContentScreen):
        if inspect.iscoroutine(action):
            action.close()
        raise TypeError(
            f"alongside takes screen_content_async's ContentScreen, not {type(screen).__name__}"
        )
    support = screen.support
    if support is None:
        return await action
    try:
        result = await action
    except Exception:
        setattr(screen.request.state, ERROR_CARD_STATE, support.payload)
        raise
    if isinstance(result, EventSourceResponse):
        result.body_iterator = _stream_with_card(result.body_iterator, support.payload)
        return result
    return {**result, "crisis_support": support.payload, ALONGSIDE: True}


async def _stream_with_card(events: Any, payload: dict[str, Any]):
    """A tutor stream's events, its terminal `done` event's data carrying the
    card beside the turn (what consumeChatStream resolves the turn from)."""
    try:
        async for item in events:
            if isinstance(item, dict) and item.get("event") == "done":
                event = json.loads(item["data"])
                event["data"] = {**(event.get("data") or {}), "crisis_support": payload, ALONGSIDE: True}
                item = {**item, "data": json.dumps(event)}
            yield item
    finally:
        close = getattr(events, "aclose", None)
        if close is not None:
            await close()


#: The most error-body bytes `ErrorCardMiddleware` holds back to add the card
#: to. An error answer is a short JSON object; one past this goes back as it
#: is, without the card, rather than buffered whole.
_ERROR_CARD_MAX_BODY = 64 * 1024


class ErrorCardMiddleware:
    """Pure ASGI, wrapped around the app's WHOLE middleware stack
    (`install_error_card`), so every error answer passes through it: the ones
    ExceptionMiddleware's handlers produce (a 429, a 413, a 422, a domain
    error) and the generic 500 that ServerErrorMiddleware produces outside
    the user middleware. When `alongside` left a card on the request's state
    and the answer is a JSON object with an error status, the card is added
    to that body (Content-Length adjusted); status and every other header
    are left as they are. Anything else streams through untouched, and an
    exception still propagates past it to the server.

    What it holds back (the error answer's start and its body so far) is
    always forwarded: unchanged, without the card, when the body outgrows
    `_ERROR_CARD_MAX_BODY`, when the inner app raises before the body is
    whole (then the exception propagates, as without a card), or when it
    returns without finishing it. The server sees exactly the no-card answer."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        # The dict request.state writes into, shared with every layer below.
        state = scope.setdefault("state", {})
        # The messages held back, the start first; None while nothing is held.
        held: list[dict[str, Any]] | None = None
        held_bytes = 0

        async def release() -> None:
            nonlocal held
            messages, held = held or [], None
            for message in messages:
                await send(message)

        async def send_with_card(message: dict[str, Any]) -> None:
            nonlocal held, held_bytes
            if held is None:
                if (message["type"] == "http.response.start" and message["status"] >= 400
                        and ERROR_CARD_STATE in state and _is_json(message)):
                    held = [message]  # held until the body is whole
                    return
                await send(message)
                return
            held.append(message)
            if message["type"] != "http.response.body":
                await release()
                return
            held_bytes += len(message.get("body", b""))
            if held_bytes > _ERROR_CARD_MAX_BODY:
                logger.warning("crisis support: an error answer too long to hold goes back without the card")
                await release()
                return
            if message.get("more_body", False):
                return
            start, *bodies = held
            held = None
            body = _body_with_card(b"".join(m.get("body", b"") for m in bodies), state[ERROR_CARD_STATE])
            headers = [(k, v) for k, v in start.get("headers", []) if k.lower() != b"content-length"]
            await send({**start, "headers": [*headers, (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})

        try:
            await self.app(scope, receive, send_with_card)
        except Exception:
            if held is not None:
                try:
                    await release()
                except Exception:  # noqa: BLE001 — the app's own exception is the one that propagates
                    logger.warning("crisis support: a held error answer could not be forwarded", exc_info=True)
            raise
        if held is not None:
            await release()


def install_error_card(app: Any) -> None:
    """Make `ErrorCardMiddleware` the outermost layer of `app` (outside every
    ServerErrorMiddleware, the one carrying main.py's generic 500 included).
    Starlette has no slot outside ServerErrorMiddleware, so this wraps
    `build_middleware_stack`, as the OpenTelemetry instrumentation does;
    call it AFTER instrumenting, which expects ServerErrorMiddleware on top."""
    build = app.build_middleware_stack
    app.build_middleware_stack = lambda: ErrorCardMiddleware(build())
    app.middleware_stack = None


def _is_json(start: dict[str, Any]) -> bool:
    for key, value in start.get("headers", []):
        if key.lower() == b"content-type":
            return value.split(b";", 1)[0].strip().lower() == b"application/json"
    return False


def _body_with_card(body: bytes, payload: dict[str, Any]) -> bytes:
    """A JSON error body with the card in it, rendered as JSONResponse renders;
    a body that is not a JSON object goes back as it was."""
    try:
        content = json.loads(body)
    except ValueError:
        content = None
    if not isinstance(content, dict):
        logger.warning("crisis support: an error answer that is not a JSON object goes back without the card")
        return body
    return json.dumps({**content, "crisis_support": payload}, ensure_ascii=False,
                      allow_nan=False, indent=None, separators=(",", ":")).encode("utf-8")


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or current_request_id() or str(uuid.uuid4())


def sse_response(support: CrisisSupport, request: Request, **neutral: Any) -> EventSourceResponse:
    """A complete, well-formed chat stream: ONE `done` event whose data is
    `turn_json` — what the tutor stream consumers already resolve a turn
    from. No tokens: the card appears whole, not typed out."""
    data = turn_json(support, **neutral)

    async def events():
        yield sapling_event_to_sse(
            SaplingEvent(type="done", step="reply", message="Complete.", data=data)
        )

    return EventSourceResponse(
        events(),
        headers={"X-Request-ID": _request_id(request), "Cache-Control": SSE_CACHE_CONTROL},
    )


# ── The route-dependency form (routes with limiter dependencies) ───────────

#: Builds a route's crisis response: `turn_response` / `turn_stream` /
#: `start_response` / `start_stream`, or `plain_response(**neutral_keys)`.
Responder = Callable[[CrisisSupport, Request], Response]


class CrisisAnswered(Exception):
    """Raised by a `screened` dependency on a match with the flag on. It carries
    the finished response, which main.py's `answered_handler` returns as-is.
    Raising is how a dependency ends a request early (as HTTPException does), so
    no later dependency (the rate limit) and not the handler run. It is not an
    error: the status is 200, and it carries no student text."""

    def __init__(self, response: Response) -> None:
        super().__init__("crisis support answered the request")
        self.response = response


async def answered_handler(_request: Request, exc: CrisisAnswered) -> Response:
    return exc.response


def turn_response(support: CrisisSupport, _request: Request) -> Response:
    return JSONResponse(turn_json(support))


def turn_stream(support: CrisisSupport, request: Request) -> Response:
    return sse_response(support, request)


def start_response(support: CrisisSupport, _request: Request) -> Response:
    """No session is opened: `session_id` is null and the copy is the opener."""
    return JSONResponse(start_json(support))


def start_stream(support: CrisisSupport, request: Request) -> Response:
    return sse_response(support, request, session_id=None)


def plain_response(**neutral: Any) -> Responder:
    def respond(support: CrisisSupport, _request: Request) -> Response:
        return JSONResponse(json_body(support, **neutral))

    return respond


def screened(surface: Surface, *fields: str, respond: Responder):
    """The crisis screen as a ROUTE DEPENDENCY. List it before any rate-limit,
    budget or quota dependency; the learning loop places it right after its
    kill switch.

    `fields` name the request body's student-written text, dotted when nested
    ("goal.text"). Detection runs first and is pure, so an ordinary request pays
    nothing more and reads no flag. On a match, the caller is authenticated
    first (`require_self` on the body's `user_id`, else the session user), then
    the flag is read. With the flag on, `CrisisAnswered(respond(...))` is raised
    and the request ends there. With no match, or the flag off, the dependency
    returns and the route carries on exactly as before.

    The body is the one FastAPI already parsed (Starlette caches it); it has not
    been validated yet, so only string values are read."""
    _check_surface(surface)

    async def crisis_screen(request: Request) -> None:
        body = await _json_object(request)
        texts = [_text_at(body, field) for field in fields]
        if sum(len(t or "") for t in texts) > _INLINE_DETECT_CHARS:
            match = await asyncio.to_thread(detect_any, texts)
        else:
            match = detect_any(texts)
        if match is None:
            return
        user_id = await _authenticated(request, body)
        support = await asyncio.to_thread(_resolve, user_id, surface, match)
        if support is not None:
            raise CrisisAnswered(respond(support, request))

    crisis_screen.surface = surface  # type: ignore[attr-defined]  # read by the ordering tests
    return Depends(crisis_screen)


def is_screen(dependency_call: Any) -> bool:
    """Whether a route dependency's callable is a `screened` crisis screen."""
    return getattr(dependency_call, "__name__", "") == "crisis_screen" and hasattr(
        dependency_call, "surface"
    )


async def _json_object(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — no JSON object: nothing to screen
        return {}
    return body if isinstance(body, dict) else {}


def _text_at(body: dict[str, Any], dotted: str) -> str | None:
    node: Any = body
    for key in dotted.split("."):
        node = node.get(key) if isinstance(node, dict) else None
    return node if isinstance(node, str) else None


async def _authenticated(request: Request, body: dict[str, Any]) -> str:
    """The caller, checked as the handler would check it, before the flag read
    and the event: the body's `user_id` must be the session's (403/401
    otherwise), and a body that names nobody means the session user."""
    claimed = body.get("user_id")
    if isinstance(claimed, str) and claimed:
        await auth_guard.guard_off_loop(auth_guard.require_self, claimed, request)
        return claimed
    return await auth_guard.guard_off_loop(auth_guard.get_session_user_id, request)
