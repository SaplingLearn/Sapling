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
from typing import NamedTuple

import config
from agents._run import run_agent_sync
from agents.check_items import CheckItemsUnavailable, draft_items
from agents.deps import SaplingDeps
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
    rank_chunks_for_concept,
    validate_draft,
)
from learning.params import (
    CHECK_ITEM_CONCEPTS_PER_CALL,
    CHECK_ITEM_INITIAL_PER_CONCEPT,
    CHECK_ITEM_MAX_CHUNKS,
    CHECK_ITEM_MAX_CONCEPTS_PER_DOC,
)
from services.chunk_visibility import COURSE_MATERIAL, SHARED, decide_visibility
from services.encryption import decrypt_if_present, encrypt_if_present, encrypt_json
from services.events_service import log_event
from services.graph_service import _normalize_concept
from services.request_context import current_request_id

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


# ── withdrawal (A23): consent stays answerable for items ──────────────────
#
# NOT gated on LEARNING_LOOP_ENABLED: withdrawal must hold under the kill
# switch too, and with no items it is one cheap no-op delete.

#: Document ids per `ov.{…}` filter. The filter rides in the query string, so
#: an unbounded list is an unbounded URL; the same bound and rationale as
#: chunk_visibility's `in.(…)` batches (#629).
_DOC_ID_BATCH = 50


def retire_items_for_documents(document_ids: Iterable[str]) -> int:
    """DELETE every item whose source_document_ids overlaps `document_ids`;
    returns how many went. Logs the count only (no event, no text)."""
    ids = [d for d in dict.fromkeys(document_ids) if d]
    if not ids:
        return 0
    retired = 0
    for start in range(0, len(ids), _DOC_ID_BATCH):
        batch = ids[start : start + _DOC_ID_BATCH]
        rows = table(_TABLE).delete(
            filters={
                "source_document_ids": "ov.{" + ",".join(pg_quote_value(d) for d in batch) + "}",
                "select": "id",  # the deleted rows come back as ids only
            }
        )
        retired += len(rows or [])
    logger.info("check items retired: %d (documents: %d)", retired, len(ids))
    return retired


def retire_items_for_uploader(user_id: str) -> int:
    """Retire every item drafted from any document `user_id` uploaded (soft-
    deleted ones included) — the share_class_context opt-out (A23)."""
    ids = [
        r["id"]
        for r in page_all(
            table("documents"), "id", filters={"user_id": f"eq.{user_id}"}, order="id"
        )
        if r.get("id")
    ]
    return retire_items_for_documents(ids)


# ── generation (flag-gated; spec §7: course level, never one student's gate) ─


class GenerationOutcome(NamedTuple):
    items_created: int
    concepts_attempted: int
    unavailable: int
    concepts_skipped: int
    concepts_unmatched: int = 0


_NOTHING = GenerationOutcome(0, 0, 0, 0)
_FAILED_EVENT = "learn.check_items_failed"
_STORAGE_ERROR = "StorageError"


def _report_failure(
    user_id: str | None, document_id: str | None, course_id: str, reason: str
) -> None:
    log_event(
        _FAILED_EVENT,
        category="error",
        user_id=user_id,
        payload={"document_id": document_id, "course_id": course_id, "reason": reason},
    )


def _passage_key(chunk: dict):
    """De-duplication key of a passage: its chunk id, or — for an unindexed
    document's one id-less fallback passage — its document."""
    return chunk.get("id") or ("fallback", chunk.get("doc_id"), chunk.get("chunk_index"))


