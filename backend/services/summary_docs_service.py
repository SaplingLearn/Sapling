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

import logging
from datetime import datetime, timezone

from agents._run import run_agent_sync
from agents.deps import SaplingDeps
from agents.summary_edit import summary_edit_agent
from agents.usage import record_agent_usage
from db.connection import table
from services.encryption import (
    decrypt_if_present,
    decrypt_json,
    encrypt_if_present,
    encrypt_json,
)
from services.prompt_safety import neutralize_delimiters, wrap_untrusted

logger = logging.getLogger(__name__)


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
    (Task 14), which is itself sync — this stays sync rather than using
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


def update_content(summary_doc_id: str, user_id: str, content: dict) -> dict | None:
    """Autosave: persist the editor's current content. Deliberately writes
    NO version row — see the plan header's "Deviation from the approved
    spec" note. Scoped to owner_user_id so one user can never autosave
    into another's summary doc."""
    rows = table("summary_docs").update(
        {"content": encrypt_json(content), "updated_at": _now_iso()},
        filters={"id": f"eq.{summary_doc_id}", "owner_user_id": f"eq.{user_id}"},
    )
    if not rows:
        return None
    return _decrypt_doc_row(rows[0])


#: Versions beyond this are never read — the history panel shows a
#: bounded, recent timeline, not an unbounded archive.
_MAX_VERSIONS = 50


def list_versions(summary_doc_id: str, user_id: str) -> list[dict] | None:
    """The history panel's read: newest first, each with a plaintext
    preview of its first paragraph. None if the caller doesn't own the doc."""
    owned = table("summary_docs").select(
        "id", filters={"id": f"eq.{summary_doc_id}", "owner_user_id": f"eq.{user_id}"}, limit=1,
    )
    if not owned:
        return None
    rows = table("summary_doc_versions").select(
        "id,trigger,content,created_at",
        filters={"summary_doc_id": f"eq.{summary_doc_id}"},
        order="created_at.desc",
        limit=_MAX_VERSIONS,
    ) or []
    out = []
    for r in rows:
        try:
            content = decrypt_json(r["content"])
        except Exception:
            # decrypt_json re-raises when both decrypt AND plaintext
            # parse fail (a genuinely corrupted row) — degrade that one
            # row instead of 500ing the whole list. Match the pattern from
            # routes/documents.py::list_documents.
            logger.warning(
                "content decrypt failed for summary_doc_version %s; degrading to placeholder",
                r.get("id"),
            )
            preview = "[Could not load this version]"
        else:
            preview = plaintext_from_prosemirror(content, max_chars=160)
        out.append({
            "id": r["id"],
            "trigger": r["trigger"],
            "created_at": r["created_at"],
            "preview": preview,
        })
    return out


def restore_version(summary_doc_id: str, user_id: str, version_id: str) -> dict | None:
    """Bring an earlier version's content back as the doc's current
    content. Writes a NEW version first (trigger='restored') so restoring
    is itself undoable, never destructive (spec section 2)."""
    owned = table("summary_docs").select(
        "id", filters={"id": f"eq.{summary_doc_id}", "owner_user_id": f"eq.{user_id}"}, limit=1,
    )
    if not owned:
        return None
    version_rows = table("summary_doc_versions").select(
        "content", filters={"id": f"eq.{version_id}", "summary_doc_id": f"eq.{summary_doc_id}"}, limit=1,
    )
    if not version_rows:
        return None
    try:
        restored_content = decrypt_json(version_rows[0]["content"])
    except Exception:
        # decrypt_json re-raises when both decrypt AND plaintext
        # parse fail (a genuinely corrupted row) — degrade to None
        # and let the route layer map this to a 404, matching the pattern
        # of "not owned" and "version not found" failures.
        logger.warning(
            "content decrypt failed for summary_doc_version %s; returning None",
            version_rows[0].get("id"),
        )
        return None
    _write_version(summary_doc_id, restored_content, "restored")
    rows = table("summary_docs").update(
        {"content": encrypt_json(restored_content), "updated_at": _now_iso()},
        filters={"id": f"eq.{summary_doc_id}", "owner_user_id": f"eq.{user_id}"},
    )
    if not rows:
        return None
    return _decrypt_doc_row(rows[0])


def _owned_pending_suggestion(summary_doc_id: str, user_id: str, suggestion_id: str) -> dict | None:
    """Verify the summary doc is owned by the user and the suggestion is
    still pending (not already resolved). Returns the suggestion row if both
    checks pass, None otherwise."""
    owned = table("summary_docs").select(
        "id", filters={"id": f"eq.{summary_doc_id}", "owner_user_id": f"eq.{user_id}"}, limit=1,
    )
    if not owned:
        return None
    rows = table("summary_doc_suggestions").select(
        "id,summary_doc_id,status",
        filters={"id": f"eq.{suggestion_id}", "summary_doc_id": f"eq.{summary_doc_id}"},
        limit=1,
    )
    if not rows or rows[0]["status"] != "pending":
        return None
    return rows[0]


