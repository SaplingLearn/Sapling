"""Summary doc service — the editable, multi-source replacement for the
static documents.summary column.

Schema (see backend/db/migrations/<TIMESTAMP>_summary_docs.sql):
    summary_docs(id, owner_user_id, primary_document_id, content*, created_at, updated_at)
    summary_doc_sources(summary_doc_id, document_id, added_at)
    summary_doc_versions(id, summary_doc_id, content*, trigger, created_at)
    summary_doc_suggestions(id, summary_doc_id, anchor_from, anchor_to,
                             instruction*, original_text*, proposed_text*, status, ...)
    * = AES-GCM encrypted at rest (content via encrypt_json/decrypt_json,
        the text fields via encrypt_if_present/decrypt_if_present).

Sync throughout (plain `table()` calls, no asyncio.to_thread) to match
routes/documents.py and routes/study_guide.py — this feature is an
extension of the upload pipeline (routes/documents.py's `_persist_document`
is sync and calls into this module directly), not the async notes.py style.
"""
from __future__ import annotations

from datetime import datetime, timezone

from db.connection import table
from services.encryption import (
    decrypt_if_present,
    encrypt_if_present,
    decrypt_json,
    encrypt_json,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def prosemirror_doc_from_text(text: str) -> dict:
    """Seed a TipTap/ProseMirror doc from plain text, one paragraph per
    blank-line-separated block. Used to turn the upload pipeline's
    summary_agent output into the initial editable document."""
    paragraphs = [p.strip() for p in (text or "").split("\n\n")]
    paragraphs = [p for p in paragraphs if p]
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": p}]}
            for p in paragraphs
        ],
    }


def plaintext_from_prosemirror(doc: dict, max_chars: int | None = None) -> str:
    """Walk a ProseMirror doc and concatenate its text nodes — paragraphs
    joined by a blank line, text nodes within a paragraph concatenated with
    no separator (mirroring how ProseMirror itself renders marks as
    adjacent text runs). Used for search/preview text and as agent context,
    never for re-rendering: formatting is intentionally lost."""
    paragraph_texts: list[str] = []
    for node in doc.get("content") or []:
        if node.get("type") != "paragraph":
            continue
        text = "".join(
            child.get("text", "")
            for child in (node.get("content") or [])
            if child.get("type") == "text"
        )
        if text:
            paragraph_texts.append(text)
    joined = "\n\n".join(paragraph_texts)
    if max_chars is not None:
        return joined[:max_chars]
    return joined


def create_summary_doc(*, user_id: str, primary_document_id: str, seed_text: str) -> dict:
    """Create the one summary doc an upload produces (#spec section 2).

    Called once per upload from routes/documents.py::_persist_document
    (Task 15), which is itself sync — this stays sync rather than using
    asyncio.to_thread so it can be called directly from that call site.
    """
    content = prosemirror_doc_from_text(seed_text)
    row = {
        "owner_user_id": user_id,
        "primary_document_id": primary_document_id,
        "content": encrypt_json(content),
    }
    inserted = table("summary_docs").insert(row)
    summary_doc = dict(inserted[0])
    table("summary_doc_sources").insert(
        {"summary_doc_id": summary_doc["id"], "document_id": primary_document_id}
    )
    table("summary_doc_versions").insert({
        "summary_doc_id": summary_doc["id"],
        "content": encrypt_json(content),
        "trigger": "initial",
    })
    summary_doc["content"] = content
    return summary_doc


def _decrypt_doc_row(row: dict) -> dict:
    out = dict(row)
    out["content"] = decrypt_json(out["content"])
    return out


def get_summary_doc(summary_doc_id: str, user_id: str) -> dict | None:
    """Fetch a summary doc the caller owns, with its sources (file names
    resolved) and pending suggestions attached — the single read the
    editor route needs."""
    rows = table("summary_docs").select(
        "id,owner_user_id,primary_document_id,content,created_at,updated_at",
        filters={"id": f"eq.{summary_doc_id}", "owner_user_id": f"eq.{user_id}"},
        limit=1,
    )
    if not rows:
        return None
    doc = _decrypt_doc_row(rows[0])

    source_rows = table("summary_doc_sources").select(
        "document_id,added_at",
        filters={"summary_doc_id": f"eq.{summary_doc_id}"},
    ) or []
    doc_ids = [s["document_id"] for s in source_rows]
    file_names: dict[str, str] = {}
    if doc_ids:
        in_clause = "in.(" + ",".join(doc_ids) + ")"
        files = table("documents").select(
            "id,file_name", filters={"id": in_clause},
        ) or []
        file_names = {f["id"]: f["file_name"] for f in files}
    doc["sources"] = [
        {
            "document_id": s["document_id"],
            "file_name": file_names.get(s["document_id"], "Untitled"),
            "added_at": s["added_at"],
        }
        for s in source_rows
    ]

    suggestion_rows = table("summary_doc_suggestions").select(
        "id,anchor_from,anchor_to,instruction,original_text,proposed_text,status,created_at,resolved_at",
        filters={"summary_doc_id": f"eq.{summary_doc_id}", "status": "eq.pending"},
        order="created_at.asc",
    ) or []
    doc["pending_suggestions"] = [
        {
            **s,
            "instruction": decrypt_if_present(s.get("instruction")) or "",
            "original_text": decrypt_if_present(s.get("original_text")),
            "proposed_text": decrypt_if_present(s.get("proposed_text")) or "",
        }
        for s in suggestion_rows
    ]
    return doc


def _write_version(summary_doc_id: str, content: dict, trigger: str) -> None:
    table("summary_doc_versions").insert({
        "summary_doc_id": summary_doc_id,
        "content": encrypt_json(content),
        "trigger": trigger,
    })


def add_source(summary_doc_id: str, user_id: str, document_id: str) -> dict | None:
    """Make `document_id` available as context for this summary doc.

    Deliberately does NOT touch `content` — adding a source only makes it
    available; the doc's text changes only when the user explicitly asks
    the agent to use it (spec section 2). Still writes a restore-point
    version, since "a source was added" is itself one of the four
    meaningful history events.
    """
    doc = get_summary_doc(summary_doc_id, user_id)
    if doc is None:
        return None
    table("summary_doc_sources").insert(
        {"summary_doc_id": summary_doc_id, "document_id": document_id}
    )
    _write_version(summary_doc_id, doc["content"], "source_added")
    return get_summary_doc(summary_doc_id, user_id)


def remove_source(summary_doc_id: str, user_id: str, document_id: str) -> dict | str | None:
    """Stop using `document_id` as context. Returns the updated doc, the
    string "primary" if the caller tried to remove the doc's own primary
    document (refused — that would orphan the doc), or None if the caller
    doesn't own this summary doc."""
    doc = get_summary_doc(summary_doc_id, user_id)
    if doc is None:
        return None
    if document_id == doc["primary_document_id"]:
        return "primary"
    table("summary_doc_sources").delete(
        filters={"summary_doc_id": f"eq.{summary_doc_id}", "document_id": f"eq.{document_id}"}
    )
    _write_version(summary_doc_id, doc["content"], "source_removed")
    return get_summary_doc(summary_doc_id, user_id)
