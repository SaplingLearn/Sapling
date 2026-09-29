"""Check items: storage, sources, generation (learning loop PKG-04; spec §2,
§4, §13 A2/A22/A23/A24).

Items are COURSE assets keyed on (course_id, concept_key), where concept_key =
services/graph_service._normalize_concept(concept_name) — never a student's
graph_nodes row (A2). Nothing here writes graph_nodes (spec §8.1).

Encryption: prompt, reference_answer, rubric_json, common_wrong_json,
options_json, correct_option, canonical_answer and final_answer (A34) are
encrypted at write (services/encryption.py) and decrypted at read in
`_row_to_item`, the single decrypt boundary. question_hash is the plaintext lookup key, hashed from the
PLAINTEXT prompt before encryption. No filter, order or join here ever names
an encrypted column (invariant 9).

Sources (A23): an item is drafted only from a document that is shared course
material — `chunk_visibility.decide_visibility` decides, never re-derived
here — and only from its SHARED chunks.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

import config
from agents._run import run_agent_sync
from agents.check_items import CheckItemsUnavailable, draft_items
from agents.check_items_topup import draft_mc_topup
from agents.deps import SaplingDeps
from db.connection import page_all, pg_quote_value, table
from learning.checks import (
    CheckItem,
    CheckItemDraft,
    Option,
    RubricItem,
    WrongReason,
    clean_chunk_ids,
    common_wrong,
    item_id,
    lettered_options,
    parse_tolerance,
    question_hash,
    rank_chunks_for_concept,
    repair_draft,
    stored_rubric,
    validate_draft,
)
from learning.params import (
    CHECK_ITEM_CONCEPTS_PER_CALL,
    CHECK_ITEM_DIFFICULTIES,
    CHECK_ITEM_DRAFT_WORKERS,
    CHECK_ITEM_INITIAL_PER_CONCEPT,
    CHECK_ITEM_MAX_CHUNKS,
    CHECK_ITEM_MAX_CONCEPTS_PER_DOC,
    CHECK_ITEM_MC_MIN_PER_CONCEPT,
    CHECK_ITEM_MC_TOPUP_CALLS,
    CHECK_ITEM_REDRAFT_FAILURE_TTL_DAYS,
    CHECK_ITEM_REDRAFT_MAX_FAILURES,
)
from services.chunk_visibility import COURSE_MATERIAL, SHARED, _share_flags, decide_visibility
from services.chunker import chunk_document
from services.encryption import (
    decrypt_if_present,
    derive_key,
    encrypt_if_present,
    encrypt_json,
)
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
    "source_document_ids,question_hash,graded,created_at,final_answer"
)

#: What derive_key names the secret the correct mc_reason option's slot is
#: keyed with (A37): the client is sent each item's question_hash, so the slot
#: must not be computable from it alone.
OPTION_SLOT_PURPOSE = "check_items.option_slot.v1"

#: A24 stub for services/decisions.py::item_answerable (PKG-05b): "is this item
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
    # A37 review: an mc_reason rubric ends with code's reason criterion.
    rubric = [r.model_dump() for r in stored_rubric(draft)]
    # A37: an mc_reason item's wrong reasons are its distractors' misconceptions,
    # the keys its stored options carry; free and teachback pair their lists.
    wrong = [w.model_dump() for w in common_wrong(draft)]
    options = None
    correct_option = None
    if draft.format == _MC_REASON:
        # A37: code letters the options and places the correct one at a slot
        # keyed by the server secret; the stored shape ([{letter, text,
        # wrong_key}] + the letter) is what the grader and the routes read.
        lettered, letter = lettered_options(draft, slot_key=derive_key(OPTION_SLOT_PURPOSE))
        options = encrypt_json([o.model_dump() for o in lettered])
        correct_option = encrypt_if_present(letter)
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
        # A34: stated by the generator, verbatim from the reference; validated.
        "final_answer": encrypt_if_present(draft.final_answer),
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


# A top-up draft whose prompt a stored item of the concept already has (A37).
_REPEAT = "repeat: the prompt is a stored item's"


class _ConceptWrite(NamedTuple):
    """What one concept's write stored and dropped."""

    ids: list[str]  # the rows upserted
    mc_reason: dict[str, int]  # of those, the mc_reason rows: id -> difficulty
    mc_drops: list[str]  # each dropped mc_reason draft's reasons, "; "-joined


