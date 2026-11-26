"""
backend/services/documents/doc_notes.py

The editable notes document behind ``/library/{docId}/notes``: one
``document_notes`` row per library document
(20261125065039_document_notes.sql).

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

from cryptography.exceptions import InvalidTag

from db.connection import table
from services.encryption import bind, decrypt_if_present, encrypt_if_present

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
    doc_id = out.get("document_id")
    out["title"] = decrypt_if_present(
        out.get("title"), bind=bind("document_notes", "title", doc_id)) or ""
    out["content"] = decrypt_if_present(
        out.get("content"), bind=bind("document_notes", "content", doc_id)) or ""
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
        row["title"] = encrypt_if_present(
            title[:MAX_TITLE], bind=bind("document_notes", "title", document_id),
        ) if title else None
    if content is not None:
        row["content"] = encrypt_if_present(
            content[:MAX_CONTENT], bind=bind("document_notes", "content", document_id),
        ) if content else None
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
    text = decrypt_if_present(
        doc.get("extracted_text"), bind=bind("documents", "extracted_text", document_id)) or ""
    summary = decrypt_if_present(
        doc.get("summary"), bind=bind("documents", "summary", document_id)) or ""
    if not text.strip():
        notes = doc.get("concept_notes")
        if isinstance(notes, str):
            from services.encryption import decrypt_json
            try:
                notes = decrypt_json(
                    notes, bind=bind("documents", "concept_notes", document_id))
            except (InvalidTag, ValueError):
                # decrypt_json raises an EncryptionError (a ValueError) for a
                # refused value, or the original InvalidTag / base64 / JSON
                # error when neither the ciphertext nor plaintext parses.
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
            '<span class="box" contenteditable="false" data-act="check">✓</span>'
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


# ── Block chrome ──────────────────────────────────────────────────────────
#
# Every block the editor inserts carries three things besides its content: a
# remove button, sometimes a mono-caps label, and the CONTROL that opens or
# edits it. `frontend/src/lib/notes/blocks.ts` is the source of truth; the
# strings below are its `X`, `H()` and action bars verbatim.
#
# A model writes a block's content reliably and its chrome unreliably, and the
# chrome is what makes the block work. A `qa` written without its
# `data-act="open"` button is the sharp case: `library-notes.css` styles
# `.qa-a { display: none }` and reveals it only under `.blk[data-open="1"]`, so
# the answer is generated, saved, and permanently invisible with nothing on
# screen to reveal it. A `toggle` without its arrow cannot be collapsed, and a
# `table` without its Edit button cannot gain or lose a row.
#
# Asking the prompt for the boilerplate does not fix this: it is a lot of exact
# markup to reproduce on every block of every document, and a single slip
# ships another half-dead block. So the prompt asks for the CONTENT shape and
# the chrome is put back here, deterministically, where it cannot drift.
_BLK_X = ('<button class="blk-x" contenteditable="false" data-act="del" '
          'title="Remove" aria-label="Remove block">×</button>')
_QA_BAR = ('<div class="tbl-bar" contenteditable="false">'
           '<button class="sbtn" data-act="open">Show Answer</button></div>')
_TG_ARROW = ('<button class="tg-arrow" contenteditable="false" data-act="open" '
             'aria-label="Show or hide">▶</button>')
_TBL_EDIT = ('<button class="tbl-edit" contenteditable="false" '
             'data-act="tedit">Edit</button>')
_TBL_BAR = ('<div class="tbl-bar" contenteditable="false">'
            '<button class="sbtn" data-act="row">+ Row</button>'
            '<button class="sbtn" data-act="col">+ Column</button>'
            '<button class="sbtn" data-act="delrow">− Row</button>'
            '<button class="sbtn" data-act="delcol">− Column</button>'
            '<span style="flex:1"></span>'
            '<button class="sbtn tbl-del" data-act="del">Delete table</button>'
            '<button class="sbtn tbl-done" data-act="tedit">Done</button></div>')


def _block_end(html: str, start: int) -> int:
    """Index just past the ``</div>`` closing the ``<div>`` that opens at
    ``start``, by depth count. Returns ``len(html)`` for an unclosed block."""
    depth, i, n = 0, start, len(html)
    while i < n:
        if html.startswith("<div", i):
            depth += 1
            i += 4
        elif html.startswith("</div>", i):
            depth -= 1
            i += 6
            if depth == 0:
                return i
        else:
            i += 1
    return n


def _insert_at(block: str, marker: str, fragment: str) -> str:
    """``fragment`` immediately before ``marker``, or appended before the
    block's own closing tag when the marker is missing."""
    at = block.find(marker)
    if at < 0:
        return block[: block.rfind("</div>")] + fragment + block[block.rfind("</div>"):]
    return block[:at] + fragment + block[at:]


def _restore_chrome(block: str, kind: str) -> str:
    """One block, with whatever chrome its kind requires put back."""
    head = block.index(">") + 1  # just past the block's own opening tag
    if 'class="blk-x"' not in block:
        block = block[:head] + _BLK_X + block[head:]
        head += len(_BLK_X)

    if kind == "qa":
        if 'class="blk-h"' not in block:
            label = '<div class="blk-h" contenteditable="false">Practice Question</div>'
            block = block[:head] + label + block[head:]
        if 'data-act="open"' not in block:
            block = _insert_at(block, '<div class="qa-a"', _QA_BAR)
    elif kind == "toggle":
        if 'data-act="open"' not in block:
            block = _insert_at(block, '<div class="tg-title"', _TG_ARROW)
    elif kind == "table":
        if 'data-act="tedit"' not in block:
            block = block[:head] + _TBL_EDIT + block[head:]
        if 'data-act="row"' not in block and "</table>" in block:
            block = block.replace("</table>", "</table>" + _TBL_BAR, 1)
    return block


#: The block kinds whose chrome is restored, and nothing else: a `math`,
#: `check` or `code` block the model writes is already complete.
_CHROME_KINDS = ("qa", "toggle", "table")


def restore_block_chrome(html: str) -> str:
    """Put the missing controls back into every generated block.

    Idempotent: a block that already carries its chrome is returned untouched,
    so this is safe over hand-written and round-tripped content too.
    """
    out = html
    for kind in _CHROME_KINDS:
        needle = f'<div class="blk" data-blk="{kind}"'
        i = out.find(needle)
        while i >= 0:
            end = _block_end(out, i)
            fixed = _restore_chrome(out[i:end], kind)
            out = out[:i] + fixed + out[end:]
            i = out.find(needle, i + len(fixed))
    return out


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
    return restore_block_chrome(out)[:MAX_CONTENT]
