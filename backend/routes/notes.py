"""HTTP routes for the notetaker.

CRUD lives here; agent-backed actions (summarize, extract concepts, chat,
generate quiz, send to tutor) come in Phase 4 below.

The model-calling actions run the crisis screen, then the learning loop's
integrity guard (spec §13 A125): services/note_guard.py says which actions and
why.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded

from agents import ORCHESTRATOR_LIMITS, WORKER_LIMITS
from agents.deps import SaplingDeps
from agents.note_chat import note_chat_agent
from agents.note_concepts import note_concepts_agent
from agents.note_summary import note_summary_agent
from agents.tools.graph import apply_concepts_to_graph
from agents.usage import record_agent_usage
from db.connection import table
from learning.gate import learning_loop_for_request
from services import crisis_support, events_service, integrity_guard
from services.note_guard import note_chat_texts, note_texts, open_note_guard
from services.academics import (
    course_offering_ids, offering_course_id, require_course_enrollment, resolve_offering,
    term_id_for_label, user_offering_ids_for_course,
)
from services.auth_guard import get_session_user_id, require_self, guard_off_loop
from services.notes_service import (
    create_note,
    delete_note,
    get_note,
    link_concept,
    link_prechecked_concepts,
    list_linked_concepts,
    list_notes,
    save_summary,
    unlink_concept,
    update_note,
)
from services.http_cache import cached_json, conditional, make_etag
from services.request_context import current_request_id
from services.xp_service import award_xp_safe

logger = logging.getLogger(__name__)

router = APIRouter()

# note_chat has no legacy fallback (ADR 0017), so guardrail trips degrade to
# an in-band reply rather than falling back or surfacing a 5xx (#329).
_CHAT_DEGRADED_REPLY = (
    "I couldn't finish answering that — the request hit its processing "
    "budget. Try again with a shorter or more specific message."
)


async def _run_note_worker(agent, user_prompt: str, deps: SaplingDeps, *, action: str):
    """Run a single-shot note worker under WORKER_LIMITS (#329).

    The two guardrail failure modes are distinct and must not be conflated:
    a budget trip is deterministic (retrying the same note fails identically),
    while unexpected model behavior is a genuine bug that must page us.
    """
    try:
        return await agent.run(user_prompt, deps=deps, usage_limits=WORKER_LIMITS)
    except UsageLimitExceeded as e:
        # Deterministic budget exhaustion — a 413 with no "try again" wording,
        # since retrying the same (too-long) note trips the same limit.
        logger.warning(
            "note %s agent hit its usage budget; returning 413", action, exc_info=e
        )
        raise HTTPException(
            status_code=413,
            detail=(
                f"This note is too long to complete {action} automatically. "
                "Shortening the note may help."
            ),
        ) from e
    except UnexpectedModelBehavior as e:
        # Malformed model output / validation-retry exhaustion — a real bug,
        # surfaced as a 5xx (so alerting fires) with a traceback in the log.
        logger.exception("note %s agent returned unexpected model behavior", action)
        raise HTTPException(
            status_code=500,
            detail="Something went wrong generating this note's AI output.",
        ) from e


async def _course_meta(offering_id: str | None, cache: dict) -> dict:
    """Resolve an offering to its abstract course id + human labels.

    Notes key on the OFFERING (a course taught in a term), but the notetaker
    UI keys on the abstract catalog course id (and shows a course label).
    Without these fields every note renders as "Unknown course" (finding F4).
    Mirrors calendar.py::_course_meta_cached: a per-request memo keyed on
    offering_id so a list of notes sharing a course hits the DB once.
    """
    if not offering_id:
        return {"course_id": None, "course_code": None, "course_name": None}
    if offering_id not in cache:
        course_id = await asyncio.to_thread(offering_course_id, offering_id)
        course = {}
        if course_id:
            rows = await table("courses").aselect(
                "id,course_code,course_name",
                filters={"id": f"eq.{course_id}"}, limit=1,
            )
            course = rows[0] if rows else {}
        cache[offering_id] = {
            "course_id": course_id,
            "course_code": course.get("course_code"),
            "course_name": course.get("course_name"),
        }
    return cache[offering_id]


def _course_offering_ids(user_id: str, course_id: str) -> list[str]:
    """Every offering of ``course_id`` a note of the student's can sit in:
    all of the course's offerings, or — if that read cannot tell — the ones
    the student is enrolled in (#831 follow-up)."""
    ids = course_offering_ids(course_id)
    return ids if ids is not None else user_offering_ids_for_course(user_id, course_id)


class CreateNoteBody(BaseModel):
    user_id: str
    course_id: str
    title: str = ""
    body: str = ""
    tags: list[str] = Field(default_factory=list)


class UpdateNoteBody(BaseModel):
    user_id: str
    title: str | None = None
    body: str | None = None
    tags: list[str] | None = None
    course_id: str | None = None


@router.get("/user/{user_id}")
async def list_user_notes(
    user_id: str,
    request: Request,
    course_id: str | None = None,
    semester: str | None = None,
):
    await guard_off_loop(require_self, user_id, request)
    # The API speaks abstract course ids; notes key on the offering. A course
    # filter covers EVERY offering of the course (#831 follow-up): a note is
    # filed under the student's enrollment (any term, the #115 gate) and,
    # before that gate, under the term it was written in, so the current
    # term's offering alone hid notes from past terms. Rows stay the
    # caller's own (`list_notes` filters on user_id). With a `semester` (term
    # label, #141) it is STRICTLY that term's offering: an unknown label or a
    # term with no offering of the course answers with the empty shape, never
    # a silent fall-back to another term. `semester` without `course_id` is
    # ignored (the notetaker UI itself carries no semester context — the
    # param exists for API completeness).
    offering_id: str | list[str] | None = None
    if course_id:
        if semester:
            term_id = await asyncio.to_thread(term_id_for_label, semester)
            offering_id = (
                await asyncio.to_thread(resolve_offering, course_id, term_id, fallback=False)
                if term_id
                else None
            ) or []
        else:
            offering_id = await asyncio.to_thread(_course_offering_ids, user_id, course_id)
    notes = (
        []
        if offering_id == []
        else await list_notes(user_id=user_id, offering_id=offering_id)
    )
    # Attach the abstract course id + labels resolved from each note's offering.
    # The notetaker UI keys on course_id; without it every note shows "Unknown
    # course" (finding F4). Shared per-request memo so notes in the same course
    # resolve the courses row once.
    meta_cache: dict = {}
    for n in notes:
        n.update(await _course_meta(n.get("offering_id"), meta_cache))
    # ETag from each note's (id, updated_at) — any create/edit/delete changes the
    # set or bumps updated_at. A matching If-None-Match returns 304 and skips
    # re-serializing the (already-decrypted) note list.
    etag = make_etag(
        "notes", user_id, ",".join(offering_id) if isinstance(offering_id, list) else offering_id or "",
        *sorted(f"{n.get('id')}:{n.get('updated_at')}" for n in notes),
    )
    not_modified = conditional(request, etag)
    if not_modified is not None:
        return not_modified
    return cached_json({"notes": notes}, etag)


@router.post("")
async def create(body: CreateNoteBody, request: Request):
    await guard_off_loop(require_self, body.user_id, request)
    # #115: only under a course the student is enrolled in (else 404). The
    # gate returns the offering the note is stored against: the student's own
    # enrollment in the abstract course — the current term's when they hold
    # it, else their latest term's — so the check and the write agree.
    # CREATE path: deliberately NOT semester-scoped (#141).
    offering_id = await asyncio.to_thread(
        require_course_enrollment, body.user_id, body.course_id,
    )
    note = await create_note(
        user_id=body.user_id,
        offering_id=offering_id,
        title=body.title,
        body=body.body,
        tags=body.tags,
    )
    # Same F4 enrichment as the read paths so a freshly created note carries its
    # abstract course_id + labels (else it shows "Unknown course" until reload).
    note.update(await _course_meta(note.get("offering_id") or offering_id, {}))
    # create_note (services/notes_service.py) inserts a single notes row per
    # call and this route calls it exactly once — award immediately after it
    # returns, keyed on the freshly-created note id so a client retry is an
    # idempotent no-op rather than a second payout.
    award_xp_safe(
        body.user_id, "note_created",
        source_type="note", source_id=note["id"],
    )
    # #117: ids + a boolean only — never the (encrypted-at-rest) title/body.
    events_service.log_event(
        "note.created",
        category="usage",
        user_id=body.user_id,
        payload={
            "note_id": note.get("id"),
            "course_id": body.course_id,
            "offering_id": offering_id,
            "has_body": bool(body.body),
        },
    )
    return note


@router.get("/{note_id}")
async def read(note_id: str, request: Request, user_id: str):
    await guard_off_loop(require_self, user_id, request)
    note = await get_note(note_id=note_id, user_id=user_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found.")
    # Same offering → course_id/label enrichment as the list route (F4), so a
    # single-note read returns a consistent shape.
    note.update(await _course_meta(note.get("offering_id"), {}))
    return note


@router.patch("/{note_id}")
async def patch(note_id: str, body: UpdateNoteBody, request: Request):
    await guard_off_loop(require_self, body.user_id, request)
    patch_dict: dict = {}
    if body.title is not None:
        patch_dict["title"] = body.title
    if body.body is not None:
        patch_dict["body"] = body.body
    if body.tags is not None:
        patch_dict["tags"] = body.tags
    if body.course_id is not None:
        # RE-HOME path: moving a note onto another abstract course passes the
        # same #115 gate as create (404 unless enrolled) and files it under
        # the offering the gate returns — not semester-scoped (#141).
        patch_dict["offering_id"] = await asyncio.to_thread(
            require_course_enrollment, body.user_id, body.course_id,
        )
    if not patch_dict:
        raise HTTPException(status_code=400, detail="No fields to update.")
    updated = await update_note(
        note_id=note_id, user_id=body.user_id, patch=patch_dict
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Note not found.")
    return updated


@router.delete("/{note_id}")
async def remove(note_id: str, request: Request, user_id: str):
    await guard_off_loop(require_self, user_id, request)
    await delete_note(note_id=note_id, user_id=user_id)
    return {"deleted": True}


class LinkConceptBody(BaseModel):
    user_id: str
    concept_node_id: str


@router.get("/{note_id}/concepts")
async def list_concepts(note_id: str, request: Request, user_id: str):
    await guard_off_loop(require_self, user_id, request)
    concepts = await list_linked_concepts(note_id=note_id, user_id=user_id)
    return {"concepts": concepts}


@router.post("/{note_id}/concepts")
async def link_concept_route(
    note_id: str, body: LinkConceptBody, request: Request
):
    await guard_off_loop(require_self, body.user_id, request)
    ok = await link_concept(
        note_id=note_id,
        user_id=body.user_id,
        concept_node_id=body.concept_node_id,
    )
    # One 404 for an unowned note, an unowned node, and a node that does not
    # exist or vanished mid-request (#115: no existence oracle).
    if not ok:
        raise HTTPException(status_code=404, detail="Note not found.")
    return {"linked": True}


@router.delete("/{note_id}/concepts/{concept_node_id}")
async def unlink_concept_route(
    note_id: str,
    concept_node_id: str,
    request: Request,
    user_id: str,
):
    await guard_off_loop(require_self, user_id, request)
    ok = await unlink_concept(
        note_id=note_id, user_id=user_id, concept_node_id=concept_node_id
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Note not found.")
    return {"unlinked": True}


class AgentActionBody(BaseModel):
    user_id: str


async def _lookup_concept_nodes_by_name(
    user_id: str, course_id: str | None, names: list[str]
) -> list[dict]:
    """Find graph_nodes for the freshly-merged concepts so we can link
    them to the note. Case-sensitive equality match — apply_graph_update
    normalizes on insert, so the names we get back from the agent should
    round-trip; if a node is missing here it means the merge skipped a
    duplicate, which is fine to silently drop."""
    import asyncio as _asyncio
    if not names:
        return []
    in_clause = "in.(" + ",".join(names) + ")"
    filters = {"user_id": f"eq.{user_id}", "concept_name": in_clause}
    if course_id:
        filters["course_id"] = f"eq.{course_id}"

    def _fetch() -> list[dict]:
        return table("graph_nodes").select(
            "id,concept_name", filters=filters
        ) or []
    return await _asyncio.to_thread(_fetch)


def _note_user_prompt(note: dict) -> str:
    """Assemble the note-worker user prompt (#150-hardened).

    Title and body are student-authored: the body ships inside the
    untrusted envelope, the title gets delimiter neutralization. Assembly-
    boundary only — the note row keeps its raw text.
    """
    from services.prompt_safety import neutralize_delimiters, wrap_untrusted

    title = neutralize_delimiters(note.get("title") or "(untitled)")
    body_text = wrap_untrusted(
        note.get("body") or "", source="student note body"
    ) or "(empty)"
    return f"Title: {title}\n\nBody:\n{body_text}"


async def _integrity_guard(
    user_id: str, surface: str, texts: Iterable[str | None]
) -> integrity_guard.Guard:
    """Spec §13 A125: the request's integrity guard (services/note_guard.py).
    Off with the loop (the kill switch; the gate is read here, at route entry,
    once)."""
    return await open_note_guard(
        user_id, surface, texts, active=learning_loop_for_request(user_id)
    )


def _deps_for(user_id: str, course_id: str | None, note_id: str | None) -> SaplingDeps:
    from db.connection import _client  # type: ignore  # only for opaque pass-through
    return SaplingDeps(
        user_id=user_id,
        course_id=course_id,
        supabase=_client,
        request_id=current_request_id() or "",
        session_id=note_id,
    )


@router.post("/{note_id}/summarize")
async def summarize(note_id: str, body: AgentActionBody, request: Request):
    await guard_off_loop(require_self, body.user_id, request)
    note = await get_note(note_id=note_id, user_id=body.user_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found.")
    # docs/safety/crisis-support.md: no summary is generated or saved; the crisis
    # screen runs BEFORE the A125 guard (services/note_guard.py says why).
    if crisis := await crisis_support.screen_async(body.user_id, "note_summarize", *note_texts(note)):
        return crisis_support.json_body(crisis)
    # spec §13 A125: a note holding one of the student's posed checks is never
    # handed to the model; a summary stating one's key is never saved or served
    guard = await _integrity_guard(
        body.user_id, "note_summary", (note.get("title"), note.get("body"))
    )
    if guard.refused:
        raise HTTPException(status_code=409, detail=integrity_guard.REFUSED_DETAIL)
    user_prompt = _note_user_prompt(note)
    # The graph keys on the abstract course; the note carries the offering.
    course_id = offering_course_id(note.get("offering_id"))
    deps = _deps_for(body.user_id, course_id, note_id)
    result = record_agent_usage(
        await _run_note_worker(
            note_summary_agent, user_prompt, deps, action="summarization"
        ),
        feature="notes", task="note_summary", user_id=body.user_id,
    )
    summary_text = result.output.summary
    if not await asyncio.to_thread(guard.screen, summary_text):
        raise HTTPException(status_code=409, detail=integrity_guard.WITHHELD_DETAIL)
    await save_summary(note_id=note_id, user_id=body.user_id, summary=summary_text)
    return {"summary": summary_text}


@router.post("/{note_id}/extract-concepts")
async def extract_concepts(
    note_id: str, body: AgentActionBody, request: Request
):
    await guard_off_loop(require_self, body.user_id, request)
    note = await get_note(note_id=note_id, user_id=body.user_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found.")
    # crisis support: no concepts are extracted, merged or linked (the crisis
    # screen first, then the A125 integrity guard, as in summarize)
    if crisis := await crisis_support.screen_async(
        body.user_id, "note_extract_concepts", *note_texts(note)
    ):
        return crisis_support.json_body(crisis)
    # spec §13 A125: as summarize; a concept name the note itself holds is the
    # student's own word (never scanned), any other name stating a posed
    # check's key is dropped before it is filed or returned
    guard = await _integrity_guard(
        body.user_id, "note_concepts", (note.get("title"), note.get("body"))
    )
    if guard.refused:
        raise HTTPException(status_code=409, detail=integrity_guard.REFUSED_DETAIL)
    user_prompt = _note_user_prompt(note)
    # Concepts land in the abstract-course graph; resolve offering → course.
    course_id = offering_course_id(note.get("offering_id"))
    deps = _deps_for(body.user_id, course_id, note_id)
    result = record_agent_usage(
        await _run_note_worker(
            note_concepts_agent, user_prompt, deps, action="concept extraction"
        ),
        feature="notes", task="note_concepts", user_id=body.user_id,
    )
    names = [n.strip() for n in (result.output.concepts or []) if n and n.strip()]
    keep = await asyncio.to_thread(guard.screen_each, names, own=guard.own_text)
    withheld = keep.count(False)
    names = [n for n, ok in zip(names, keep) if ok]
    await apply_concepts_to_graph(
        user_id=body.user_id, course_id=course_id, concept_names=names
    )
    nodes = await _lookup_concept_nodes_by_name(
        user_id=body.user_id, course_id=course_id, names=names
    )
    # Both sides are already proven the student's: get_note above is
    # user-scoped and the lookup filters graph_nodes by user_id, so one bulk
    # idempotent write replaces link_concept's per-node re-checks.
    linked = await link_prechecked_concepts(
        note_id=note_id, node_ids=[n["id"] for n in nodes]
    )
    out = {"concepts": names, "linked": linked}
    if withheld:
        out["withheld"] = withheld
    return out


class NoteChatBody(BaseModel):
    user_id: str
    message: str


@router.post("/{note_id}/chat")
async def note_chat(note_id: str, body: NoteChatBody, request: Request):
    await guard_off_loop(require_self, body.user_id, request)
    note = await get_note(note_id=note_id, user_id=body.user_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found.")
    # crisis support: the message, and the note the chat agent reads — its title,
    # body and tags (the crisis screen first, then the A125 integrity guard, as
    # in summarize)
    if crisis := await crisis_support.screen_async(
        body.user_id, "note_chat", *note_chat_texts(body.message, note)
    ):
        return crisis_support.json_body(crisis, degraded=False)
    # spec §13 A125: the message and the note the agent grounds in (its
    # read_active_note tool serves this very row, deps.note) are checked against
    # the student's posed items before any model call; the reply after it
    guard = await _integrity_guard(
        body.user_id, "note_chat", note_chat_texts(body.message, note)
    )
    if guard.refused:
        return {"reply": integrity_guard.REFUSED_REPLY, "degraded": False, "integrity": "refused"}
    course_id = offering_course_id(note.get("offering_id"))
    deps = _deps_for(body.user_id, course_id, note_id)
    deps.note = note
    deps.integrity = guard  # the agent's graph writes are screened too
    try:
        result = record_agent_usage(
            await note_chat_agent.run(
                body.message, deps=deps, usage_limits=ORCHESTRATOR_LIMITS
            ),
            feature="notes", task="note_chat", user_id=body.user_id,
        )
    except UsageLimitExceeded as e:
        # Only a real budget trip reaches the in-band degrade, so the budget
        # wording in _CHAT_DEGRADED_REPLY is accurate. Retrying is safe with no
        # partial-write rollback: any graph write apply_graph_update_tool made
        # before the trip is idempotent (apply_graph_update upserts nodes
        # on_conflict, and note_chat writes no mastery events or edges).
        logger.warning(
            "note_chat agent hit its usage budget; degrading in-band", exc_info=e
        )
        return {"reply": _CHAT_DEGRADED_REPLY, "degraded": True}
    except UnexpectedModelBehavior as e:
        # Not a budget signal — a genuine bug. Surface it as a 5xx (never the
        # budget reply) so alerting fires; the log carries a traceback.
        logger.exception("note_chat agent returned unexpected model behavior")
        raise HTTPException(
            status_code=500,
            detail="Something went wrong answering that.",
        ) from e
    if not await asyncio.to_thread(guard.screen, result.output):
        return {"reply": integrity_guard.WITHHELD_REPLY, "degraded": False, "integrity": "withheld"}
    return {"reply": result.output, "degraded": False}


@router.post("/{note_id}/send-to-tutor")
async def send_to_tutor(
    note_id: str, body: AgentActionBody, request: Request
):
    await guard_off_loop(require_self, body.user_id, request)
    note = await get_note(note_id=note_id, user_id=body.user_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found.")
    # crisis support: nothing is handed to the tutor (no topic, no preface)
    if crisis := await crisis_support.screen_async(
        body.user_id, "note_send_to_tutor", *note_texts(note)
    ):
        return crisis_support.json_body(crisis)
    title = (note.get("title") or "").strip() or "Untitled note"
    topic = title.splitlines()[0][:80]
    preface_parts: list[str] = []
    if note.get("last_summary"):
        preface_parts.append(f"Note summary: {note['last_summary']}")
    body_text = (note.get("body") or "").strip()
    if body_text:
        preface_parts.append(f"Note excerpt:\n{body_text[:1500]}")
    preface = "\n\n".join(preface_parts)
    return {
        "topic": topic,
        # The tutor session starts from the abstract course id (the graph key).
        "course_id": offering_course_id(note.get("offering_id")),
        "preface": preface,
    }


@router.post("/{note_id}/generate-quiz")
async def generate_quiz_from_note(
    note_id: str, body: AgentActionBody, request: Request
):
    await guard_off_loop(require_self, body.user_id, request)
    note = await get_note(note_id=note_id, user_id=body.user_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found.")
    linked = await list_linked_concepts(note_id=note_id, user_id=body.user_id)
    if not linked:
        raise HTTPException(
            status_code=400,
            detail="Link at least one concept before generating a quiz.",
        )
    # Lowest mastery wins so the quiz targets the weakest spot.
    chosen = min(linked, key=lambda c: float(c.get("mastery_score") or 0.0))
    return {
        "concept_node_id": chosen.get("id"),
        "concept_name": chosen.get("concept_name"),
    }
