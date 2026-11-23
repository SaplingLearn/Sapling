"""HTTP routes for the notetaker.

CRUD lives here; agent-backed actions (summarize, extract concepts, chat,
generate quiz, send to tutor) come in Phase 4 below.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

import httpx

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from typing import Annotated, Literal

from pydantic import BaseModel, Field
from starlette.responses import Response
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded

from agents import ORCHESTRATOR_LIMITS, WORKER_LIMITS
from agents.deps import SaplingDeps
from agents.note_chat import note_chat_agent
from agents.note_concepts import note_concepts_agent
from agents.note_summary import note_summary_agent
from agents.tools.graph import apply_concepts_to_graph
from agents.usage import record_agent_usage
from db.connection import pg_quote_value, table
from models import CHAT_MESSAGE_MAX, Id
from services import crisis_support, events_service
from services.academics import (
    course_offering_ids, offering_course_id, require_course_enrollment, resolve_offering,
    term_id_for_label, user_offering_ids_for_course,
)
from services.auth_guard import get_session_user_id, require_self, guard_off_loop
from services import abuse_limits
from services.request_limits import aenforce_abuse_limit, read_within_limit
from services import note_originals
from services.extraction_service import extract_text_from_file
from services.upload_validation import DOCX, PDF, matching_type
from services.prompt_safety import wrap_untrusted
from services.notes_service import (
    create_note,
    delete_note,
    get_note,
    link_concept,
    link_prechecked_concepts,
    list_linked_concepts,
    list_notes,
    save_summary,
    tutor_topic,
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


def _provider_unavailable(exc: ModelHTTPError, action: str) -> HTTPException:
    logger.warning(
        "Note AI provider rejected %s: model=%s status=%s",
        action, exc.model_name, exc.status_code,
    )
    return HTTPException(status_code=503, detail="Clov is unavailable. Try again later.")


async def _run_note_worker(agent, user_prompt: str, deps: SaplingDeps, *, action: str):
    """Run a single-shot note worker under WORKER_LIMITS (#329).

    The two guardrail failure modes are distinct and must not be conflated:
    a budget trip is deterministic (retrying the same note fails identically),
    while unexpected model behavior is a genuine bug that must page us.
    """
    try:
        return await agent.run(user_prompt, deps=deps, usage_limits=WORKER_LIMITS)
    except ModelHTTPError as exc:
        raise _provider_unavailable(exc, action) from None
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


#: Note bounds (the notetaker's inputs carry the same maxLength). A note body is
#: plain text; 200k characters is a ~100-page set of lecture notes.
NOTE_TITLE_MAX = 300
NOTE_BODY_MAX = 200_000
NOTE_TAG_MAX = 64
NOTE_TAGS_MAX = 50
NoteTag = Annotated[str, Field(max_length=NOTE_TAG_MAX)]


class CreateNoteBody(BaseModel):
    user_id: Id
    course_id: Id
    title: str = Field(default="", max_length=NOTE_TITLE_MAX)
    body: str = Field(default="", max_length=NOTE_BODY_MAX)
    tags: list[NoteTag] = Field(default_factory=list, max_length=NOTE_TAGS_MAX)


class UpdateNoteBody(BaseModel):
    user_id: Id
    title: str | None = Field(default=None, max_length=NOTE_TITLE_MAX)
    body: str | None = Field(default=None, max_length=NOTE_BODY_MAX)
    tags: list[NoteTag] | None = Field(default=None, max_length=NOTE_TAGS_MAX)
    course_id: Id | None = None


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


@router.post("/import", status_code=201)
async def import_document(
    request: Request,
    user_id: Annotated[Id, Form()],
    course_id: Annotated[Id, Form()],
    file: Annotated[UploadFile, File()],
):
    await guard_off_loop(require_self, user_id, request)
    await aenforce_abuse_limit(abuse_limits.DOCUMENT_UPLOAD, user_id)
    offering_id = await asyncio.to_thread(require_course_enrollment, user_id, course_id)
    filename = (file.filename or "").replace(chr(92), "/").rsplit("/", 1)[-1].strip()
    if not filename or len(filename) > NOTE_TITLE_MAX or any(ord(char) < 32 for char in filename):
        raise HTTPException(status_code=422, detail="Choose a file with a valid filename.")
    contents = await read_within_limit(file, note_originals.MAX_IMPORT_BYTES)
    content_type = matching_type(filename, contents, {PDF, DOCX})
    if not content_type:
        raise HTTPException(status_code=415, detail="Choose a valid PDF or Word (.docx) file.")
    try:
        extracted = await asyncio.to_thread(extract_text_from_file, contents, filename, content_type)
    except Exception as exc:
        logger.warning("Editable document extraction failed", exc_info=True)
        raise HTTPException(status_code=422, detail="Couldn't read this PDF or Word document.") from exc
    text = (extracted or "").replace(chr(0), "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="No readable text was found in this document.")
    # The browser's textarea limit counts UTF-16 code units.
    if len(text.encode("utf-16-le")) // 2 > NOTE_BODY_MAX:
        raise HTTPException(status_code=413, detail="This document has too much text for one editable copy.")

    note_id = str(uuid.uuid4())
    stored = False
    try:
        size = await asyncio.to_thread(note_originals.store_original, user_id, note_id, contents)
        stored = True
        note = await create_note(
            user_id=user_id, offering_id=offering_id, title=filename, body=text,
            note_id=note_id, original=(filename, content_type, size),
        )
    except httpx.HTTPError as exc:
        # The insert can commit even if its response is lost. Check ownership
        # before removing the object in that case.
        note = None
        if stored and (not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code >= 500):
            try:
                note = await get_note(note_id=note_id, user_id=user_id)
            except httpx.HTTPError as lookup_error:
                logger.exception("Could not confirm imported note %s", note_id)
                raise HTTPException(status_code=502, detail="Check your Library before retrying.") from lookup_error
        if note is None:
            try:
                await asyncio.to_thread(note_originals.remove_originals, user_id, [note_id])
            except (httpx.HTTPError, RuntimeError):
                logger.exception("Could not clean up failed note original %s", note_id)
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 413:
                raise HTTPException(status_code=413, detail="Original file storage quota reached.") from exc
            raise HTTPException(status_code=502, detail="Couldn't save the imported document. Try again.") from exc
    note.update(await _course_meta(offering_id, {}))
    return note


@router.get("/{note_id}/original", response_class=Response)
async def original_document(note_id: str, request: Request):
    user_id = await guard_off_loop(get_session_user_id, request)
    await aenforce_abuse_limit(abuse_limits.NOTE_LOOKUP, user_id)
    note = await get_note(note_id=note_id, user_id=user_id)
    if not note or not note.get("original_filename"):
        raise HTTPException(status_code=404, detail="Original file not found.")
    try:
        return await asyncio.to_thread(note_originals.download_original, note)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Couldn't download the original file. Try again.") from exc


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
    note = await get_note(note_id=note_id, user_id=user_id)
    if note and note.get("original_filename"):
        try:
            await asyncio.to_thread(note_originals.remove_originals, user_id, [note_id])
        except (httpx.HTTPError, RuntimeError) as exc:
            raise HTTPException(status_code=502, detail="Couldn't remove the original file. Try again.") from exc
    await delete_note(note_id=note_id, user_id=user_id)
    return {"deleted": True}


class LinkConceptBody(BaseModel):
    user_id: Id
    concept_node_id: Id


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
    user_id: Id


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
    in_clause = "in.(" + ",".join(pg_quote_value(name) for name in names) + ")"
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


def _note_texts(note: dict) -> tuple[str | None, ...]:
    """The student-written note text an agent action hands a model (the title
    and body; `last_summary` is model output, not the student's words),
    screened in full (a quotation like the rest). A match never blocks the
    action: `crisis_support.alongside` shows the card beside its answer."""
    return (note.get("title"), note.get("body"))


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
    # docs/safety/crisis-support.md: the note never blocks; a match shows the card alongside
    screen = await crisis_support.screen_content_async(request, body.user_id, "note_summarize", *_note_texts(note))

    async def action() -> dict:
        await aenforce_abuse_limit(abuse_limits.NOTE_AI_ACTION, body.user_id)
        user_prompt = _note_user_prompt(note)
        # The graph keys on the abstract course; the note carries the offering.
        course_id = offering_course_id(note.get("offering_id"))
        deps = _deps_for(body.user_id, course_id, note_id)
        result = record_agent_usage(
            await _run_note_worker(note_summary_agent, user_prompt, deps, action="summarization"),
            feature="notes", task="note_summary", user_id=body.user_id,
        )
        summary_text = result.output.summary
        await save_summary(note_id=note_id, user_id=body.user_id, summary=summary_text)
        return {"summary": summary_text}

    return await crisis_support.alongside(screen, action())


@router.post("/{note_id}/extract-concepts")
async def extract_concepts(
    note_id: str, body: AgentActionBody, request: Request
):
    await guard_off_loop(require_self, body.user_id, request)
    note = await get_note(note_id=note_id, user_id=body.user_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found.")
    # docs/safety/crisis-support.md: the note never blocks; a match shows the card alongside
    screen = await crisis_support.screen_content_async(
        request, body.user_id, "note_extract_concepts", *_note_texts(note)
    )

    return await crisis_support.alongside(
        screen, _extract_and_link_note_concepts(note, note_id, body.user_id)
    )


async def _extract_and_link_note_concepts(note: dict, note_id: str, user_id: str) -> dict:
    await aenforce_abuse_limit(abuse_limits.NOTE_AI_ACTION, user_id)
    user_prompt = _note_user_prompt(note)
    # Concepts land in the abstract-course graph; resolve offering → course.
    course_id = offering_course_id(note.get("offering_id"))
    deps = _deps_for(user_id, course_id, note_id)
    result = record_agent_usage(
        await _run_note_worker(note_concepts_agent, user_prompt, deps, action="concept extraction"),
        feature="notes", task="note_concepts", user_id=user_id,
    )
    names = [n.strip() for n in (result.output.concepts or []) if n and n.strip()]
    await apply_concepts_to_graph(user_id=user_id, course_id=course_id, concept_names=names)
    nodes = await _lookup_concept_nodes_by_name(user_id=user_id, course_id=course_id, names=names)
    # Both sides are already proven the student's: get_note above is
    # user-scoped and the lookup filters graph_nodes by user_id, so one bulk
    # idempotent write replaces link_concept's per-node re-checks.
    linked = await link_prechecked_concepts(note_id=note_id, node_ids=[n["id"] for n in nodes])
    return {"concepts": names, "linked": linked}


class NoteChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=2000)


class NoteChatBody(BaseModel):
    user_id: Id
    message: str = Field(max_length=CHAT_MESSAGE_MAX)
    history: list[NoteChatTurn] = Field(default_factory=list, max_length=6)
    rewrite_selection: str | None = Field(default=None, max_length=4000)


@router.post("/{note_id}/chat")
async def note_chat(note_id: str, body: NoteChatBody, request: Request):
    # docs/safety/crisis-support.md: the typed message blocks, before every limit and budget
    if crisis := await crisis_support.screen_async(request, body.user_id, "note_chat", body.message):
        return crisis_support.json_body(crisis, degraded=False)
    await guard_off_loop(require_self, body.user_id, request)
    note = await get_note(note_id=note_id, user_id=body.user_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found.")
    if body.rewrite_selection and body.rewrite_selection not in (note.get("body") or ""):
        raise HTTPException(status_code=409, detail="The document changed. Select the passage again.")
    # ...the note the chat agent reads never blocks: a match shows the card alongside
    # Re-read every turn: the card goes beside each answer, the event once a
    # day per note version.
    screen = await crisis_support.screen_content_async(
        request, body.user_id, "note_chat", *_note_texts(note),
        once_a_day=(note_id, note.get("updated_at")),
    )

    async def action() -> dict:
        await aenforce_abuse_limit(abuse_limits.NOTE_AI_ACTION, body.user_id)
        course_id = offering_course_id(note.get("offering_id"))
        deps = _deps_for(body.user_id, course_id, note_id)
        # M7: a concept the chat adds must come from the message or the note
        # (the agent's read tools add what they return).
        deps.concept_context = [body.message, note.get("title") or "", note.get("body") or ""]
        prompt = body.message
        if body.rewrite_selection:
            prompt += "\n\n" + wrap_untrusted(body.rewrite_selection, source="selected document passage")
        if body.history:
            transcript = "\n".join(f"{turn.role}: {turn.text}" for turn in body.history)
            prompt = (
                wrap_untrusted(transcript, source="previous document chat turns")
                + "\n\nCurrent question:\n" + prompt
            )
        try:
            result = record_agent_usage(
                await note_chat_agent.run(prompt, deps=deps, usage_limits=ORCHESTRATOR_LIMITS),
                feature="notes", task="note_chat", user_id=body.user_id,
            )
        except ModelHTTPError as exc:
            raise _provider_unavailable(exc, "chat") from None
        except UsageLimitExceeded as e:
            # Only a real budget trip reaches the in-band degrade, so the budget
            # wording in _CHAT_DEGRADED_REPLY is accurate. Retrying is safe with no
            # partial-write rollback: any graph write apply_graph_update_tool made
            # before the trip is idempotent (apply_graph_update upserts nodes
            # on_conflict, and note_chat writes no mastery events or edges).
            logger.warning("note_chat agent hit its usage budget; degrading in-band", exc_info=e)
            return {"reply": _CHAT_DEGRADED_REPLY, "degraded": True}
        except UnexpectedModelBehavior as e:
            # Not a budget signal — a genuine bug. Surface it as a 5xx (never the
            # budget reply) so alerting fires; the log carries a traceback.
            logger.exception("note_chat agent returned unexpected model behavior")
            raise HTTPException(status_code=500, detail="Something went wrong answering that.") from e
        return {"reply": result.output, "degraded": False}

    return await crisis_support.alongside(screen, action())


@router.post("/{note_id}/send-to-tutor")
async def send_to_tutor(
    note_id: str, body: AgentActionBody, request: Request
):
    await guard_off_loop(require_self, body.user_id, request)
    note = await get_note(note_id=note_id, user_id=body.user_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found.")
    # docs/safety/crisis-support.md: the note never blocks; a match shows the card alongside,
    # recorded here; the /learn start it hands over records no second card for this version.
    screen = await crisis_support.screen_content_async(
        request, body.user_id, "note_send_to_tutor", *_note_texts(note),
        hands_off_note=(note_id, note.get("updated_at")),
    )

    async def action() -> dict:
        # No model runs here (the tutor session is limited where it starts),
        # so the cheap note budget, not a note-AI unit.
        await aenforce_abuse_limit(abuse_limits.NOTE_LOOKUP, body.user_id)
        preface_parts: list[str] = []
        if note.get("last_summary"):
            preface_parts.append(f"Note summary: {note['last_summary']}")
        body_text = (note.get("body") or "").strip()
        if body_text:
            preface_parts.append(f"Note excerpt:\n{body_text[:1500]}")
        return {
            "topic": tutor_topic(note),
            # The tutor session starts from the abstract course id (the graph key).
            "course_id": offering_course_id(note.get("offering_id")),
            "preface": "\n\n".join(preface_parts),
        }

    return await crisis_support.alongside(screen, action())


@router.post("/{note_id}/generate-quiz")
async def generate_quiz_from_note(
    note_id: str, body: AgentActionBody, request: Request
):
    await guard_off_loop(require_self, body.user_id, request)
    await aenforce_abuse_limit(abuse_limits.NOTE_LOOKUP, body.user_id)
    note = await get_note(note_id=note_id, user_id=body.user_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found.")
    linked = await list_linked_concepts(note_id=note_id, user_id=body.user_id)
    if linked:
        return _quiz_concept(linked)
    if not (note.get("body") or "").strip():
        raise HTTPException(status_code=400, detail="Write something in this note to generate a quiz.")

    screen = await crisis_support.screen_content_async(
        request, body.user_id, "note_extract_concepts", *_note_texts(note)
    )

    async def action() -> dict:
        await _extract_and_link_note_concepts(note, note_id, body.user_id)
        concepts = await list_linked_concepts(note_id=note_id, user_id=body.user_id)
        if not concepts:
            raise HTTPException(status_code=422, detail="Add more detail to find a concept for this quiz.")
        return _quiz_concept(concepts)

    return await crisis_support.alongside(screen, action())


def _quiz_concept(linked: list[dict]) -> dict:
    chosen = min(linked, key=lambda concept: float(concept.get("mastery_score") or 0.0))
    return {
        "concept_node_id": chosen["id"],
        "concept_name": chosen["concept_name"],
    }