def keep_suggestion(summary_doc_id: str, user_id: str, suggestion_id: str, content: dict) -> dict | None:
    """Resolve a pending suggestion as kept. The caller (the route) has
    already applied the suggested replacement in the editor and sends the
    resulting full document as `content` — this function trusts it exactly
    as it would trust a normal autosave from the authenticated owner, and
    additionally marks the suggestion row + writes a restore point."""
    if _owned_pending_suggestion(summary_doc_id, user_id, suggestion_id) is None:
        return None
    table("summary_doc_suggestions").update(
        {"status": "kept", "resolved_at": _now_iso()},
        filters={"id": f"eq.{suggestion_id}"},
    )
    _write_version(summary_doc_id, content, "ai_edit_kept")
    rows = table("summary_docs").update(
        {"content": encrypt_json(content), "updated_at": _now_iso()},
        filters={"id": f"eq.{summary_doc_id}", "owner_user_id": f"eq.{user_id}"},
    )
    if not rows:
        return None
    return _decrypt_doc_row(rows[0])


def undo_suggestion(summary_doc_id: str, user_id: str, suggestion_id: str) -> bool:
    """Reject a pending suggestion. Nothing was ever applied to `content`,
    so this only flips the suggestion's status."""
    if _owned_pending_suggestion(summary_doc_id, user_id, suggestion_id) is None:
        return False
    table("summary_doc_suggestions").update(
        {"status": "undone", "resolved_at": _now_iso()},
        filters={"id": f"eq.{suggestion_id}"},
    )
    return True


#: How much of a summary's plaintext to carry in list/search responses —
#: matches the 3-line clamp the Library grid card renders.
_PREVIEW_MAX_CHARS = 220


def attach_summary_previews(docs: list[dict]) -> None:
    """Mutate each dict in `docs` in place, adding `summary_doc_id`,
    `summary_preview` (plaintext, truncated), and `summary_source_count`.

    One query for summary_docs + one for summary_doc_sources, regardless of
    how many documents are passed — the same per-request-batch shape as
    routes/notes.py's `_course_meta` cache, not one query per document.
    """
    if not docs:
        return
    doc_ids = [d["id"] for d in docs]
    in_clause = "in.(" + ",".join(doc_ids) + ")"
    summary_rows = table("summary_docs").select(
        "id,primary_document_id,content",
        filters={"primary_document_id": in_clause},
    ) or []
    by_primary_doc = {r["primary_document_id"]: r for r in summary_rows}
    summary_doc_ids = [r["id"] for r in summary_rows]

    source_counts: dict[str, int] = {}
    if summary_doc_ids:
        sd_in_clause = "in.(" + ",".join(summary_doc_ids) + ")"
        source_rows = table("summary_doc_sources").select(
            "summary_doc_id,document_id",
            filters={"summary_doc_id": sd_in_clause},
        ) or []
        for s in source_rows:
            source_counts[s["summary_doc_id"]] = source_counts.get(s["summary_doc_id"], 0) + 1

    for d in docs:
        summary_row = by_primary_doc.get(d["id"])
        if summary_row is None:
            d["summary_doc_id"] = None
            d["summary_preview"] = None
            d["summary_source_count"] = 0
            continue
        d["summary_doc_id"] = summary_row["id"]
        try:
            content = decrypt_json(summary_row["content"])
            d["summary_preview"] = plaintext_from_prosemirror(content, max_chars=_PREVIEW_MAX_CHARS)
        except Exception:
            # Same degrade-one-row-not-the-whole-list posture as
            # list_versions (Task 6) — one corrupted summary doc must not
            # break the Library list for every other document.
            logger.warning(
                "summary_docs content decrypt failed for id %s; degrading preview",
                summary_row["id"],
            )
            d["summary_preview"] = None
        d["summary_source_count"] = source_counts.get(summary_row["id"], 0)


def delete_summary_docs_for_document(document_id: str) -> None:
    """Hard-delete the summary doc this document primarily owns.

    A real SQL DELETE (not the soft-delete `documents` uses) so the table's
    ON DELETE CASCADE foreign keys (summary_doc_sources,
    summary_doc_versions, summary_doc_suggestions) clean up everything
    under it in one statement. Called from routes/documents.py's
    delete_document route right after that route soft-deletes the
    documents row — see the spec's "Delete-together behavior" decision. A
    document that is only a SECONDARY source of some other summary doc is
    unaffected: this only ever matches on `primary_document_id`, and
    `summary_doc_sources.document_id`'s own FK (ON DELETE CASCADE on
    `documents`) only fires on a hard delete, which the app never does to
    a document that still has other owners.
    """
    table("summary_docs").delete(filters={"primary_document_id": f"eq.{document_id}"})


