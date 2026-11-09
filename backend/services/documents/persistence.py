"""
backend/services/documents/persistence.py

Saving an upload's outcome (#118, moved from routes/documents.py): the
idempotent-replay lookup and payload, the documents insert (with its
missing-column escape hatch), and the syllabus / graph post-steps.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from agents.document import DocumentProcessingResult
from db.connection import table
from services import events_service
from services.calendar_service import save_assignments_to_db
from services.documents_read import decrypt_document_row
from services.encryption import encrypt_if_present, encrypt_json
from services.graph_service import apply_graph_update
from services.xp_service import award_xp_safe

logger = logging.getLogger(__name__)


def _existing_doc_by_request_id(user_id: str, request_id: str) -> dict | None:
    """Return an existing documents row for this user + request_id, if any.

    The request_id column may not exist in older schemas — catch that and
    return None so deployments can ship the code before the migration runs.
    Defensive against non-list return shapes (mocked DBs, partial errors)
    so a misbehaving Supabase response can't masquerade as a cache hit.
    """
    try:
        rows = table("documents").select(
            "id,user_id,offering_id,file_name,category,summary,concept_notes,created_at,processed_at",
            filters={
                "user_id": f"eq.{user_id}",
                "request_id": f"eq.{request_id}",
                "deleted_at": "is.null",
            },
            limit=1,
        )
    except Exception:
        return None
    if not isinstance(rows, list) or not rows:
        return None
    first = rows[0]
    if not isinstance(first, dict):
        return None
    return decrypt_document_row(first)


def _replay_result_payload(row: dict) -> dict:
    """The idempotent-replay `result.data`, shaped like a fresh run's (#759).

    A fresh stream sends `DocumentProcessingResult.model_dump()`; the replay
    used to send the raw documents row under the same `result` event —
    `summary` a string instead of `{abstract}`, `concept_notes` instead of
    `concepts.concepts`, a top-level `category`. One event type now carries
    one shape. Only what the row persists can be reproduced: `headline`,
    `key_points`, confidence and rationale are absent, never invented.
    `id` and `replayed` are additions on top of the fresh keys; the
    document id is also on the trailing `status:done`, as on a fresh run.
    """
    category = row.get("category") or "other"
    notes = row.get("concept_notes")
    concepts = [
        {"name": n["name"], "description": n.get("description") or ""}
        for n in (notes if isinstance(notes, list) else [])
        if isinstance(n, dict) and n.get("name")
    ]
    return {
        "classification": {"category": category, "is_syllabus": category == "syllabus"},
        "summary": {"abstract": row.get("summary") or ""},
        "concepts": {"concepts": concepts},
        "syllabus": None,
        "graph_updated": False,
        "id": row.get("id"),
        "replayed": True,
    }


#: PostgREST's code for "column not found in the schema cache", plus the
#: Postgres wording it wraps. Either shape means a column is genuinely absent
#: rather than the row being bad.
_MISSING_COLUMN_MARKERS = ("PGRST204", "does not exist", "Could not find the")

#: The only columns `_persist_document` is willing to ship ahead of. Anything
#: else reported absent is a real schema problem and must surface. The last
#: three are #482's; `extracted_text` is deliberately NOT here — it predates
#: this hatch (0030), and dropping it would silently cost the recovery text.
_DROPPABLE_COLUMNS = (
    "request_id", "shareability",
    "index_status", "index_attempts", "shareability_confidence",
)


def _missing_column(exc: Exception) -> str | None:
    """Which droppable column a PostgREST error says is absent, or None.

    Reads the RESPONSE BODY, not `str(exc)`. `db/connection.py` raises through
    httpx's `raise_for_status()`, whose message is only `Client error '400 Bad
    Request' for url …` plus a link to MDN — the PGRST204 payload naming the
    column never appears in it. A guard written against the exception string
    therefore never fires, which is exactly how the first version of this
    escape hatch shipped as dead code and left every upload failing in the one
    window it existed to cover.

    Returns the column NAME rather than a bool so the retry drops only that
    one. Dropping both would lose `request_id` whenever `shareability` is the
    absent one — and a client retrying with the same X-Request-ID would then no
    longer be recognised as a replay, re-running the whole orchestrator and
    persisting a duplicate document.
    """
    body = ""
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            body = response.text or ""
        except Exception:
            body = ""
    if not body:
        body = str(exc)
    if not any(m in body for m in _MISSING_COLUMN_MARKERS):
        return None
    for col in _DROPPABLE_COLUMNS:
        if f"'{col}'" in body or f'"{col}"' in body:
            return col
    return None


def _stored_confidence(classification) -> float | None:
    """The classifier's confidence as the row can hold it, or None.

    Only a real number in [0, 1] is stored — anything else would be rejected by
    `documents_shareability_confidence_check` and fail the whole insert. None
    reads as private at index time (#630), the safe direction.
    """
    value = getattr(classification, "confidence", None)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if 0.0 <= value <= 1.0 else None


def _persist_document(
    *,
    user_id: str,
    offering_id: str,
    filename: str,
    result: DocumentProcessingResult,
    request_id: str | None = None,
    course_id: str | None = None,
    char_count: int | None = None,
    extracted_text: str | None = None,
) -> tuple[str, dict]:
    """Insert a documents row from an orchestrator result.

    Shared by both upload_document_sync and the streaming upload_document.
    The document keys on the OFFERING (0025), not the abstract course.
    summary + concept_notes are encrypted at the insert boundary; the
    returned row carries the plaintext shape so callers can pass it
    straight back to the client without an extra decrypt step.
    ``request_id`` (when provided) is stored verbatim for idempotent
    replay detection. ``course_id``/``char_count`` only feed the
    document.processed observability event (#117); they are not persisted
    on the row.

    ``extracted_text`` IS persisted, encrypted, and the row is enqueued for
    indexing (#482). The indexer used to write the text, which made the
    recovery path depend on the thing that failed: a document whose indexer
    never ran had nothing for a re-drive to work from. It is stripped from the
    returned row — `/upload/sync` hands that row to the client verbatim.
    Returns (document_id, full_row).
    """
    now = datetime.now(timezone.utc).isoformat()
    concept_notes = [
        {"name": c.name, "description": c.description}
        for c in result.concepts.concepts
    ]
    summary = result.summary.abstract or None
    row = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "offering_id": offering_id,
        "file_name": filename,
        "category": result.classification.category,
        # #630: stored, not just acted on. Without a stored value, a re-index or
        # a backfill has nothing to reproduce the sharing decision from, and
        # `decide_visibility(None)` privatises everything — which is the same
        # shape of silent corpus loss as #628.
        "shareability": getattr(result.classification, "shareability", None),
        # #482: the confidence the sharing decision was made at. A re-drive
        # reads it back, because decide_visibility treats a missing confidence
        # as private — without it, recovering a correctly shared document
        # would silently privatise it.
        "shareability_confidence": _stored_confidence(result.classification),
        "extracted_text": encrypt_if_present(extracted_text),
        "index_status": "pending",
        "index_attempts": 0,
        "summary": encrypt_if_present(summary),
        "concept_notes": encrypt_json(concept_notes) if concept_notes is not None else None,
        "created_at": now,
        "processed_at": now,
    }
    if request_id:
        row["request_id"] = request_id
    # The schema may not yet have some of these columns; retry without each one
    # PostgREST names, so a deployment can ship the code before its migration
    # runs. Losing `shareability` is safe in the direction that matters: an
    # absent stored value reads as private at index time (#630), never as
    # shareable.
    #
    # Gated on the error BODY and narrowed to the column it names — not on
    # which keys happen to be in the row, and not on `str(exc)`. Keyed on
    # presence this was a universal retry that stripped `request_id` from
    # every failure; read off the exception string it never fired at all.
    #
    # A LOOP, not one retry (#482): a single migration can add several columns
    # to this insert, and a hatch that drops one and gives up fails every
    # upload in exactly the window it exists for. Bounded by the droppable
    # set, and a column named again after it was dropped is raised — the drop
    # is then not what is failing.
    for _ in range(len(_DROPPABLE_COLUMNS) + 1):
        try:
            inserted = table("documents").insert(row)
            break
        except Exception as exc:
            column = _missing_column(exc)
            if column is None or column not in row:
                raise
            logger.warning(
                "documents insert rejected %r as absent — retrying without it. "
                "The migration that adds it has not run in this environment.",
                column,
            )
            row.pop(column)
    else:  # pragma: no cover — unreachable: each pass removes a column or raises
        raise RuntimeError("documents insert kept naming absent columns")
    full_row = dict(inserted[0] if inserted else row)
    full_row.pop("extracted_text", None)
    full_row["summary"] = summary
    full_row["concept_notes"] = concept_notes
    # The documents row above is the single shared insert point for both
    # upload_document_sync and the streaming upload_document (see docstring);
    # each calls this helper exactly once per logical upload, so awarding
    # here — keyed on the freshly-inserted document id — pays out exactly
    # once per upload and is a clean idempotent no-op on any retry.
    award_xp_safe(
        user_id, "document_uploaded",
        source_type="document", source_id=full_row["id"],
    )
    # #117: one document.processed per persisted document, covering both the
    # sync and the streaming agent path. Ids/counts only — never the text,
    # summary, or concept notes.
    events_service.log_event(
        "document.processed",
        category="usage",
        user_id=user_id,
        request_id=request_id,
        payload={
            "document_id": full_row["id"],
            "category": result.classification.category,
            "course_id": course_id,
            "char_count": char_count,
        },
    )
    return full_row["id"], full_row


def _grading_categories_from(result: DocumentProcessingResult) -> list[dict]:
    """Map orchestrator GradingCategory -> legacy {name, weight} shape.

    Returns [] for non-syllabus documents or when the syllabus did not
    state a grading breakdown — matches the legacy pipeline's contract
    so the frontend's category-rendering branch sees the same shape.
    """
    if not (result.classification.is_syllabus and result.syllabus
            and result.syllabus.grading_categories):
        return []
    return [
        {"name": c.name, "weight": float(c.weight)}
        for c in result.syllabus.grading_categories
    ]


def _save_orchestrator_syllabus(*, user_id: str, course_id: str, filename: str,
                                result: DocumentProcessingResult) -> None:
    """Map SyllabusAssignment -> legacy assignments shape and persist.

    Drops entries with due_date=None per the no-invent contract.
    Best-effort: any error is logged and swallowed.
    """
    if not (result.classification.is_syllabus and result.syllabus
            and result.syllabus.assignments):
        return
    legacy: list[dict] = []
    for a in result.syllabus.assignments:
        if a.due_date is None:
            continue
        legacy.append({
            "title": a.title,
            "due_date": a.due_date.isoformat(),
            "course_id": course_id,
            "course_name": result.syllabus.course_title,
            "assignment_type": "other",
            "notes": a.description,
        })
    if legacy:
        try:
            save_assignments_to_db(user_id, legacy, source="syllabus")
        except Exception:
            logger.exception("Assignment save failed for '%s' (best-effort)", filename)


def _graph_backstop(*, user_id: str, course_id: str, filename: str,
                    result: DocumentProcessingResult) -> None:
    """Apply graph update if the orchestrator skipped its tool call."""
    if result.graph_updated:
        return
    if result.classification.category not in ("syllabus", "assignment"):
        return
    try:
        new_nodes = [
            {"concept_name": c.name, "initial_mastery": 0.0}
            for c in result.concepts.concepts
        ]
        apply_graph_update(user_id, {"new_nodes": new_nodes}, course_id=course_id)
    except Exception:
        logger.exception("Graph backstop failed for '%s' (best-effort)", filename)