def _store_drafts(
    course_id: str,
    concept_key: str,
    document_id: str | None,
    drafts: Iterable[CheckItemDraft],
    *,
    allowed_chunk_ids: Iterable[str] = (),
    source_document_ids: Iterable[str] = (),
    limit: int | None = None,
    exclude_ids: Iterable[str] = (),
) -> _ConceptWrite:
    """create_items, saying what it stored and why each mc_reason draft was
    dropped (the A37 top-up feeds those reasons back). `limit` caps the valid
    rows stored (the top-up's missing count); the rest are logged, not stored.
    A draft whose row id is in `exclude_ids` (the top-up's stored items: the
    id is the prompt's question_hash) is a repeat: dropped before `limit`
    counts it, so it never rewrites the stored item or takes a new one's slot."""
    allowed = set(allowed_chunk_ids)
    exclude = set(exclude_ids)
    source_docs = sorted({d for d in source_document_ids if d})
    if not source_docs and document_id:
        source_docs = [document_id]
    rows: list[dict] = []
    seen: set[str] = set()
    mc_drops: list[str] = []
    surplus = repeats = 0
    for draft in drafts:
        draft, repairs = repair_draft(draft)
        if repairs:
            logger.info(
                "check item draft repaired (course=%s concept=%s format=%s): %s",
                course_id,
                concept_key,
                draft.format,
                "; ".join(repairs),
            )
        reasons = validate_draft(draft)
        if reasons:
            logger.warning(
                "check item draft dropped (course=%s concept=%s format=%s): %s",
                course_id,
                concept_key,
                draft.format,
                "; ".join(reasons),
            )
            if draft.format == _MC_REASON:
                mc_drops.append("; ".join(reasons))
            continue
        row = _build_row(
            course_id, concept_key, document_id, draft, allowed=allowed, source_docs=source_docs
        )
        if row["id"] in seen:
            # Same normalized prompt twice in one batch: one upsert may not
            # name a row twice (PostgREST rejects it), and it is one item.
            continue
        if row["id"] in exclude:
            repeats += 1
            if draft.format == _MC_REASON:
                mc_drops.append(_REPEAT)
            continue
        if limit is not None and len(rows) >= limit:
            surplus += 1
            continue
        seen.add(row["id"])
        rows.append(row)
    if repeats:
        logger.info(
            "check items: %d draft(s) repeat a stored item's prompt; not stored "
            "(course=%s concept=%s)",
            repeats,
            course_id,
            concept_key,
        )
    if surplus:
        logger.info(
            "check items: %d valid draft(s) beyond the %d asked for; not stored "
            "(course=%s concept=%s)",
            surplus,
            limit,
            course_id,
            concept_key,
        )
    if rows:
        table(_TABLE).upsert(rows, on_conflict=_ON_CONFLICT)
    return _ConceptWrite(
        [r["id"] for r in rows],
        {r["id"]: r["difficulty"] for r in rows if r["format"] == _MC_REASON},
        mc_drops,
    )


def create_items(
    course_id: str,
    concept_key: str,
    document_id: str | None,
    drafts: Iterable[CheckItemDraft],
    *,
    allowed_chunk_ids: Iterable[str] = (),
    source_document_ids: Iterable[str] = (),
) -> list[str]:
    """Repair each draft where no guess is needed (A37; logged at INFO by
    rule), validate it (invalid → dropped + WARNING naming every rule), then
    upsert every valid row in ONE call on (course_id, concept_key,
    question_hash). Returns the stored ids. Raises on a PostgREST failure (the
    caller logs it)."""
    return _store_drafts(
        course_id,
        concept_key,
        document_id,
        drafts,
        allowed_chunk_ids=allowed_chunk_ids,
        source_document_ids=source_document_ids,
    ).ids


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
        # A34: None on a legacy row — checks.is_servable keeps it from being served.
        final_answer=decrypt_if_present(row.get("final_answer")),
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
    boundary rag_service.retrieve_chunks_detailed owns for similarity reads).
    Paged: a textbook can index to more chunks than PostgREST's max_rows, and
    an unpaged select truncates silently."""
    rows = page_all(
        table("course_chunks"),
        "id,chunk_index,chunk_text,visibility,doc_id",
        filters={"doc_id": f"eq.{document_id}"},
        order="chunk_index,id",
    )
    out = []
    for row in rows:
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
    → its decrypted extracted_text, split by the indexer's block chunker into
    id-less passages (chunk_index 0, 1, …), so ranking bounds what each agent
    call carries exactly as for an indexed document — never the whole text in
    every batch. Every passage carries its `doc_id`."""
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
    return [
        {"id": None, "chunk_index": i, "chunk_text": piece, "doc_id": doc_id}
        for i, piece in enumerate(chunk_document(str(text)))
    ]


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


