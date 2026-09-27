"""Check items: storage, sources, generation (learning loop PKG-04; spec §2,
§4, §13 A2/A22/A23/A24).

Items are COURSE assets keyed on (course_id, concept_key), where concept_key =
services/graph_service._normalize_concept(concept_name) — never a student's
graph_nodes row (A2). Nothing here writes graph_nodes (spec §8.1).

Encryption: prompt, reference_answer, rubric_json, common_wrong_json,
options_json, correct_option and canonical_answer are encrypted at write
(services/encryption.py) and decrypted at read in `_row_to_item`, the single
decrypt boundary. question_hash is the plaintext lookup key, hashed from the
PLAINTEXT prompt before encryption. No filter, order or join here ever names
an encrypted column (invariant 9).

Sources (A23): an item is drafted only from a document that is shared course
material — `chunk_visibility.decide_visibility` decides, never re-derived
here — and only from its SHARED chunks.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable

from db.connection import page_all, pg_quote_value, table
from learning.checks import (
    CheckItem,
    CheckItemDraft,
    Option,
    RubricItem,
    WrongReason,
    clean_chunk_ids,
    item_id,
    parse_tolerance,
    question_hash,
    validate_draft,
)
from services.chunk_visibility import COURSE_MATERIAL, SHARED, decide_visibility
from services.encryption import decrypt_if_present, encrypt_if_present, encrypt_json
from services.graph_service import _normalize_concept

logger = logging.getLogger("sapling.services.check_items")

_TABLE = "check_items"
_ON_CONFLICT = "course_id,concept_key,question_hash"
_MC_REASON = "mc_reason"
_NUMERIC = "numeric"
_COLUMNS = (
    "id,course_id,concept_key,document_id,format,difficulty,prompt,reference_answer,"
    "rubric_json,common_wrong_json,options_json,correct_option,answer_kind,"
    "canonical_answer,tolerance,canonical_verified,stepwise,source_chunk_ids,"
    "source_document_ids,question_hash,graded,created_at"
)

#: A24 stub for services.decisions.item_answerable (PKG-05b): "is this item
#: answerable from these passages?". Nothing in the series sets it and nothing
#: calls it — do not add a call site here.
answerable_hook: Callable[[list[str], str, str], bool] | None = None


def concept_key(name: str) -> str:
    """The A2 course concept key: graph_service's normalizer, imported."""
    return _normalize_concept(name)


# ── write ──────────────────────────────────────────────────────────────────


def _build_row(
    course_id: str,
    key: str,
    document_id: str | None,
    draft: CheckItemDraft,
    *,
    allowed: set[str],
    source_docs: list[str],
) -> dict:
    qh = question_hash(draft.prompt)  # PLAINTEXT, before encryption
    rubric = [
        {"id": f"r{i}", "text": text}
        for i, text in enumerate((t for t in draft.rubric if t.strip()), start=1)
    ]
    wrong = [{"key": k, "text": t} for k, t in zip(draft.wrong_keys, draft.wrong_texts)]
    options = None
    correct_option = None
    if draft.format == _MC_REASON:
        options = encrypt_json(
            [
                {
                    "letter": letter,
                    "text": text,
                    "wrong_key": None if letter == draft.correct_option else (key_ or None),
                }
                for letter, text, key_ in zip(
                    draft.option_letters, draft.option_texts, draft.option_wrong_keys
                )
            ]
        )
        correct_option = encrypt_if_present(draft.correct_option)
    numeric = draft.answer_kind == _NUMERIC
    return {
        "id": item_id(course_id, key, qh),
        "course_id": course_id,
        "concept_key": key,
        "document_id": document_id,
        "format": draft.format,
        "difficulty": draft.difficulty,
        "prompt": encrypt_if_present(draft.prompt),
        "reference_answer": encrypt_if_present(draft.reference_answer),
        "rubric_json": encrypt_if_present(json.dumps(rubric)),
        "common_wrong_json": encrypt_if_present(json.dumps(wrong)),
        "options_json": options,
        "correct_option": correct_option,
        "answer_kind": draft.answer_kind,
        "canonical_answer": encrypt_if_present(draft.canonical_answer) if numeric else None,
        "tolerance": parse_tolerance(draft),
        # A22: never an agent output; true only on an independent agreement
        # check or an instructor confirmation, neither of which the series builds.
        "canonical_verified": False,
        "stepwise": draft.stepwise,
        "source_chunk_ids": clean_chunk_ids(draft, allowed),
        "source_document_ids": source_docs,
        "question_hash": qh,
        # A32: every generated item is practice material, never graded coursework.
        "graded": False,
    }


