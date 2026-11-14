"""The crisis-support path (docs/safety/crisis-support.md).

Every student-facing route that hands student-written text to a model screens
that text as the FIRST thing its handler does, before any rate limit, budget
or quota check and before its session or model work. A student in crisis must
never be answered with a 429 instead of the card, so no limiter may run
first. The call is one line at the top of the handler:

    if crisis := await crisis_support.screen_async(request, user_id, "tutor_chat", body.message):
        return crisis_support.turn_json(crisis)

(`screen` is the same for a sync `def` route).

The one exception is text the student STORED rather than typed: a note's
title and body, read by the notes agent actions. A match there never
blocks. The notes routes screen the note right after they read it (still
before any limit) with `screen_content_async`, then run their action
through `alongside`, which returns the action's own answer with the card
beside it: its result, or the error it raised (a 429, a 413, a 500), whose
body main.py's exception handlers give the card through `error_body`. The
action itself is limited, budgeted and written exactly as without a match.
A note is often material the student quotes (a patient, a play), which no
phrase list can tell from their own words, so they get the result they
asked for and the resources with it. The note chat's typed message still
blocks.

A crisis turn (a blocking screen) makes no model call, consumes no
rate-limit, budget or quota unit (the per-user LLM budget is checked at the
model chokepoint, which a crisis turn never reaches), and writes nothing a
turn writes: no message row, lazy session, summary, concept, card or graph
change. The triggering text is
never stored, logged, fingerprinted or sent anywhere (no `content=` on the
event either).

Order inside a screen: `crisis_detection.detect_any` first (pure: an ordinary
request pays only that, and reads no flag), then, on a match only, the caller
is AUTHENTICATED (`require_self` on the request's user id: a 401/403 for a
stranger, before anything is read or recorded about them), then the
`crisis_support` flag for this student (fail-closed "off": the route behaves
exactly as before), then the one `safety.crisis_support_shown` event and the
fixed response built from `services/crisis_support_copy.py`.

The event is category `system` (not the student's activity, so the usage
rollups skip it) and is NOT mirrored to PostHog (`posthog_client.
_NOT_MIRRORED` says why): it stays in our own `events` table.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Literal, TypeVar, get_args

from fastapi import Request
from sse_starlette.sse import EventSourceResponse

from db.connection import table
from services import auth_guard
from services import crisis_support_copy as crisis_copy
from services import events_service
from services.agent_events import SSE_CACHE_CONTROL, SaplingEvent, sapling_event_to_sse
from services.crisis_detection import CrisisMatch, detect_any
from services.feature_flags import flag_on
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
    _check_surface(surface)
    if sum(len(t or "") for t in texts) > _INLINE_DETECT_CHARS:
        match = await asyncio.to_thread(detect_any, texts)
    else:
        match = detect_any(texts)
    if match is None:
        return None
    await auth_guard.guard_off_loop(auth_guard.require_self, user_id, request)
    return await asyncio.to_thread(_resolve, user_id, surface, match)


async def screen_content_async(
    request: Request, user_id: str | None, surface: Surface, *texts: str | None,
) -> CrisisSupport | None:
    """`screen_async` for the student's STORED material (a note's title and
    body), which NEVER blocks: the caller does not stop on a match, it runs
    its action as usual through `alongside`, which attaches the card to
    whatever answer goes back. The match is screened, authenticated, flagged
    and logged exactly as for a typed message.

    A typed message blocks (the card instead of the result): it is what the
    student is saying now. A note is material they stored, often quoting
    someone else (a patient, a play), and no pattern can tell those apart, so
    the student gets the result they asked for and the card beside it."""
    return await screen_async(request, user_id, surface, *texts)


def _check_surface(surface: str) -> None:
    if surface not in SURFACES:
        raise ValueError(f"unknown crisis-support surface {surface!r}")


def _resolve(user_id: str | None, surface: str, match: CrisisMatch) -> CrisisSupport | None:
    if not flag_on(FLAG, user_id):
        return None
    payload = client_payload(counseling_for(user_id))
    # No `content=`: not even a fingerprint of what the student wrote.
    events_service.log_event(
        EVENT,
        category=events_service.SYSTEM_CATEGORY,
        user_id=user_id,
        payload={"surface": surface, "category": match.category, "tier": match.tier},
    )
    return CrisisSupport(surface=surface, category=match.category, payload=payload,
                         reply=render_reply(payload))


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
    result."""
    return {**neutral, "reply": support.reply, "crisis_support": support.payload}


def turn_json(support: CrisisSupport, **neutral: Any) -> dict[str, Any]:
    """`json_body` for a chat turn: the empty graph deltas a turn carries."""
    return json_body(support, graph_update={}, mastery_changes=[], **neutral)


def start_json(support: CrisisSupport) -> dict[str, Any]:
    """A session start: no session is opened (`session_id` null) and the copy
    stands in for the opener."""
    return json_body(support, session_id=None, initial_message=support.reply, graph_state=None)


#: Marks a result that carries the card BESIDE it (`alongside`), not instead
#: of it (`json_body`): the note chat shows both the reply and the card.
ALONGSIDE = "crisis_support_alongside"
#: Where `alongside` leaves the card on an exception the action raised;
#: `error_body` (main.py's exception handlers) puts it in the error answer.
_ERROR_CARD = "_crisis_support_payload"

_E = TypeVar("_E", bound=BaseException)


async def alongside(support: CrisisSupport | None, action: Awaitable[dict[str, Any]]) -> dict[str, Any]:
    """Await `action` (the route's own work, limits included) and attach the
    card to whatever answer goes back: its result (`crisis_support` plus
    `ALONGSIDE`), or the error it raises (a 429, a 413, a 500), whose body
    main.py's handlers give the card too. With no card, just the action."""
    if support is None:
        return await action
    try:
        result = await action
    except Exception as exc:
        card_from_payload(exc, support.payload)
        raise
    return {**result, "crisis_support": support.payload, ALONGSIDE: True}


def card_from_payload(exc: _E, payload: dict[str, Any] | None) -> _E:
    """`exc` carrying `payload` (the card) to the handler that answers it."""
    if payload is not None:
        try:
            setattr(exc, _ERROR_CARD, payload)
        except AttributeError:  # a slotted exception: the answer goes back without the card
            logger.warning("crisis support: could not attach the card to %s", type(exc).__name__)
    return exc


def card_from(source: BaseException, target: _E) -> _E:
    """`target` carrying `source`'s card: for a handler that answers `source`
    with a new exception (main.py's scope handlers)."""
    return card_from_payload(target, getattr(source, _ERROR_CARD, None))


def error_body(content: dict[str, Any], exc: BaseException) -> dict[str, Any]:
    """An error answer's body (`content`) with the card the failed action
    carried (`alongside`), if any."""
    payload = getattr(exc, _ERROR_CARD, None)
    return {**content, "crisis_support": payload} if payload is not None else content


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