def items_missing_final_answer(course_id: str) -> dict[str, list[str]]:
    """A34: the course's rows drafted before check_items.final_answer existed
    (the column is NULL), as {concept_key: [item ids]} in id order. Reads ids
    and keys, and final_answer only to see that it is NULL — never decrypted,
    never filtered on (invariant 9), and no reference text is read: a final
    answer is never derived from a reference, the concept is redrafted."""
    missing: dict[str, list[str]] = {}
    for row in page_all(
        table(_TABLE),
        "id,concept_key,final_answer",
        filters={"course_id": f"eq.{course_id}"},
        order="id",
    ):
        if row.get("final_answer") is None and row.get("id"):
            missing.setdefault(row.get("concept_key"), []).append(row["id"])
    return missing


def retire_items_by_id(item_ids: Iterable[str]) -> int:
    """DELETE the given items (_DOC_ID_BATCH ids per `in.(…)`); returns how
    many went. The A34 backfill mode retires rows without a final_answer this
    way before it redrafts their concepts; nothing serves them either way."""
    ids = [i for i in dict.fromkeys(item_ids) if i]
    retired = 0
    for start in range(0, len(ids), _DOC_ID_BATCH):
        batch = ids[start : start + _DOC_ID_BATCH]
        rows = table(_TABLE).delete(
            filters={
                "id": "in.(" + ",".join(pg_quote_value(i) for i in batch) + ")",
                "select": "id",
            }
        )
        retired += len(rows or [])
    if ids:
        logger.info("check items retired by id: %d", retired)
    return retired


def _withdrawn_sources(document_ids: Iterable[str]) -> list[str]:
    """The ids among `document_ids` withdrawn since they were read as sources:
    deleted, or their uploader's stored `share_class_context` is now false —
    A23's two withdrawal triggers. Raises on ANY failed read.

    Consent is read through chunk_visibility's raising batch read
    (`_share_flags`: no row = opted in, only an explicit false opts out), not
    through `document_is_item_source`: its consent read
    (`shares_class_context`) answers a PostgREST failure with "opted out"
    (#629's fail-closed indexing rule), which here would turn a blip into a
    withdrawal — and a post-write withdrawal DELETES every item citing the
    document, older ones included. The rest of the source rule is not re-read:
    `shareability` and its confidence are written once (the upload's persist,
    or the NULL-only shareability backfill), so a document `decide_visibility`
    passed stays past that gate. One `in.(…)` documents read per
    _DOC_ID_BATCH ids, then one user_settings read per 50 uploaders."""
    ids = sorted({d for d in document_ids if d})
    live: dict[str, str] = {}
    for start in range(0, len(ids), _DOC_ID_BATCH):
        batch = ids[start : start + _DOC_ID_BATCH]
        rows = table("documents").select(
            "id,user_id",
            filters={
                "id": "in.(" + ",".join(pg_quote_value(d) for d in batch) + ")",
                "deleted_at": "is.null",
            },
        )
        for row in rows or []:
            live[row["id"]] = row.get("user_id")
    consent = _share_flags(u for u in live.values() if u)
    return [d for d in ids if d not in live or not consent.get(live[d], True)]


def retire_items_for_uploader(user_id: str) -> int:
    """Retire every item drafted from any document `user_id` uploaded (soft-
    deleted ones included) — the share_class_context opt-out (A23).

    Raises nothing. It runs as a post-response BackgroundTask, where an
    exception would vanish after the 200: the student would see the opt-out
    succeed while their items stayed in the class pool. A failure is logged at
    ERROR and emitted as `learn.check_items_failed` (reason WithdrawalError),
    the way chunk_visibility.resync_user_chunk_visibility reports its own; the
    call is idempotent, so an operator can re-run it. Returns 0 then."""
    try:
        ids = [
            r["id"]
            for r in page_all(
                table("documents"), "id", filters={"user_id": f"eq.{user_id}"}, order="id"
            )
            if r.get("id")
        ]
        return retire_items_for_documents(ids)
    except Exception:
        logger.error(
            "check items: opt-out withdrawal FAILED for user %s — items drafted from "
            "their documents are still in the class pool (A23)",
            user_id,
            exc_info=True,
        )
        _report_failure(user_id, None, None, _WITHDRAWAL_ERROR)
        return 0


# ── generation (flag-gated; spec §7: course level, never one student's gate) ─


class GenerationOutcome(NamedTuple):
    items_created: int
    concepts_attempted: int
    unavailable: int
    concepts_skipped: int
    concepts_unmatched: int = 0