def create_items(
    course_id: str,
    concept_key: str,
    document_id: str | None,
    drafts: Iterable[CheckItemDraft],
    *,
    allowed_chunk_ids: Iterable[str] = (),
    source_document_ids: Iterable[str] = (),
) -> list[str]:
    """Validate each draft (invalid → dropped + WARNING), then upsert every
    valid row in ONE call on (course_id, concept_key, question_hash). Returns
    the stored ids. Raises on a PostgREST failure (the caller logs it)."""
    allowed = set(allowed_chunk_ids)
    source_docs = sorted({d for d in source_document_ids if d})
    if not source_docs and document_id:
        source_docs = [document_id]
    rows: list[dict] = []
    seen: set[str] = set()
    for draft in drafts:
        reasons = validate_draft(draft)
        if reasons:
            logger.warning(
                "check item draft dropped (course=%s concept=%s format=%s): %s",
                course_id,
                concept_key,
                draft.format,
                "; ".join(reasons),
            )
            continue
        row = _build_row(
            course_id, concept_key, document_id, draft, allowed=allowed, source_docs=source_docs
        )
        if row["id"] in seen:
            # Same normalized prompt twice in one batch: one upsert may not
            # name a row twice (PostgREST rejects it), and it is one item.
            continue
        seen.add(row["id"])
        rows.append(row)
    if not rows:
        return []
    table(_TABLE).upsert(rows, on_conflict=_ON_CONFLICT)
    return [r["id"] for r in rows]


# ── read ───────────────────────────────────────────────────────────────────


def _json_column(row: dict, column: str, default):
    """Decrypt + json.loads one JSON column; WARNING and `default` on failure
    (a bad row never fails a read)."""
    raw = row.get(column)
    if raw is None:
        return default
    try:
        return json.loads(decrypt_if_present(raw))
    except (TypeError, ValueError):
        logger.warning("check item %s: %s is not valid JSON", row.get("id"), column)
        return default


def _hydrate(model, entries, column: str, item_id_: str):
    try:
        return [model(**e) for e in entries]
    except (TypeError, ValueError):
        logger.warning("check item %s: %s has an unexpected shape", item_id_, column)
        return None


def _row_to_item(row: dict) -> CheckItem:
    """The single decrypt boundary for check_items rows."""
    rid = row.get("id")
    rubric = _hydrate(RubricItem, _json_column(row, "rubric_json", []), "rubric_json", rid) or []
    wrong = (
        _hydrate(WrongReason, _json_column(row, "common_wrong_json", []), "common_wrong_json", rid)
        or []
    )
    options = None
    raw_options = _json_column(row, "options_json", None)
    if raw_options is not None:
        options = _hydrate(Option, raw_options, "options_json", rid)
    return CheckItem(
        id=rid,
        course_id=row.get("course_id"),
        concept_key=row.get("concept_key"),
        document_id=row.get("document_id"),
        format=row.get("format"),
        difficulty=row.get("difficulty"),
        prompt=decrypt_if_present(row.get("prompt")) or "",
        reference_answer=decrypt_if_present(row.get("reference_answer")) or "",
        rubric=rubric,
        common_wrong=wrong,
        options=options,
        correct_option=decrypt_if_present(row.get("correct_option")),
        answer_kind=row.get("answer_kind") or "free",
        canonical_answer=decrypt_if_present(row.get("canonical_answer")),
        tolerance=row.get("tolerance"),
        canonical_verified=bool(row.get("canonical_verified")),
        stepwise=bool(row.get("stepwise")),
        source_chunk_ids=list(row.get("source_chunk_ids") or []),
        question_hash=row.get("question_hash"),
        graded=bool(row.get("graded")),
        created_at=row.get("created_at"),
    )


def _to_items(rows) -> list[CheckItem]:
    items = []
    for row in rows or []:
        try:
            items.append(_row_to_item(row))
        except ValueError:
            # pydantic's ValidationError is a ValueError: a row whose plaintext
            # columns are unusable is skipped, never raised (Error semantics).
            logger.warning("check item %s could not be read; skipped", row.get("id"))
    return items


def list_items(
    course_id: str,
    concept_key: str,
    *,
    format: str | None = None,
    difficulty: int | None = None,
) -> list[CheckItem]:
    """Every item for one course concept, filtered on plaintext columns only."""
    filters = {"course_id": f"eq.{course_id}", "concept_key": f"eq.{concept_key}"}
    if format is not None:
        filters["format"] = f"eq.{format}"
    if difficulty is not None:
        filters["difficulty"] = f"eq.{difficulty}"
    rows = table(_TABLE).select(_COLUMNS, filters=filters, order="created_at,id")
    return _to_items(rows)


