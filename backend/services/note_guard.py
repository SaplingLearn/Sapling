"""The learning loop's integrity guard around the notes agent actions (spec
§13 A125): the student-written text each action hands a model, and the guard's
one read of the student's posed items (services/integrity_guard.py).

The three model-calling actions (chat, summarize, extract-concepts) run the
guard: a note or message quoting one of the student's posed checks never
reaches the model, and model text stating one's key is never served.
send-to-tutor and generate-quiz call no model: they hand the client a topic or
a concept node, and the tutor that topic opens is the loop's, whose served
turns it scans itself (A88/A93).

Before any of that, the four actions that hand note text to a model or the
tutor (chat, summarize, extract-concepts, send-to-tutor) screen it for crisis
language (docs/safety/crisis-support.md). On a match the support card is the
response: the integrity guard never opens, so a student in crisis is never
answered with an integrity refusal, and no posed-items read is made.

Moved out of routes/notes.py with the #118 layout (spec §13 A149), which keeps
every route file at 600 lines or fewer. The route still evaluates the
learning-loop gate (owner decision 00: only routes/ reads it) and maps a
refusal to its 409.
"""
from __future__ import annotations

import asyncio
from collections.abc import Iterable

from services import integrity_guard
from services.request_context import current_request_id


def note_texts(note: dict) -> tuple[str | None, ...]:
    """The student-written note text an agent action hands a model (the title
    and body; `last_summary` is model output, not the student's words)."""
    return (note.get("title"), note.get("body"))


def note_chat_texts(message: str, note: dict) -> tuple[str | None, ...]:
    """Everything student-written the note-chat agent reads: the message, the
    note's title and body, and its tags (its read_active_note tool serves them;
    A125's integrity guard checks the same four)."""
    tags = [t for t in note.get("tags") or [] if isinstance(t, str)]
    return (message, *note_texts(note), *tags)


async def open_note_guard(
    user_id: str, surface: str, texts: Iterable[str | None], *, active: bool
) -> integrity_guard.Guard:
    """Spec §13 A125: the request's integrity guard — ONE read of the student's
    posed items and the pre-call check of everything the model will read that
    the student wrote, off the event loop (the reads are DB calls). `active` is
    the route-entry gate: off with the loop (the kill switch)."""
    return await asyncio.to_thread(
        integrity_guard.open_guard,
        user_id,
        surface=surface,
        texts=list(texts),
        active=active,
        request_id=current_request_id(),
    )
