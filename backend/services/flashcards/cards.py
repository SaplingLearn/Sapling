"""Flashcard reads behind the list and import routes (#118, moved from
``routes/flashcards.py``), and the list's FSRS review order (learning-loop
PKG-11: `_loop_order`)."""
from __future__ import annotations

from datetime import datetime

from db.connection import table
from learning.fsrs import order_due
from services.academics import term_id_for_label
from services.encryption import decrypt_if_present, decrypt_json
from services.timestamps import parse_ts


_LEGACY_LIST_COLS = (
    "id,user_id,topic,offering_id,front,back,times_reviewed,last_rating,"
    "last_reviewed_at,created_at"
)
_FSRS_LIST_COLS = ",fsrs_d,fsrs_s,due_at,reps,lapses"


def _order_due_rows(rows: list[dict], now: datetime) -> list[dict]:
    """PKG-11: due cards in learning.fsrs.order_due's order (|R − threshold|
    ascending, spec §3.2). ADAPTER (HANDOFF-02: `order_due(items, now, *,
    stability_key="fsrs_s", last_review_key=...)`): a flashcard's stability
    is `fsrs_s` and its last review is `last_reviewed_at`. If PKG-02's
    signature changes, change THIS function only."""
    if not rows:
        return []
    return list(order_due(rows, now, last_review_key="last_reviewed_at"))


def _loop_order(rows: list[dict], now: datetime) -> tuple[list[dict], list[dict]]:
    """PKG-11: (ordered rows, due rows). Due first (`due_at` <= now, in
    _order_due_rows order), then never rated on the loop path (`fsrs_s` null,
    query order), then not yet due by `due_at` ascending. A null `due_at` is
    never due."""
    due, fresh, later = [], [], []
    for r in rows:
        due_at = parse_ts(r.get("due_at"))
        if due_at is not None and due_at <= now:
            due.append(r)
        elif r.get("fsrs_s") is None:
            fresh.append(r)
        else:
            later.append(r)
    later.sort(key=lambda r: parse_ts(r.get("due_at")) or now)
    ordered_due = _order_due_rows(due, now)
    return ordered_due + fresh + later, ordered_due


def list_flashcards(
    user_id: str, topic: str | None = None, semester: str | None = None
) -> list[dict]:
    """The user's cards, newest first, decrypted; ``topic`` narrows to one
    topic and ``semester`` to one term (#141). Errors propagate: the route
    maps them."""
    filters = {"user_id": f"eq.{user_id}"}
    if topic:
        filters["topic"] = f"eq.{topic}"

    rows = table("flashcards").select(
        _LEGACY_LIST_COLS + _FSRS_LIST_COLS,
        filters=filters, order="created_at.desc"
    ) or []
    for r in rows:
        r["front"] = decrypt_if_present(r.get("front"))
        r["back"] = decrypt_if_present(r.get("back"))
    if semester:
        # Term scoping (#141). This route is user-wide (no course id), so
        # the filter works on the cards' offering: cards from the selected
        # term stay, other terms' cards are hidden, and term-LESS cards
        # (offering_id NULL — e.g. AI-generated) stay visible under any
        # selection so picking a term never strands them. An unknown label
        # degrades to term-less cards only — never a 500.
        term_id = term_id_for_label(semester)
        allowed: set[str] = set()
        if term_id:
            offs = table("course_offerings").select(
                "id", filters={"term_id": f"eq.{term_id}"}
            ) or []
            allowed = {o["id"] for o in offs if o.get("id")}
        rows = [
            r for r in rows
            if r.get("offering_id") is None or r["offering_id"] in allowed
        ]
    return rows


def library_doc_source_text(user_id: str, document_id: str) -> str | None:
    """The text a library document contributes to an import generation (its
    summary plus concept notes), or None when the user has no such live
    document."""
    rows = table("documents").select(
        "id,user_id,summary,concept_notes,file_name",
        filters={
            "id": f"eq.{document_id}",
            "user_id": f"eq.{user_id}",
            "deleted_at": "is.null",
        },
        limit=1,
    )
    if not rows:
        return None
    doc = rows[0]
    doc_summary = decrypt_if_present(doc.get("summary")) or ""
    notes_raw = doc.get("concept_notes")
    if isinstance(notes_raw, str):
        try:
            doc_notes = decrypt_json(notes_raw)
        except Exception:
            doc_notes = notes_raw
    else:
        doc_notes = notes_raw or {}
    parts = [doc_summary, str(doc_notes)]
    return "\n\n".join(p for p in parts if p)