def items_for_concepts(course_id: str, concept_keys: Iterable[str]) -> dict[str, list[CheckItem]]:
    """Every item for the given keys, in ONE `in.(...)` select, grouped by key
    (every requested key present, [] when it has none)."""
    keys = list(dict.fromkeys(k for k in concept_keys if k))
    if not keys:
        return {}
    rows = table(_TABLE).select(
        _COLUMNS,
        filters={
            "course_id": f"eq.{course_id}",
            "concept_key": f"in.({','.join(pg_quote_value(k) for k in keys)})",
        },
        order="created_at,id",
    )
    grouped: dict[str, list[CheckItem]] = {k: [] for k in keys}
    for item in _to_items(rows):
        grouped.setdefault(item.concept_key, []).append(item)
    return grouped


def course_has_items(course_id: str) -> bool:
    """Whether the course has any item (feeds /probe/next's no_check_items and
    the A26 "No check items for this course yet" state)."""
    rows = table(_TABLE).select("id", filters={"course_id": f"eq.{course_id}"}, limit=1)
    return bool(rows)


def count_items(course_id: str, concept_key: str) -> int:
    rows = table(_TABLE).select(
        "id", filters={"course_id": f"eq.{course_id}", "concept_key": f"eq.{concept_key}"}
    )
    return len(rows or [])


class _GraphNodesRead:
    """A read-only `page_all` handle over graph_nodes. Invariant 1 (PKG-03's
    ast half) allows `table("graph_nodes")` only as a direct `.select` /
    `.select_with_count` read, so the handle is never passed around: every
    page is one direct read, and page_all's paging contract is reused as is."""

    def select_with_count(self, *args, **kwargs):
        return table("graph_nodes").select_with_count(*args, **kwargs)


def coverage(course_id: str) -> tuple[int, int]:
    """(concept keys of the course's graph_nodes that have >= 1 item, concept
    keys of the course's graph_nodes). Both reads page with a total order."""
    scope = {"course_id": f"eq.{course_id}"}
    concepts = {
        concept_key(r.get("concept_name") or "")
        for r in page_all(_GraphNodesRead(), "concept_name", filters=scope, order="id")
    }
    concepts.discard("")
    with_items = {
        r.get("concept_key")
        for r in page_all(table(_TABLE), "concept_key", filters=scope, order="id")
    }
    return len(concepts & with_items), len(concepts)


# ── sources (A23 privacy) ──────────────────────────────────────────────────


def chunks_for_document(document_id: str) -> list[dict]:
    """The document's course_chunks rows by doc_id, chunk_text decrypted (the
    boundary rag_service.retrieve_chunks_detailed owns for similarity reads)."""
    rows = table("course_chunks").select(
        "id,chunk_index,chunk_text,visibility,doc_id",
        filters={"doc_id": f"eq.{document_id}"},
        order="chunk_index",
    )
    out = []
    for row in rows or []:
        chunk = dict(row)
        chunk["chunk_text"] = decrypt_if_present(chunk.get("chunk_text"))
        out.append(chunk)
    return out


def document_is_item_source(row: dict) -> bool:
    """Shared course material only: the stored shareability is course_material
    AND chunk_visibility.decide_visibility (confidence floor + the uploader's
    stored consent, #629/#630) says SHARED."""
    if row.get("shareability") != COURSE_MATERIAL:
        return False
    return (
        decide_visibility(
            row["user_id"],
            shareability=row.get("shareability"),
            confidence=row.get("shareability_confidence"),
        )
        == SHARED
    )


def source_chunks(doc_row: dict) -> list[dict]:
    """The passages an item may be drafted from. Not a source → []. Indexed →
    its SHARED chunks only (none shared → [], never the fallback). Not indexed
    → its decrypted extracted_text as ONE passage with no id. Every passage
    carries its `doc_id`."""
    doc_id = doc_row.get("id")
    if not document_is_item_source(doc_row):
        logger.info("check items: document %s is not shared course material; skipped", doc_id)
        return []
    rows = chunks_for_document(doc_id)
    if rows:
        shared = [
            dict(r, doc_id=r.get("doc_id") or doc_id) for r in rows if r.get("visibility") == SHARED
        ]
        if not shared:
            logger.info("check items: document %s has no shared chunks; skipped", doc_id)
        return shared
    text = decrypt_if_present(doc_row.get("extracted_text"))
    if not text or not str(text).strip():
        logger.warning("check items: document %s has no chunks and no extracted text", doc_id)
        return []
    return [{"id": None, "chunk_index": 0, "chunk_text": text, "doc_id": doc_id}]