_NOTHING = GenerationOutcome(0, 0, 0, 0)
_FAILED_EVENT = "learn.check_items_failed"
_TOPUP_EVENT = "learn.check_items_topup"
_STORAGE_ERROR = "StorageError"
_WITHDRAWAL_ERROR = "WithdrawalError"


def _report_failure(
    user_id: str | None, document_id: str | None, course_id: str | None, reason: str
) -> None:
    log_event(
        _FAILED_EVENT,
        category="error",
        user_id=user_id,
        payload={"document_id": document_id, "course_id": course_id, "reason": reason},
    )


def _recheck_sources(
    source_docs: list[str], *, user_id: str | None, document_id: str | None, course_id: str
) -> list[str] | None:
    """`_withdrawn_sources`, or None when the re-read failed — logged and
    reported as StorageError. The caller drops the call's drafts on either
    answer (fail closed), but only a real withdrawal leaves the run's later
    batches: a blip is not a withdrawal."""
    try:
        return _withdrawn_sources(source_docs)
    except Exception:
        logger.warning(
            "check items: source re-check failed (course=%s); drafts dropped",
            course_id,
            exc_info=True,
        )
        _report_failure(user_id, document_id, course_id, _STORAGE_ERROR)
        return None


def _passage_key(chunk: dict):
    """De-duplication key of a passage: its chunk id, or — for an unindexed
    document's one id-less fallback passage — its document."""
    return chunk.get("id") or ("fallback", chunk.get("doc_id"), chunk.get("chunk_index"))


class _CallSources(NamedTuple):
    """What one agent call is shown, and the A23 provenance that follows."""

    passages: list[dict]  # [{id, text}] as the agent reads them
    allowed: set[str]  # chunk ids a draft may cite
    source_docs: list[str]  # every document whose passages the call showed


def _call_sources(ranked_lists: Iterable[list[dict]]) -> _CallSources:
    """The union of the given concepts' ranked passages, de-duplicated. A23
    provenance is the CALL's, not one concept's: the model sees every passage
    of the call, so any item may be drafted from (and cite) any of them. Every
    concept of the call records every document it showed, and citations are
    kept only for passages it showed — so withdrawing any of those documents
    reaches every item of the call."""
    passages: list[dict] = []
    seen: set = set()
    shown_docs: set[str] = set()
    allowed: set[str] = set()
    for ranked in ranked_lists:
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
    return _CallSources(passages, allowed, sorted(shown_docs))


class _CallWrite(NamedTuple):
    stored: dict[str, _ConceptWrite]  # per concept whose write ran
    recheck_failed: bool = False  # the pre-write re-check failed: drafts dropped
    withdrawn: bool = False  # a source was withdrawn: drafts dropped, or items retired


def _write_checked(
    drafts_by_key: dict[str, list[CheckItemDraft]],
    sources: _CallSources,
    *,
    gone: set[str],
    user_id: str | None,
    document_id: str | None,
    course_id: str,
    limit: int | None = None,
    exclude_ids: Iterable[str] = (),
) -> _CallWrite:
    """One call's write, with A23's source re-check on both sides of it. A
    concept whose write fails is reported (StorageError) and left out of
    `stored`; a withdrawn source is added to `gone`."""
    # A23: the sources were read before a call that can take minutes. A
    # document deleted or opted out meanwhile had its items retired while
    # these did not exist yet, so re-check right before writing...
    recheck = {"user_id": user_id, "document_id": document_id, "course_id": course_id}
    withdrawn = _recheck_sources(sources.source_docs, **recheck)
    if withdrawn is None:
        return _CallWrite({}, recheck_failed=True)
    if withdrawn:
        gone.update(withdrawn)
        logger.info(
            "check items: %d source document(s) withdrawn while drafting; "
            "the call's drafts are dropped (course=%s)",
            len(withdrawn),
            course_id,
        )
        return _CallWrite({}, withdrawn=True)
    stored: dict[str, _ConceptWrite] = {}
    for key, drafts in drafts_by_key.items():
        try:
            stored[key] = _store_drafts(
                course_id,
                key,
                document_id,
                drafts,
                allowed_chunk_ids=sources.allowed,
                source_document_ids=sources.source_docs,
                limit=limit,
                exclude_ids=exclude_ids,
            )
        except Exception:
            logger.warning(
                "check items write failed (course=%s concept=%s)", course_id, key, exc_info=True
            )
            _report_failure(user_id, document_id, course_id, _STORAGE_ERROR)
    # ...and once more after it: a withdrawal that landed between that
    # read and the upsert found nothing to delete, so retire it here. A
    # failure here is reported, never answered by deleting: the sources
    # were live a moment ago, and retiring on a blip would also delete
    # every older item citing them.
    retired = False
    if any(w.ids for w in stored.values()):
        try:
            withdrawn = _withdrawn_sources(sources.source_docs)
            if withdrawn:
                gone.update(withdrawn)
                retire_items_for_documents(withdrawn)
                retired = True
        except Exception:
            logger.error(
                "check items: post-write source re-check failed (course=%s)",
                course_id,
                exc_info=True,
            )
            _report_failure(user_id, document_id, course_id, _STORAGE_ERROR)
    return _CallWrite(stored, withdrawn=retired)


