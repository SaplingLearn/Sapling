"""The documents a study guide is made from: the class's materials, the set
suggested for a scope, their text for the prompt, and what arrived since.

Only the student's own ``documents`` rows are read, never the shared
``course_chunks`` pool, so a classmate's material cannot reach a guide.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from db.connection import pg_quote_value, table
from models.study_guide import MaterialOption, Source
from services.encryption import decrypt, decrypt_json_column
from services.study_guides.scopes import MAX_ID_CHARS, Scope

logger = logging.getLogger(__name__)

#: The source budget, as the topic outline reads the same columns
#: (`services/topic_checklist_service.py`).
MAX_SOURCES = 30
MAX_SOURCE_CHARS = 10_000
MAX_TOTAL_CHARS = 60_000

SYLLABUS = "syllabus"
LECTURE_CATEGORIES = ("lecture_notes", "slides")


@dataclass(frozen=True)
class SourceText:
    """One document as the prompt reads it. ``text`` is not wrapped: the
    prompt builder wraps it as untrusted."""

    label: str
    source: Source
    concepts: list[str]
    text: str


def _live(user_id: str, **more: str) -> dict:
    """Filters for the student's own documents that are not deleted."""
    return {"user_id": f"eq.{user_id}", "deleted_at": "is.null", **more}


# ── The class's materials and the suggested set ───────────────────────────────


async def alist_materials(user_id: str, offering_id: str) -> list[MaterialOption]:
    """The student's live documents in the class, oldest first so lectures
    read in the order they were given."""
    rows = await table("documents").aselect(
        "id,file_name,category,created_at",
        filters=_live(user_id, offering_id=f"eq.{offering_id}"),
        order="created_at.asc,id.asc",
    ) or []
    return [
        MaterialOption(
            id=row["id"], file_name=row["file_name"],
            category=row["category"], created_at=row["created_at"],
        )
        for row in rows
    ]


def _day(stamp: str) -> str:
    """``YYYY-MM-DD`` of a date or a UTC timestamp. ISO days compare as text."""
    return stamp[:10]


def _since_last_exam(
    materials: list[MaterialOption], scope: Scope, scopes: list[Scope],
) -> list[MaterialOption]:
    """Materials uploaded after the exam before this scope, up to its date."""
    due = _day(scope.due_date)
    earlier = [
        _day(s.due_date) for s in scopes
        if s.kind == "exam" and s.due_date and _day(s.due_date) < due
    ]
    start = max(earlier, default="")
    return [m for m in materials if start < _day(m.created_at) <= due]


def suggest_materials(
    materials: list[MaterialOption], scope: Scope, scopes: list[Scope],
) -> list[str]:
    """The material ids pre-selected for a scope.

    The whole course takes everything. An exam or assignment takes what was
    uploaded since the exam before it, up to its own date, and never the
    syllabus. With no date, or nothing in that window, it takes every
    material but the syllabus. Past the `MAX_SOURCES` a guide reads, the
    newest are suggested: the oldest material is the one left out, as the
    source budget leaves it out (`_arows`).
    """
    if scope.kind == "course":
        chosen = materials
    else:
        usable = [m for m in materials if m.category != SYLLABUS]
        chosen = (_since_last_exam(usable, scope, scopes) if scope.due_date else []) or usable
    return [m.id for m in chosen][-MAX_SOURCES:]


# ── Source text for the prompt ────────────────────────────────────────────────


async def _arows(
    user_id: str, offering_id: str, material_ids: list[str], columns: str,
) -> list[dict]:
    """The chosen documents, oldest first. An id that is not the student's,
    not in the class or deleted matches nothing and is left out.

    Past the budget the last ids given are the ones read. Callers give them
    oldest first, with the lectures new to a guide at the end, so it is the
    oldest material that is left out and never the new."""
    known = [i for i in dict.fromkeys(material_ids) if len(i) <= MAX_ID_CHARS]
    ids = known[-MAX_SOURCES:]
    if not ids:
        return []
    return await table("documents").aselect(
        columns,
        filters=_live(
            user_id,
            offering_id=f"eq.{offering_id}",
            id=f"in.({','.join(pg_quote_value(i) for i in ids)})",
        ),
        order="created_at.asc,id.asc",
    ) or []


def _column(row: dict, column: str, read: Callable[[Any], Any]) -> Any:
    """``read`` of one column of a document, or None when it is empty or
    cannot be read (a wrong key, a damaged value, not JSON). An unreadable
    column is left out with a warning and costs the document only that
    column; its value is never used as text."""
    value = row.get(column)
    if not value:
        return None
    try:
        return read(value)
    except Exception as exc:
        logger.warning(
            "study guide: document %s %s did not decrypt (%s); left out",
            row.get("id"), column, type(exc).__name__,
        )
        return None


