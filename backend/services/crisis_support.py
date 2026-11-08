"""The crisis-support path (docs/safety/crisis-support.md).

Every student-facing route that hands student-written text to a model screens
that text right after authentication and BEFORE any rate limit, budget or
quota check, and before its session or model work. A student in crisis must
never be answered with a 429 or a pause instead of the card, so no limiter may
run first. Two forms, one rule:

- `screened(...)`, a ROUTE DEPENDENCY, for a route that has route-level
  limiter dependencies (the loop's `_RATE_LIMITED`): listed before them, it
  authenticates on a match and raises `CrisisAnswered`, so neither a later
  dependency nor the handler runs.
- `screen` / `screen_async`, called as the handler's first statement after
  its auth, for a route whose limiters are all inline (the legacy tutor, the
  loop's goal / probe / review, notes): it returns `json_body` / `turn_json` /
  `sse_response` instead of the turn.

Either way a crisis turn makes no model call, consumes no rate-limit, budget or
tutor-call unit, and writes nothing a turn writes: no learning evidence, grade,
hint, help-ledger row, message row, session materialisation, XP or streak. The
triggering text is never stored, logged, fingerprinted or sent anywhere (no
`content=` on the event either).

Order inside a screen: `crisis_detection.detect_any` first (pure — a normal
turn never pays more than that), then the `crisis_support` flag for this
student (fail-closed "off": the route behaves exactly as before), then the
one `safety.crisis_support_shown` event and the fixed response built from
`services/crisis_support_copy.py`.

The event is category `system` (not the student's activity, so the usage
rollups skip it) and is NOT mirrored to PostHog (`posthog_client.
_NOT_MIRRORED` says why): it stays in our own `events` table.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, get_args

from fastapi import Depends, Request
from fastapi.responses import JSONResponse, Response
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
    # /api/learn/* (the tutor; delegates to the loop when the loop is on)
    "tutor_chat",
    "tutor_start",
    # /api/learn/loop/*
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


def screen(user_id: str | None, surface: Surface, *texts: str | None) -> CrisisSupport | None:
    """The crisis response for this request, or None to carry on as before.
    Blocking (a flag read on a match): sync routes only. Never raises on a
    store outage — the flag fails closed and the school read falls back."""
    match = detect_any(texts)
    if match is None:
        return None
    return _resolve(user_id, surface, match)


async def screen_async(user_id: str | None, surface: Surface, *texts: str | None) -> CrisisSupport | None:
    """`screen` for an `async def` route: no blocking read on the event loop."""
    if sum(len(t or "") for t in texts) > _INLINE_DETECT_CHARS:
        match = await asyncio.to_thread(detect_any, texts)
    else:
        match = detect_any(texts)
    if match is None:
        return None
    return await asyncio.to_thread(_resolve, user_id, surface, match)


def _resolve(user_id: str | None, surface: str, match: CrisisMatch) -> CrisisSupport | None:
    if surface not in SURFACES:
        raise ValueError(f"unknown crisis-support surface {surface!r}")
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
    as text), `crisis_support` (the card) and the route's own neutral keys."""
    return {**neutral, "reply": support.reply, "crisis_support": support.payload}


def turn_json(support: CrisisSupport, **neutral: Any) -> dict[str, Any]:
    """`json_body` for a chat turn: the empty graph deltas a turn carries."""
    return json_body(support, graph_update={}, mastery_changes=[], **neutral)


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
    return JSONResponse(
        json_body(support, session_id=None, initial_message=support.reply, graph_state=None)
    )


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
    if surface not in SURFACES:
        raise ValueError(f"unknown crisis-support surface {surface!r}")

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