def _stored_items(course_id: str, key: str) -> dict[str, tuple[str | None, int | None]]:
    """The concept's stored items, id -> (format, difficulty) (plaintext
    columns only, invariant 9)."""
    rows = table(_TABLE).select(
        "id,format,difficulty",
        filters={"course_id": f"eq.{course_id}", "concept_key": f"eq.{key}"},
    )
    return {r["id"]: (r.get("format"), r.get("difficulty")) for r in rows or [] if r.get("id")}


def _report_topup(
    user_id: str | None,
    document_id: str | None,
    course_id: str,
    *,
    requested: int,
    returned: int,
    stored: int,
    mc_reason_items: int,
) -> None:
    """One `learn.check_items_topup` per top-up call: ids and counts only."""
    log_event(
        _TOPUP_EVENT,
        category="usage",
        user_id=user_id,
        payload={
            "document_id": document_id,
            "course_id": course_id,
            "requested": requested,
            "returned": returned,
            "stored": stored,
            "mc_reason_items": mc_reason_items,
        },
    )


def _top_up_mc_reason(
    key: str,
    name: str,
    ranked: list[dict],
    first: _ConceptWrite,
    *,
    deps: SaplingDeps,
    flex: bool,
    gone: set[str],
    user_id: str | None,
    document_id: str | None,
    course_id: str,
) -> int:
    """A37 (series coordinator's ruling, 2026-09-28): a concept this pass
    drafted that ends it with fewer than CHECK_ITEM_MC_MIN_PER_CONCEPT stored
    mc_reason items gets up to CHECK_ITEM_MC_TOPUP_CALLS focused calls, each
    for exactly the missing count at difficulties the concept lacks, shown
    the concept's own passages and told why its mc_reason drafts were
    dropped. The drafts pass the same repair and validation (no rule is
    relaxed), the write the same A23 re-checks. The count is the one read
    after the pass's write, which alone says what the concept holds (a pass
    item retired meanwhile is not counted); a top-up draft whose prompt a
    stored item already has is a repeat, not stored. Each call is billed by
    the agent (llm_usage feature check_items_topup) and counted here
    (`learn.check_items_topup`). A concept still below is logged with its drop
    reasons and left to a later generation run or backfill, which drafts it
    again only while it has fewer than CHECK_ITEM_INITIAL_PER_CONCEPT items.
    Returns the items the top-up stored."""
    if len(first.mc_reason) >= CHECK_ITEM_MC_MIN_PER_CONCEPT:
        return 0  # this pass alone stored enough: no read, no call
    try:
        stored_items = _stored_items(course_id, key)
    except Exception:
        logger.warning(
            "check items: mc_reason count read failed (course=%s concept=%s); no top-up",
            course_id,
            key,
            exc_info=True,
        )
        _report_failure(user_id, document_id, course_id, _STORAGE_ERROR)
        return 0
    have = {i: d for i, (fmt, d) in stored_items.items() if fmt == _MC_REASON}
    exclude = set(stored_items)
    drops = list(first.mc_drops)
    created = calls = 0
    recheck = {"user_id": user_id, "document_id": document_id, "course_id": course_id}
    while calls < CHECK_ITEM_MC_TOPUP_CALLS:
        missing = CHECK_ITEM_MC_MIN_PER_CONCEPT - len(have)
        live = [c for c in ranked if c.get("doc_id") not in gone]
        if missing <= 0 or not live:
            break
        calls += 1
        lacking = [d for d in CHECK_ITEM_DIFFICULTIES if d not in set(have.values())]
        difficulties = (lacking + list(CHECK_ITEM_DIFFICULTIES))[:missing]
        sources = _call_sources([live])
        out = run_agent_sync(
            draft_mc_topup(
                name,
                sources.passages,
                difficulties=difficulties,
                drop_reasons=drops,
                deps=deps,
                flex=flex,
            )
        )
        if isinstance(out, CheckItemsUnavailable):
            _report_failure(user_id, document_id, course_id, out.reason)
            _report_topup(
                user_id,
                document_id,
                course_id,
                requested=missing,
                returned=0,
                stored=0,
                mc_reason_items=len(have),
            )
            continue
        mine = [d for d in out.items if concept_key(d.concept) == key and d.format == _MC_REASON]
        if len(mine) < len(out.items):
            logger.info(
                "check items: %d top-up draft(s) not mc_reason for %r; dropped",
                len(out.items) - len(mine),
                name,
            )
        write = _write_checked(
            {key: mine}, sources, gone=gone, limit=missing, exclude_ids=exclude, **recheck
        )
        result = write.stored.get(key)
        stored = len(result.ids) if result is not None else 0
        created += stored  # as the pass counts its own: written, even if retired right after
        if result is not None and not write.withdrawn:
            have.update(result.mc_reason)
            exclude.update(result.ids)
            drops += result.mc_drops
        _report_topup(
            user_id,
            document_id,
            course_id,
            requested=missing,
            returned=len(mine),
            stored=stored,
            mc_reason_items=len(have),
        )
    if len(have) < CHECK_ITEM_MC_MIN_PER_CONCEPT:
        logger.warning(
            "check items: concept %r ends the pass with %d mc_reason item(s), below %d, "
            "after %d top-up call(s) (course=%s); a later run drafts it again only while "
            "it has fewer than %d items; drop reasons: %s",
            key,
            len(have),
            CHECK_ITEM_MC_MIN_PER_CONCEPT,
            calls,
            course_id,
            CHECK_ITEM_INITIAL_PER_CONCEPT,
            " | ".join(drops) or "none (too few mc_reason drafts returned)",
        )
    return created


