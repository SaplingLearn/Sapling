"""The crisis-support path (docs/safety/crisis-support.md).

Every student-facing route that hands student-written text to a model screens
that text at entry — after auth, BEFORE its session, rate-limit, budget or
model work — with `screen` (sync routes) or `screen_async` (async routes).
On a hit it returns `json_body` / `turn_json` / `sse_response` INSTEAD of its
turn, so a crisis turn makes no model call and writes nothing a turn writes:
no learning evidence, grade, hint, help-ledger row, message row, session
materialisation, XP or streak. The triggering text is never stored, logged,
fingerprinted or sent anywhere (no `content=` on the event either).

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
from dataclasses import dataclass
from typing import Any, Literal, get_args

from fastapi import Request
from sse_starlette.sse import EventSourceResponse

from db.connection import table
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