def _notes(row: dict) -> list[tuple[str, str]]:
    """The document's ``concept_notes`` as (name, description) pairs. Notes
    stored before encryption (plain JSON) read as they are
    (``decrypt_json_column``); notes that are not a list of notes (a sentence
    some old rows hold) are none."""
    raw = _column(row, "concept_notes", decrypt_json_column)
    if not isinstance(raw, list):
        return []
    pairs = [
        (str(n.get("name") or "").strip(), str(n.get("description") or "").strip())
        for n in raw if isinstance(n, dict)
    ]
    return [(name, description) for name, description in pairs if name]


def _text(row: dict, column: str) -> str:
    text = _column(row, column, decrypt)
    return text.strip() if isinstance(text, str) else ""


def _concepts(row: dict) -> list[str]:
    return [name for name, _ in _notes(row)]


def _kind(file_name: str) -> str:
    _, dot, extension = file_name.rpartition(".")
    return extension.upper() if dot and extension.isalnum() and len(extension) <= 5 else "FILE"


def _note_lines(notes: list[tuple[str, str]]) -> str:
    lines = [f"- {name}: {description}" if description else f"- {name}" for name, description in notes]
    return "Key concepts:\n" + "\n".join(lines) if lines else ""


def _unlabelled(row: dict) -> SourceText:
    """One row as a source with its whole text, before labels and budget.
    Old rows have no ``extracted_text``; they read from the other two. Each
    column is read on its own, so one that does not decrypt costs only
    itself."""
    notes = _notes(row)
    summary = _text(row, "summary")
    body = _text(row, "extracted_text")
    parts = [f"Summary: {summary}" if summary else "", _note_lines(notes), body]
    return SourceText(
        label="",
        source=Source(
            id=f"document:{row['id']}",
            name=row["file_name"][:200],
            kind=_kind(row["file_name"]),
        ),
        concepts=[name for name, _ in notes],
        text="\n\n".join(part for part in parts if part),
    )


def _decrypted(rows: list[dict], read) -> list:
    """``read(row)`` for every row that can be read. One that cannot is left
    out with a warning, so a single bad row cannot fail the guide (a column
    that does not decrypt is already left out on its own, `_column`)."""
    out = []
    for row in rows:
        try:
            out.append(read(row))
        except Exception as exc:  # a wrong key, a damaged value, not JSON
            logger.warning(
                "study guide: document %s did not decrypt (%s); left out",
                row.get("id"), type(exc).__name__,
            )
    return out


def source_chars(count: int) -> int:
    """Characters each of ``count`` sources may bring. An even share of the
    total, so the last material chosen is read as much as the first."""
    return min(MAX_SOURCE_CHARS, MAX_TOTAL_CHARS // max(count, 1))


async def aload_sources(
    user_id: str, offering_id: str, material_ids: list[str],
) -> list[SourceText]:
    """The chosen documents as labelled sources (``S1``, ``S2``, ... oldest
    first), each with its concept names and its text within the budget. A
    document with nothing to read is left out."""
    rows = await _arows(
        user_id, offering_id, material_ids,
        "id,file_name,summary,concept_notes,extracted_text",
    )
    sources = [s for s in _decrypted(rows, _unlabelled) if s.text]
    share = source_chars(len(sources))
    return [
        replace(source, label=f"S{number}", text=source.text[:share])
        for number, source in enumerate(sources, start=1)
    ]


async def aload_concepts(
    user_id: str, offering_id: str, material_ids: list[str],
) -> list[str]:
    """The chosen documents' concept names, oldest document first. The planned
    outline needs only these, so the documents' text is not read."""
    rows = await _arows(user_id, offering_id, material_ids, "id,concept_notes")
    return [name for names in _decrypted(rows, _concepts) for name in names]


# ── New lectures since a guide was made ───────────────────────────────────────


async def alist_lecture_docs(user_id: str) -> list[dict]:
    """Every live lecture document of the student, as ``{id, offering_id,
    created_at}``. One read serves the whole home list."""
    return await table("documents").aselect(
        "id,offering_id,created_at",
        filters=_live(user_id, category=f"in.({','.join(LECTURE_CATEGORIES)})"),
        order="created_at.asc,id.asc",
    ) or []


def new_material_ids(
    lecture_docs: list[dict], *, offering_id: str, material_ids: list[str], since: str | None,
) -> list[str]:
    """The class's lecture documents added after ``since`` (when the guide was
    made) that the guide does not already use. No ``since``: nothing is new."""
    if not since:
        return []
    made = datetime.fromisoformat(since)
    used = set(material_ids)
    return [
        doc["id"] for doc in lecture_docs
        if doc.get("offering_id") == offering_id
        and doc["id"] not in used
        and datetime.fromisoformat(doc["created_at"]) > made
    ]