# ── bounded redrafting (owner decision A38, low-severity 2) ─────────────────
#
# A concept whose drafts always fail was redrafted on every upload and every
# backfill. check_item_draft_failures counts its consecutive failed passes
# against a fingerprint of what it is drafted from (its passages, the drafting
# prompts' versions and the model); at CHECK_ITEM_REDRAFT_MAX_FAILURES on an
# unchanged source it is skipped for CHECK_ITEM_REDRAFT_FAILURE_TTL_DAYS after
# its last failure, then drafted once more. A pass that stores an item resets
# the count; a changed source (or prompt, or model) starts it over. The
# bookkeeping fails open: an error reading or writing it drafts as before.
#
# What counts (A38 fix round, M2) is an ALLOWLIST of the concept's OWN
# outcomes: a one-concept call whose output never validated
# (_CONCEPT_FAILURE_REASONS), or a call that answered but stored nothing for
# that concept. A timeout, a transport or API error, a usage limit, any other
# exception, and every failure of a multi-concept call count for no concept.

_FAILURES_TABLE = "check_item_draft_failures"
_FAILURES_ON_CONFLICT = "course_id,concept_key"
# The only Unavailable reason that is the drafts' fault: the output failed
# validation on every retry (pydantic-ai raises UnexpectedModelBehavior).
_CONCEPT_FAILURE_REASONS = frozenset({"UnexpectedModelBehavior"})


def _drafting_version() -> str:
    """The drafting prompts' versions and the model: a change to either is a
    new source, so a concept stalled under the old one is drafted again."""
    from agents import check_items, check_items_topup
    from agents._providers import model_name_for

    return "|".join(
        (check_items._PROMPT_HASH, check_items_topup._PROMPT_HASH, model_name_for("check_items"))
    )


def _source_fingerprint(ranked: Iterable[dict]) -> str:
    """What a concept is drafted from: its ranked passages' ids and texts,
    order-free (a re-rank of the same passages is the same source), and the
    drafting version (_drafting_version)."""
    parts = sorted(
        f"{chunk.get('id') or ''}\x1f"
        + hashlib.sha256((chunk.get("chunk_text") or "").encode("utf-8")).hexdigest()
        for chunk in ranked
    )
    parts.append("version\x1f" + _drafting_version())
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    """The clock the expiry reads; tests monkeypatch it."""
    return datetime.now(UTC)


def _parse_stamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


