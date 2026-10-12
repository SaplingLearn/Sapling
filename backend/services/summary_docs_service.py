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
