"""Agents for the editable per-document notes page (`/library/{id}/notes`).

Two single-shot, tool-less agents:

* ``document_notes_agent`` turns an uploaded document's extracted text into
  the notes body the editor opens with — an HTML fragment using exactly the
  tags and block markup the editor understands.
* ``document_notes_chat_agent`` is Clov, the sidecar that answers questions
  about the notes the student is looking at.

Both have their own model slots (``document_notes`` / ``document_notes_chat``)
carrying the same model and effort as the notetaker's. They cannot SHARE the
notetaker's slots: the function-mode seam keys its handler on the slot, and
``note_summary``'s handler answers with a schema, where these two answer in
free text — a str-output agent handed a structured handler raises before it
returns anything (verified 2026-11-23).
"""
from __future__ import annotations

import hashlib

from pydantic_ai import Agent

from agents._providers import model_for
from agents.deps import SaplingDeps
from services.prompt_safety import INJECTION_GUARD_PROMPT


#: The exact block markup the editor round-trips. Kept in one string so the
#: generation prompt and the editor's own `BLK` helpers cannot drift apart
#: silently — frontend/src/lib/notes/blocks.ts builds the same shapes.
_BLOCK_GUIDE = (
    "Use only these tags: <h2>, <h3>, <p>, <ul>, <ol>, <li>, <strong>, <em>, "
    "<pre>, <blockquote>, <hr>.\n"
    "For a display equation use:\n"
    '  <div class="math" contenteditable="false" data-tex="LATEX"></div>\n'
    "For an inline equation inside a paragraph use:\n"
    '  <span class="imath" contenteditable="false" data-tex="LATEX"></span>\n'
    "For a table use:\n"
    '  <div class="blk" data-blk="table" data-edit="0">'
    '<table><thead><tr><th>…</th></tr></thead>'
    "<tbody><tr><td>…</td></tr></tbody></table></div>\n"
    "For a collapsible worked example use:\n"
    '  <div class="blk" data-blk="toggle" data-open="1">'
    '<div class="tg-head"><div class="tg-title">TITLE</div></div>'
    '<div class="tg-body"><p>BODY</p></div></div>\n'
    "For a practice question with a hidden answer use:\n"
    '  <div class="blk" data-blk="qa" data-open="0">'
    '<div class="qa-q">QUESTION</div><div class="qa-a">ANSWER</div></div>\n'
    "For a review checklist use:\n"
    '  <ul class="check"><li data-done="0">'
    '<span class="box" contenteditable="false" data-act="check">✓</span>'
    "<span>ITEM</span></li></ul>\n"
    # The `.box` span IS the checkbox: `library-notes.css` styles
    # `ul.check li > .box`, and `data-act="check"` is what the editor's click
    # handler looks for. A checklist written without it renders as plain text
    # and cannot be ticked.
)

_NOTES_PROMPT = (
    "You write a student's study notes for one uploaded course document.\n\n"
    "Produce an HTML fragment — no <html>, <head>, <body>, no document title "
    "(<h1>), no markdown fences, no commentary before or after. The page "
    "supplies the title itself.\n\n"
    "Shape the notes as the student would want to revise from: an opening "
    "paragraph that says what the document covers, then numbered <h2> "
    "sections that follow the document's own order, each with short "
    "paragraphs or lists. Include at least one practice question block and "
    "end with a <h2>Questions to Review</h2> checklist. Add a table when the "
    "document compares things, an equation block when it states a formula, "
    "and a toggle when it works an example through.\n\n"
    "Headings are Title Case. Be faithful: every claim must come from the "
    "document. Never invent a fact, a number or a citation. If the document "
    "is too short or unreadable to summarize, say so in one paragraph "
    "instead of padding.\n\n"
    + _BLOCK_GUIDE
    + "\n"
    # #150: the document text is untrusted student-supplied content.
    + INJECTION_GUARD_PROMPT
)
_NOTES_HASH = hashlib.sha256(_NOTES_PROMPT.encode("utf-8")).hexdigest()[:12]

document_notes_agent = Agent[SaplingDeps, str](
    model=model_for("document_notes"),
    deps_type=SaplingDeps,
    output_type=str,
    # No `retries=`: a free-text agent has no output schema to validate
    # against, so a retry budget would only be a hidden re-roll (#153). A
    # generation that comes back unusable falls back instead — see
    # `services/documents/doc_notes.py::fallback_notes`.
    system_prompt=_NOTES_PROMPT,
    metadata={"prompt_version": _NOTES_HASH, "agent": "document_notes"},
)


_CHAT_PROMPT = (
    "You are Clov, Sapling's study tutor, answering inside the notes the "
    "student is reading. You are given the notes text, the recent chat, and "
    "sometimes a passage the student selected.\n\n"
    "Reply in plain text, under 140 words. No markdown symbols — no #, no **, "
    "no bullet characters. Be concrete and specific to what the notes "
    "actually say.\n\n"
    "If the student asks how to edit or improve the notes, give the exact "
    "sentence or bullet they should add or change. If the student asks you to "
    "rewrite a passage, reply with only the rewritten text — no preamble.\n\n"
    # #150: the notes and the quoted passage are untrusted student content.
    + INJECTION_GUARD_PROMPT
)
_CHAT_HASH = hashlib.sha256(_CHAT_PROMPT.encode("utf-8")).hexdigest()[:12]

document_notes_chat_agent = Agent[SaplingDeps, str](
    model=model_for("document_notes_chat"),
    deps_type=SaplingDeps,
    output_type=str,
    system_prompt=_CHAT_PROMPT,
    metadata={"prompt_version": _CHAT_HASH, "agent": "document_notes_chat"},
)