class _DraftFailures:
    """One run's view of check_item_draft_failures for its candidate concepts:
    ONE read up front, a write per concept whose count changes. Every error
    is a WARNING and leaves the concept draftable (fail open)."""

    def __init__(self, course_id: str, keys: list[str]):
        self.course_id = course_id
        self.rows: dict[str, dict] = {}
        if not keys:
            return
        try:
            rows = table(_FAILURES_TABLE).select(
                "concept_key,failures,source_fp,updated_at",
                filters={
                    "course_id": f"eq.{course_id}",
                    "concept_key": f"in.({','.join(pg_quote_value(k) for k in keys)})",
                },
            )
        except Exception:
            logger.warning(
                "check items: draft-failure read failed (course=%s); drafting every concept",
                course_id,
                exc_info=True,
            )
            return
        self.rows = {r["concept_key"]: r for r in rows or [] if r.get("concept_key")}

    def stalled(self, key: str, fp: str) -> bool:
        """At the bound on an unchanged source, within the TTL of the last
        failure. A row with no readable updated_at is not stalled (fail open)."""
        row = self.rows.get(key)
        if not (
            row
            and row.get("source_fp") == fp
            and (row.get("failures") or 0) >= CHECK_ITEM_REDRAFT_MAX_FAILURES
        ):
            return False
        stamp = _parse_stamp(row.get("updated_at"))
        ttl = timedelta(days=CHECK_ITEM_REDRAFT_FAILURE_TTL_DAYS)
        return stamp is not None and _utcnow() - stamp < ttl

    def _write(self, key: str, failures: int, fp: str) -> None:
        row = {
            "course_id": self.course_id,
            "concept_key": key,
            "failures": failures,
            "source_fp": fp,
            "updated_at": _utcnow().isoformat(),
        }
        try:
            table(_FAILURES_TABLE).upsert([row], on_conflict=_FAILURES_ON_CONFLICT)
        except Exception:
            logger.warning(
                "check items: draft-failure write failed (course=%s concept=%s)",
                self.course_id,
                key,
                exc_info=True,
            )
            return
        self.rows[key] = row

    def failed(self, key: str, fp: str) -> None:
        row = self.rows.get(key)
        before = (row.get("failures") or 0) if row and row.get("source_fp") == fp else 0
        self._write(key, before + 1, fp)

    def succeeded(self, key: str, fp: str) -> None:
        row = self.rows.get(key)
        if row and (row.get("failures") or 0) > 0:  # no record, nothing to reset
            self._write(key, 0, fp)


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
    agent call. Each call's sources are re-checked around its write (A23);
    a source found withdrawn leaves every later call of the run. A concept a
    call left below CHECK_ITEM_MC_MIN_PER_CONCEPT stored mc_reason items is
    topped up right after it (`_top_up_mc_reason`, A37); `items_created`
    counts the top-up's items too.
    Synchronous: it runs in a worker thread with no event loop.
    `user_id=None` (the backfill) records usage against the system actor.
    A concept at CHECK_ITEM_REDRAFT_MAX_FAILURES failed passes on an unchanged
    source is skipped too, within CHECK_ITEM_REDRAFT_FAILURE_TTL_DAYS of its
    last failure (counted in concepts_skipped; `_DraftFailures`)."""
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
    ledger = _DraftFailures(course_id, [key for key, _, _ in todo])
    stalled = [key for key, _, ranked in todo if ledger.stalled(key, _source_fingerprint(ranked))]
    if stalled:
        logger.info(
            "check items: %d concept(s) skipped after %d failed drafting passes on an "
            "unchanged source (course=%s): %s",
            len(stalled),
            CHECK_ITEM_REDRAFT_MAX_FAILURES,
            course_id,
            stalled,
        )
        skipped += len(stalled)
        todo = [t for t in todo if t[0] not in stalled]

    deps = SaplingDeps(
        user_id=user_id or "",
        course_id=course_id,
        supabase=None,
        request_id=current_request_id() or f"check_items:{document_id or course_id}",
        feature="check_items",
    )
    created = attempted = unavailable = 0
    # Documents a re-check found withdrawn during this run. The backfill reads
    # a course's sources once and then drafts batch after batch, so each later
    # batch is re-ranked without them: their text is never sent again, and a
    # concept they alone covered counts unmatched instead of costing a call
    # whose drafts would be dropped.
    gone: set[str] = set()
    for start in range(0, len(todo), CHECK_ITEM_CONCEPTS_PER_CALL):
        batch = todo[start : start + CHECK_ITEM_CONCEPTS_PER_CALL]
        if gone:
            remaining = [c for c in chunks if c.get("doc_id") not in gone]
            kept = []
            for key, name, _ in batch:
                ranked = rank_chunks_for_concept(
                    name, remaining, limit=CHECK_ITEM_MAX_CHUNKS, min_score=min_chunk_score
                )
                if ranked:
                    kept.append((key, name, ranked))
                else:
                    unmatched += 1
            batch = kept
            if not batch:
                continue
        names = [name for _, name, _ in batch]
        sources = _call_sources(ranked for _, _, ranked in batch)

        out = run_agent_sync(draft_items(names, sources.passages, deps=deps, flex=flex))
        attempted += len(batch)
        if isinstance(out, CheckItemsUnavailable):
            _report_failure(user_id, document_id, course_id, out.reason)
            unavailable += len(batch)
            # Only a one-concept call's validation failure is that concept's
            # own outcome; anything else, or any multi-concept call, is no
            # concept's fault (M2 allowlist).
            if len(batch) == 1 and out.reason in _CONCEPT_FAILURE_REASONS:
                key, _, ranked = batch[0]
                ledger.failed(key, _source_fingerprint(ranked))
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

        write = _write_checked(
            drafts_by_key,
            sources,
            gone=gone,
            user_id=user_id,
            document_id=document_id,
            course_id=course_id,
        )
        if write.recheck_failed:
            unavailable += len(batch)
            continue
        created += sum(len(w.ids) for w in write.stored.values())
        if write.withdrawn:
            continue  # the call's drafts were dropped, or its items retired
        # A37: a concept this call left below the mc_reason floor is topped up.
        for key, name, ranked in batch:
            if key in write.stored:
                topped = _top_up_mc_reason(
                    key,
                    name,
                    ranked,
                    write.stored[key],
                    deps=deps,
                    flex=flex,
                    gone=gone,
                    user_id=user_id,
                    document_id=document_id,
                    course_id=course_id,
                )
                created += topped
                # A write that failed (StorageError) is not the drafts' fault:
                # only a concept whose write ran is counted either way.
                fp = _source_fingerprint(ranked)
                if write.stored[key].ids or topped:
                    ledger.succeeded(key, fp)
                else:
                    ledger.failed(key, fp)

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


# ── upload-time drafting pool ──────────────────────────────────────────────
#
# One upload's drafting is up to ceil(CHECK_ITEM_MAX_CONCEPTS_PER_DOC /
# CHECK_ITEM_CONCEPTS_PER_CALL) = 4 sequential generation runs plus at most
# CHECK_ITEM_MAX_CONCEPTS_PER_DOC x CHECK_ITEM_MC_TOPUP_CALLS = 10 one-concept
# mc_reason top-up runs (A37), all on Flex and on this one thread, each up to
# FLEX_TIMEOUT_S x (CHECK_ITEM_FLEX_RETRIES + 1): a thread held for minutes,
# hours at worst.
# On the event loop's default executor or Starlette's request threadpool a few
# concurrent uploads would starve every other threaded call in the process
# (the next upload's extraction and persist among them), so real-mode drafting
# runs HERE, CHECK_ITEM_DRAFT_WORKERS at a time; the rest wait in the queue.
# The workers are not daemons: concurrent.futures joins them at interpreter
# exit. So the app's shutdown hook (main.py's lifespan) calls
# `shutdown_draft_pool`, which drops every QUEUED drafting (owner decision A38,
# low-severity 4) instead of letting a deploy's SIGTERM wait for the whole
# queue; a run already in flight still finishes or dies with the platform's
# kill after its grace period. The nightly `--all-courses` backfill (spec
# §11.7) drafts what was dropped.

_draft_pool_instance: ThreadPoolExecutor | None = None
_draft_pool_lock = threading.Lock()


def _draft_pool() -> ThreadPoolExecutor:
    global _draft_pool_instance
    with _draft_pool_lock:
        if _draft_pool_instance is None:
            _draft_pool_instance = ThreadPoolExecutor(
                max_workers=CHECK_ITEM_DRAFT_WORKERS, thread_name_prefix="check-items"
            )
        return _draft_pool_instance


def shutdown_draft_pool() -> None:
    """Drop the queued drafting and let the pool go without waiting (the app's
    shutdown hook). Idempotent; a later upload builds a new pool."""
    global _draft_pool_instance
    with _draft_pool_lock:
        pool, _draft_pool_instance = _draft_pool_instance, None
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)
        logger.info("check items: drafting pool shut down; queued drafting dropped")


def _generate_for_document_logged(document_id: str, **kwargs) -> None:
    try:
        generate_for_document(document_id, **kwargs)
    except Exception:
        logger.exception("check items for document %s failed", document_id)


def queue_generation_for_document(
    document_id: str, *, user_id: str, course_id: str, concept_names: Iterable[str]
) -> Future:
    """Queue the upload hook's drafting (background prefill, Flex) on this
    module's own bounded pool and return at once. The caller's context
    (request id) rides along; a failure is logged, never raised."""
    return _draft_pool().submit(
        contextvars.copy_context().run,
        _generate_for_document_logged,
        document_id,
        user_id=user_id,
        course_id=course_id,
        concept_names=list(concept_names),
        flex=True,
    )