def _source_texts(summary_doc_id: str) -> list[tuple[str, str]]:
    """(file_name, extracted_text) for every source document attached to
    this summary doc — the raw material the agent can draw on, distinct
    from the summary doc's OWN content."""
    source_rows = table("summary_doc_sources").select(
        "document_id", filters={"summary_doc_id": f"eq.{summary_doc_id}"},
    ) or []
    doc_ids = [s["document_id"] for s in source_rows]
    if not doc_ids:
        return []
    in_clause = "in.(" + ",".join(doc_ids) + ")"
    docs = table("documents").select(
        "id,file_name,extracted_text", filters={"id": in_clause},
    ) or []
    return [
        (d.get("file_name") or "Untitled", decrypt_if_present(d.get("extracted_text")) or "")
        for d in docs
    ]


def _build_ask_prompt(
    *,
    instruction: str,
    selection_text: str | None,
    doc_plaintext: str,
    sources: list[tuple[str, str]],
    allow_surrounding_edits: bool,
) -> str:
    parts = [f"Instruction: {neutralize_delimiters(instruction)}"]
    if selection_text:
        parts.append(
            "Text to rewrite (a highlighted section):\n"
            + wrap_untrusted(selection_text, source="highlighted summary text")
        )
        # Spec section 3 "Suggestion scope": a per-request toggle, default
        # off (confined to the highlight — the safer default). Only
        # meaningful for a SELECTION ask; a whole-doc ask has no
        # "surrounding text" to distinguish.
        parts.append(
            "You may ONLY rewrite the exact text above — do not change "
            "anything outside it."
            if not allow_surrounding_edits
            else "You may also lightly adjust text immediately "
            "surrounding the highlighted section if it improves flow, "
            "but stay focused on the instruction."
        )
    else:
        parts.append(
            "Text to rewrite (the whole document, nothing was highlighted):\n"
            + wrap_untrusted(doc_plaintext, source="the full summary document")
        )
    for file_name, text in sources:
        if not text:
            continue
        parts.append(
            f"Source document '{neutralize_delimiters(file_name)}':\n"
            + wrap_untrusted(text[:4000], source=f"source document {file_name}")
        )
    return "\n\n".join(parts)


def create_suggestion(
    summary_doc_id: str,
    user_id: str,
    *,
    anchor_from: int | None,
    anchor_to: int | None,
    instruction: str,
    original_text: str | None,
    allow_surrounding_edits: bool = False,
) -> dict | None:
    """Run the summary_edit agent and store its output as a pending
    suggestion. Returns None if the caller doesn't own this summary doc.

    This function is sync and calls run_agent_sync, which raises RuntimeError
    if invoked from a thread that already has a running event loop. An
    `async def` route caller MUST wrap this call in
    `asyncio.to_thread(create_suggestion, ...)` (the pattern used in
    routes/documents.py / routes/admin_documents.py), not call it directly.
    """
    doc = get_summary_doc(summary_doc_id, user_id)
    if doc is None:
        return None
    doc_plaintext = plaintext_from_prosemirror(doc["content"])
    sources = _source_texts(summary_doc_id)
    user_prompt = _build_ask_prompt(
        instruction=instruction, selection_text=original_text,
        doc_plaintext=doc_plaintext, sources=sources,
        allow_surrounding_edits=allow_surrounding_edits,
    )
    deps = SaplingDeps(
        user_id=user_id, course_id=None, supabase=None,
        request_id="", feature="library",
    )
    result = record_agent_usage(
        run_agent_sync(summary_edit_agent.run(user_prompt, deps=deps)),
        feature="library", task="summary_edit", user_id=user_id,
    )
    proposed_text = result.output.proposed_text

    inserted = table("summary_doc_suggestions").insert({
        "summary_doc_id": summary_doc_id,
        "anchor_from": anchor_from,
        "anchor_to": anchor_to,
        "instruction": encrypt_if_present(instruction),
        "original_text": encrypt_if_present(original_text),
        "proposed_text": encrypt_if_present(proposed_text),
    })
    row = dict(inserted[0])
    row["instruction"] = instruction
    row["original_text"] = original_text
    row["proposed_text"] = proposed_text
    return row


def plaintext_for_primary_document(document_id: str) -> str | None:
    """The plaintext of the summary doc this document seeded, for callers
    (scan-concepts) that want the student's current write-up as context —
    not capped to preview length, since this feeds a model prompt rather
    than a UI card."""
    rows = table("summary_docs").select(
        "content", filters={"primary_document_id": f"eq.{document_id}"}, limit=1,
    )
    if not rows:
        return None
    try:
        return plaintext_from_prosemirror(decrypt_json(rows[0]["content"]))
    except Exception:
        # Same degrade-not-crash posture as list_versions (Task 6) and
        # attach_summary_previews (Task 8) — a corrupted summary doc must
        # not break concept scanning; it just loses this one context input.
        logger.warning(
            "summary_docs content decrypt failed for primary_document_id %s; "
            "degrading to no summary context",
            document_id,
        )
        return None
