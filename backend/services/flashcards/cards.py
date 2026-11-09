"""Flashcard reads behind the list and import routes (#118, moved from
``routes/flashcards.py``)."""
from __future__ import annotations

from db.connection import table
from services.academics import term_id_for_label
from services.encryption import decrypt_if_present, decrypt_json


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
        "id,user_id,topic,offering_id,front,back,times_reviewed,last_rating,last_reviewed_at,created_at",
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