def generate_for_concepts(
    *,
    user_id: str | None,
    course_id: str,
    concept_names: Iterable[str],
    chunks: list[dict],
    flex: bool,
    document_id: str | None = None,
    max_concepts: int | None = None,
    min_chunk_score: int = 0,
) -> GenerationOutcome:
    """Draft items for the course concepts that still lack them, from `chunks`.

    Inert (zeros, no read, no agent) when LEARNING_LOOP_ENABLED is off or
    there is nothing to write from. Otherwise: names de-duplicated by
    concept_key (first name wins), the first `max_concepts` kept, every key
    already at CHECK_ITEM_INITIAL_PER_CONCEPT items skipped BEFORE any agent
    call, every key no passage scores >= `min_chunk_score` for dropped
    (A23 relevance floor), the rest drafted CHECK_ITEM_CONCEPTS_PER_CALL per
    agent call. Synchronous: it runs in a worker thread with no event loop.
    `user_id=None` (the backfill) records usage against the system actor."""
    if not config.LEARNING_LOOP_ENABLED:
        return _NOTHING
    if not chunks:
        logger.info("check items: no source passages for course %s; nothing to draft", course_id)
        return _NOTHING

    names_by_key: dict[str, str] = {}
    for name in concept_names:
        key = concept_key(name)
        if key and key not in names_by_key:
            names_by_key[key] = name
    keys = list(names_by_key)
    if max_concepts is not None:
        keys = keys[:max_concepts]

    skipped = unmatched = 0
    todo: list[tuple[str, str, list[dict]]] = []
    for key in keys:
        if count_items(course_id, key) >= CHECK_ITEM_INITIAL_PER_CONCEPT:
            skipped += 1
            continue
        ranked = rank_chunks_for_concept(
            names_by_key[key], chunks, limit=CHECK_ITEM_MAX_CHUNKS, min_score=min_chunk_score
        )
        if not ranked:
            unmatched += 1
            continue
        todo.append((key, names_by_key[key], ranked))

    deps = SaplingDeps(
        user_id=user_id or "",
        course_id=course_id,
        supabase=None,
        request_id=current_request_id() or f"check_items:{document_id or course_id}",
        feature="check_items",
    )
    created = attempted = unavailable = 0
    for start in range(0, len(todo), CHECK_ITEM_CONCEPTS_PER_CALL):
        batch = todo[start : start + CHECK_ITEM_CONCEPTS_PER_CALL]
        names = [name for _, name, _ in batch]
        passages: list[dict] = []
        seen: set = set()
        # A23 provenance is the CALL's, not one concept's: the model sees the
        # union of the batch's passages, so any item may be drafted from (and
        # cite) any of them. Every concept of the call records every document
        # it showed, and citations are kept only for passages it showed — so
        # withdrawing any of those documents reaches every item of the call.
        shown_docs: set[str] = set()
        allowed: set[str] = set()
        for _, _, ranked in batch:
            for chunk in ranked:
                pkey = _passage_key(chunk)
                if pkey in seen:
                    continue
                seen.add(pkey)
                passages.append({"id": chunk.get("id"), "text": chunk.get("chunk_text") or ""})
                if chunk.get("doc_id"):
                    shown_docs.add(chunk["doc_id"])
                if chunk.get("id"):
                    allowed.add(chunk["id"])
        source_docs = sorted(shown_docs)

        out = run_agent_sync(draft_items(names, passages, deps=deps, flex=flex))
        attempted += len(batch)
        if isinstance(out, CheckItemsUnavailable):
            _report_failure(user_id, document_id, course_id, out.reason)
            unavailable += len(batch)
            continue

        drafts_by_key: dict[str, list[CheckItemDraft]] = {key: [] for key, _, _ in batch}
        for draft in out.items:
            dkey = concept_key(draft.concept)
            if dkey in drafts_by_key:
                drafts_by_key[dkey].append(draft)
            else:
                logger.warning(
                    "check item draft for %r is outside the call's concepts %s; dropped",
                    draft.concept,
                    names,
                )
        for key, _, _ in batch:
            try:
                created += len(
                    create_items(
                        course_id,
                        key,
                        document_id,
                        drafts_by_key[key],
                        allowed_chunk_ids=allowed,
                        source_document_ids=source_docs,
                    )
                )
            except Exception:
                logger.warning(
                    "check items write failed (course=%s concept=%s)", course_id, key, exc_info=True
                )
                _report_failure(user_id, document_id, course_id, _STORAGE_ERROR)

    outcome = GenerationOutcome(created, attempted, unavailable, skipped, unmatched)
    logger.info(
        "check items: course=%s document=%s items=%d attempted=%d unavailable=%d "
        "skipped=%d unmatched=%d",
        course_id,
        document_id,
        *outcome,
    )
    return outcome


def generate_for_document(
    document_id: str,
    *,
    user_id: str,
    course_id: str,
    concept_names: Iterable[str],
    flex: bool,
) -> GenerationOutcome:
    """The upload hook's generation: the document's source passages (A23 —
    shared course material only), then at most CHECK_ITEM_MAX_CONCEPTS_PER_DOC
    of its concepts. Usage is attributed to the uploader."""
    if not config.LEARNING_LOOP_ENABLED:
        return _NOTHING
    rows = table("documents").select(
        "id,user_id,shareability,shareability_confidence,extracted_text",
        filters={"id": f"eq.{document_id}", "deleted_at": "is.null"},
        limit=1,
    )
    if not rows:
        logger.warning("check items: document %s not found; nothing drafted", document_id)
        return _NOTHING
    chunks = source_chunks(rows[0])
    if not chunks:
        return _NOTHING
    return generate_for_concepts(
        user_id=user_id,
        course_id=course_id,
        concept_names=concept_names,
        chunks=chunks,
        flex=flex,
        document_id=document_id,
        max_concepts=CHECK_ITEM_MAX_CONCEPTS_PER_DOC,
    )
