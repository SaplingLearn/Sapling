"""
backend/services/documents/notes_api.py

The handler bodies behind ``/api/documents/doc/{id}/notes`` — read (generating
on the first request), save, regenerate, and Ask Clov.

The route is the HTTP surface only (#118); everything it does lives here. The
storage boundary is ``doc_notes.py``, which owns the encryption; this owns the
two agent runs and the shape of each answer.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException

from agents import WORKER_LIMITS
from agents.deps import SaplingDeps
from agents.document_notes import document_notes_agent, document_notes_chat_agent
from agents.usage import record_agent_usage
from services.academics import offering_course_id
from services.documents import doc_notes

logger = logging.getLogger(__name__)

#: How many earlier turns Ask Clov is given. Enough to follow a thread,
#: bounded so a long chat cannot grow the prompt without limit.
_HISTORY_TURNS = 5

#: Caps on what one question may carry.
_MAX_QUOTE = 4_000
_MAX_HISTORY = 6_000


async def run_agent(agent, prompt: str, deps: SaplingDeps, *, action: str) -> str:
    """Run one of the document-notes workers under WORKER_LIMITS.

    The same split as ``routes/notes.py::_run_note_worker``: a budget trip is
    deterministic (retrying the same document fails identically) and answers
    413, while unexpected model behavior is a real bug and answers 500 with a
    traceback in the log.
    """
    from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded

    try:
        result = await agent.run(prompt, deps=deps, usage_limits=WORKER_LIMITS)
    except UsageLimitExceeded as e:
        logger.warning("document notes %s hit its usage budget", action, exc_info=e)
        raise HTTPException(
            status_code=413,
            detail=(
                f"This document is too long to {action} automatically. "
                "Try a shorter document."
            ),
        ) from e
    except UnexpectedModelBehavior as e:
        logger.exception("document notes %s returned unexpected model behavior", action)
        raise HTTPException(
            status_code=500,
            detail="Something went wrong generating these notes.",
        ) from e
    record_agent_usage(result, feature="document_notes", user_id=deps.user_id)
    return str(result.output or "")


async def load_document(document_id: str, user_id: str) -> dict:
    """The document a notes request is about, with its source text and the
    abstract course id the agents are given as context."""
    text, doc = await doc_notes.source_text(document_id, user_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    doc["_source_text"] = text
    doc["course_id"] = (
        await asyncio.to_thread(offering_course_id, doc.get("offering_id"))
        if doc.get("offering_id") else None
    )
    return doc


def _deps(user_id: str, doc: dict, request_id: str, feature: str) -> SaplingDeps:
    return SaplingDeps(
        user_id=user_id,
        course_id=doc.get("course_id"),
        supabase=None,
        request_id=request_id,
        feature=feature,
    )


async def generate(doc: dict, user_id: str, request_id: str) -> str:
    """The notes body for a document: the model's, or an honest fallback.

    A document with nothing readable in it is NOT an error the page should
    show — the editor is perfectly usable empty, and the student can write
    their own or regenerate. Only the two guardrail failures in `run_agent`
    surface as HTTP errors.
    """
    text = doc.get("_source_text") or ""
    if not text.strip():
        return doc_notes.fallback_notes(doc)

    prompt = (
        f"Document title: {doc.get('file_name') or 'Untitled'}\n"
        f"Document type: {doc.get('category') or 'other'}\n\n"
        'Document text:\n"""\n' + text + '\n"""\n'
    )
    html = await run_agent(
        document_notes_agent, prompt, _deps(user_id, doc, request_id, "document_notes"),
        action="draft notes for",
    )
    return doc_notes.clean_generated(html) or doc_notes.fallback_notes(doc)


async def read(document_id: str, user_id: str, request_id: str) -> dict:
    """The notes for a document, generated on the first read.

    Generation happens once: the generated body is stored straight away, so a
    reload — or a second tab — gets the same document rather than a second
    draft, and every edit after that is the student's.
    """
    stored = await doc_notes.get_notes(document_id, user_id)
    if stored and (stored.get("content") or "").strip():
        return stored

    doc = await load_document(document_id, user_id)
    content = await generate(doc, user_id, request_id)
    return await doc_notes.save_notes(
        document_id, user_id,
        title=(stored or {}).get("title") or doc.get("file_name") or "Notes",
        content=content,
    )


async def save(document_id: str, user_id: str, body: dict) -> dict:
    """Save the notes. The editor autosaves on a debounce, so this is called
    often and writes only the fields it is given — an autosaved body must not
    clear the title, and Finalize must not clear the body."""
    content = body.get("content")
    if content is not None and len(content) > doc_notes.MAX_CONTENT:
        raise HTTPException(
            status_code=413,
            detail="These notes are too long to save. Try removing some blocks.",
        )
    return await doc_notes.save_notes(
        document_id, user_id,
        title=body.get("title"),
        content=content,
        final=body.get("final"),
    )


async def regenerate(document_id: str, user_id: str, request_id: str) -> dict:
    """Rebuild the notes from the source document, replacing the student's
    edits. The page asks for confirmation before calling this."""
    doc = await load_document(document_id, user_id)
    content = await generate(doc, user_id, request_id)
    return await doc_notes.save_notes(
        document_id, user_id,
        title=doc.get("file_name") or "Notes",
        content=content,
        final=False,
    )


async def ask(document_id: str, user_id: str, body: dict, request_id: str) -> dict:
    """Clov, the notes sidecar: one question about the notes on screen.

    The client sends the notes text it is actually showing — the student may
    have unsaved edits — along with the recent turns and the passage they
    selected.
    """
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Ask Clov a question first.")

    doc = await load_document(document_id, user_id)
    notes_text = (body.get("notes") or "")[:doc_notes.MAX_SOURCE_CHARS]
    quote = (body.get("quote") or "")[:_MAX_QUOTE]
    history = body.get("history") or []
    turns = "\n".join(
        f"{'Student' if h.get('role') == 'user' else 'Tutor'}: {h.get('text') or ''}"
        for h in history[-_HISTORY_TURNS:] if isinstance(h, dict)
    )[:_MAX_HISTORY]

    prompt = (
        f'The student is working in their notes document '
        f'"{doc.get("file_name") or "Untitled"}".\n\n'
        'Their current notes:\n"""\n' + notes_text + '\n"""\n'
        + (f"\nEarlier in this chat:\n{turns}\n" if turns else "")
        + (f'\nThe student selected this passage from their notes:\n"{quote}"\n' if quote else "")
        + f"\nStudent: {message}"
    )
    reply = await run_agent(
        document_notes_chat_agent, prompt,
        _deps(user_id, doc, request_id, "document_notes_chat"),
        action="answer about",
    )
    return {"reply": reply.strip()}
