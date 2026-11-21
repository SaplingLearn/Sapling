"""
backend/services/documents/doc_notes.py

The editable notes document behind ``/library/{docId}/notes``: one
``document_notes`` row per library document
(20261119120000_library_folders_and_document_notes.sql).

The encryption boundary lives entirely in this module, the same way
``services/notes_service.py`` keeps it for the notetaker: every write encrypts
``title`` and ``content`` before Supabase sees them, every read decrypts before
returning. Routes never touch ciphertext.

Notes are generated on the first read and then owned by the student — a
regenerate is the only thing that overwrites their edits, and the UI asks
first.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from db.connection import table
from services.encryption import decrypt_if_present, encrypt_if_present

logger = logging.getLogger(__name__)

#: Largest notes body accepted on a save. The editor's own documents are a few
#: tens of KB; this only stops a runaway client. Matches the order of magnitude
#: of what `extracted_text` already stores per document.
MAX_CONTENT = 400_000

#: Longest title accepted.
MAX_TITLE = 300

#: How much of the source document is handed to the generator. Long enough for
#: a full lecture, short enough to stay inside the worker's usage budget.
MAX_SOURCE_CHARS = 24_000

_COLS = "document_id,user_id,title,content,final,created_at,updated_at"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decrypt_row(row: dict) -> dict:
    out = dict(row)
    out["title"] = decrypt_if_present(out.get("title")) or ""
    out["content"] = decrypt_if_present(out.get("content")) or ""
    out["final"] = bool(out.get("final"))
    return out


async def get_notes(document_id: str, user_id: str) -> dict | None:
    """The stored notes row, decrypted, or ``None`` if none has been made."""
    rows = await table("document_notes").aselect(
        _COLS,
        filters={"document_id": f"eq.{document_id}", "user_id": f"eq.{user_id}"},
        limit=1,
    ) or []
    return _decrypt_row(rows[0]) if rows else None


async def save_notes(
    document_id: str,
    user_id: str,
    *,
    title: str | None = None,
    content: str | None = None,
    final: bool | None = None,
) -> dict:
    """Create or update the notes row. Only the fields passed are written, so
    the autosave can send a body without clearing the title and the Finalize
    button can flip the flag without resending the body."""
    now = _now_iso()
    row: dict = {"document_id": document_id, "user_id": user_id, "updated_at": now}
    if title is not None:
        row["title"] = encrypt_if_present(title[:MAX_TITLE]) if title else None
    if content is not None:
        row["content"] = encrypt_if_present(content[:MAX_CONTENT]) if content else None
    if final is not None:
        row["final"] = bool(final)

    existing = await table("document_notes").aselect(
        "document_id",
        filters={"document_id": f"eq.{document_id}", "user_id": f"eq.{user_id}"},
        limit=1,
    ) or []
    if existing:
        await table("document_notes").aupdate(
            {k: v for k, v in row.items() if k not in ("document_id", "user_id")},
            filters={"document_id": f"eq.{document_id}", "user_id": f"eq.{user_id}"},
        )
    else:
        row.setdefault("created_at", now)
        row.setdefault("final", False)
        await table("document_notes").ainsert(row)

    saved = await get_notes(document_id, user_id)
    return saved or _decrypt_row(row)


async def source_text(document_id: str, user_id: str) -> tuple[str, dict]:
    """``(text, document_row)`` for the generator.

    ``extracted_text`` is the full document; it is encrypted, so it is read and
    decrypted here. When a document has none (an older row, or one whose
    extraction was never stored) the summary and concept notes stand in — a
    thinner source, but enough for an honest set of notes.
    """
    rows = await table("documents").aselect(
        "id,file_name,category,summary,concept_notes,extracted_text,offering_id,created_at",
        filters={"id": f"eq.{document_id}", "user_id": f"eq.{user_id}", "deleted_at": "is.null"},
        limit=1,
    ) or []
    if not rows:
        return "", {}
    doc = rows[0]
    text = decrypt_if_present(doc.get("extracted_text")) or ""
    summary = decrypt_if_present(doc.get("summary")) or ""
    if not text.strip():
        notes = doc.get("concept_notes")
        if isinstance(notes, str):
            from services.encryption import decrypt_json
            try:
                notes = decrypt_json(notes)
            except Exception:
                logger.warning(
                    "concept_notes decrypt failed for document %s; generating from the summary alone",
                    document_id,
                )
                notes = []
        bits = [summary]
        for n in (notes or []):
            if isinstance(n, dict) and n.get("name"):
                bits.append(f"{n['name']}: {n.get('description') or ''}")
        text = "\n\n".join(b for b in bits if b and b.strip())
    doc["summary"] = summary
    return text[:MAX_SOURCE_CHARS], doc


def fallback_notes(doc: dict) -> str:
    """Notes written without the model, for a document the generator could not
    read (no extracted text, no summary) — or when the model call failed.

    Honest rather than padded: it says what is known and leaves the student a
    place to write, which is exactly what the editor is for.
    """
    summary = (doc.get("summary") or "").strip()
    name = doc.get("file_name") or "this document"
    if summary:
        return (
            "<h2>Overview</h2>"
            f"<p>{_esc(summary)}</p>"
            "<h2>Your Notes</h2>"
            "<p><br></p>"
            '<h2>Questions to Review</h2>'
            '<ul class="check"><li data-done="0">'
            "<span>What is the main idea of this document?</span></li></ul>"
        )
    return (
        "<h2>Your Notes</h2>"
        f"<p>Sapling could not read enough of {_esc(name)} to draft notes for "
        "it. Write your own here, or re-upload the file if it was a scan "
        "without a text layer.</p>"
        "<p><br></p>"
    )


def _esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def clean_generated(html: str) -> str:
    """Strip what a model sometimes wraps generated HTML in: markdown fences,
    a stray document title, and leading/trailing prose."""
    out = (html or "").strip()
    if out.startswith("```"):
        out = out.split("\n", 1)[-1] if "\n" in out else ""
        if out.rstrip().endswith("```"):
            out = out.rstrip()[:-3]
    out = out.strip()
    # A generated <h1> duplicates the page's own title field.
    while out.lower().startswith("<h1"):
        end = out.lower().find("</h1>")
        if end < 0:
            break
        out = out[end + 5:].lstrip()
    return out[:MAX_CONTENT]
