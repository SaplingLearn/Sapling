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

Quality (A113, A123): every stored row carries learning.item_lint's flags
(`lint_flags`, plaintext codes — flagged items are stored, never dropped); a
question staff retired for its course (learning/item_reports.py) is never
stored again, and `retire_course_item` voids its evidence through the single
graph writer, then deletes it through the same retire path as A23/A34. A
question its reporters quarantined is stored again when re-drafted, held like
its other rows (`reports_threshold`, below).

Alignment (A119): before a generation pass writes, every valid draft of the
call goes through ONE alignment check (agents/check_items_verify.py) and
learning/item_alignment.py applies its answers — an unasked criterion is
dropped, an item is re-tagged to the concept it tests, or rejected — with what
changed recorded beside the lint codes and `aligned_at` stamped. The check
failing closes the write (the call's drafts are dropped, a later run redrafts
them). `create_items` stores without it: tests and evals only.

Keys (A124): then every aligned draft is solved BLIND by a model of another
family (agents/check_items_solve.py: the question, an mc_reason item's
options under their stored letters and the call's passages — never the key,
rubric or reference), and learning/item_keys.py compares the answer with the
key in code (option letter; number within the tolerance; free text by equal
answer tokens, else ONE key-match call per batch, agents/
check_items_key_match.py). Agreement stores the item with
`canonical_verified`; a different answer, or "the passages do not settle one",
stores it HELD (`key_disputed` / `key_unsolved` in lint_flags) — never served,
its key never released, listed first-class in the A113 review queue until an
admin approves it (which confirms the key) or retires it; a draft the check
gave no usable answer for is dropped alone; an unavailable check drops the
call's drafts (fail closed). `key_checked_at` is stamped on every checked row.
Held items are withdrawn from every student read here (`list_items`,
`items_for_concepts`, `get_check_item`) exactly as a retired one is; the scan
reads (`items_by_ids`, `items_by_hash`) and the admin reads keep them.
scripts/backfill_check_item_keys.py checks stored rows; the human audit
(`record_item_audit`, learning/item_audit.py) measures what is left.

Staff holds (A123) are the same hold under two more codes
(learning/checks.py STAFF_HOLD_FLAGS): `reports_threshold` while reporters'
quarantine waits for staff, `staff_retired` from a staff retire until the
rows are deleted. A confirmed key lifts neither; only a staff decision does.
The database derives both from check_item_reviews — the report and decision
functions write them onto the course item's rows in the decision's own
transaction, and a trigger re-derives them on every later insert or flag
write — so nothing here sets or clears one (a rewrite keeps them, `kept_flags`,
only so as not to fight that trigger).
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import threading
from collections import deque
from collections.abc import Iterable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

import config
from agents._run import run_agent_sync
from agents.check_items import CheckItemsUnavailable, draft_items
from agents.check_items_key_match import MatchItem, match_keys, matches
from agents.check_items_solve import SolveItem, solutions, solve_items
from agents.check_items_topup import draft_mc_topup
from agents.check_items_verify import VerifyItem, verdicts, verify_items
from agents.deps import SaplingDeps
from db.connection import page_all, pg_quote_value, table
from learning.checks import (
    KEY_AUDIT_AMBIGUOUS,
    KEY_AUDIT_WRONG,
    KEY_HOLD_FLAGS,
    PROVENANCE_FLAGS,
    REPORTS_THRESHOLD,
    STAFF_HOLD_FLAGS,
    UNSOURCED,
    CheckItem,
    CheckItemDraft,
    Option,
    RubricItem,
    WrongReason,
    clean_chunk_ids,
    common_wrong,
    content_criteria,
    held,
    held_flags,
    item_id,
    key_held_flags,
    lettered_options,
    parse_tolerance,
    question_hash,
    rank_chunks_for_concept,
    repair_draft,
    rubric_entries,
    stored_rubric,
    validate_draft,
)
from learning.item_alignment import (
    ALIGNMENT_FLAGS,
    Alignment,
    Verdict,
    align,
    kept_flags,
    merge_flags,
)
from learning.item_audit import AMBIGUOUS, CORRECT, WRONG
from learning.item_keys import (
    TO_MATCH,
    KeyCheck,
    KeySubject,
    audited_flags,
    checked_flags,
    compare,
    settle,
)
from learning.item_lint import LINT_FLAGS, lint_check_item, lint_item
from learning.item_reports import QUARANTINED, RETIRED, review_statuses
from learning.params import (
    CHECK_ITEM_CONCEPTS_PER_CALL,
    CHECK_ITEM_DIFFICULTIES,
    CHECK_ITEM_DRAFT_PENDING_TTL_S,
    CHECK_ITEM_DRAFT_WORKERS,
    CHECK_ITEM_INITIAL_PER_CONCEPT,
    CHECK_ITEM_MAX_CHUNKS,
    CHECK_ITEM_MAX_CONCEPTS_PER_DOC,
    CHECK_ITEM_MC_MIN_PER_CONCEPT,
    CHECK_ITEM_MC_TOPUP_CALLS,
    CHECK_ITEM_REDRAFT_FAILURE_TTL_DAYS,
    CHECK_ITEM_REDRAFT_MAX_FAILURES,
    CHECK_ITEM_SOLVE_MAX_ITEMS,
    CHECK_ITEM_VERIFY_MAX_ITEMS,
    ITEM_AUDIT_VERDICTS,
)
from services.academics import course_offering_ids
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
    "source_document_ids,question_hash,graded,created_at,final_answer,lint_flags"
)
#: The plaintext columns the A113 review queue lists an item by (never text);
#: canonical_verified says whether a key-hold code still holds it (A124).
_QUEUE_COLUMNS = (
    "id,course_id,concept_key,question_hash,format,difficulty,lint_flags,canonical_verified"
)
#: What the A119 alignment backfill reads: every column, when the alignment
#: check last passed the row (NULL = never) and when the A124 key check did (a
#: re-key carries it). Only the backfills read them, so the request path's reads
#: never depend on the A119 or A124 migrations.
_ALIGN_COLUMNS = _COLUMNS + ",aligned_at,key_checked_at"
#: What the A124 key backfill reads: every column, and when the key check last
#: ran on the row (NULL = never).
_KEY_COLUMNS = _COLUMNS + ",key_checked_at"
#: Every code the review queue lists an item for: the A113 linter's, A119's,
#: the holds (A124's key holds, A123's staff holds) and the A128 provenance
#: code (`unsourced`, which is no hold), in item_alignment.merge_flags' order.
QUEUE_FLAGS = (
    *LINT_FLAGS, *ALIGNMENT_FLAGS, *KEY_HOLD_FLAGS, *PROVENANCE_FLAGS, *STAFF_HOLD_FLAGS
)

#: What derive_key names the secret the correct mc_reason option's slot is
#: keyed with (A37): the client is sent each item's question_hash, so the slot
#: must not be computable from it alone.
OPTION_SLOT_PURPOSE = "check_items.option_slot.v1"

# The A24 answerable stub ("is this item answerable from these
# passages?", meant for services/learning_decisions.py::item_answerable and
# never called) is gone: the A124 blind solve answers that question for every
# draft before it is stored — an item the passages do not settle is held
# (`key_unsolved`), never served.


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
    flags: Iterable[str] = (),
    aligned_at: str | None = None,
    verified: bool = False,
    key_checked_at: str | None = None,
    unsourced: bool = False,
) -> dict:
    qh = question_hash(draft.prompt)  # PLAINTEXT, before encryption
    cited = clean_chunk_ids(draft, allowed)
    if unsourced and not cited:
        # A128: drafted from extracted text because the document's indexing
        # failed — no passage to cite. Stored like any other item; the code
        # puts it in the review queue and behind its sourced siblings.
        flags = (*flags, UNSOURCED)
    # A37 review: an mc_reason rubric ends with code's reason criterion.
    rubric = [r.model_dump() for r in stored_rubric(draft)]
    # A37: an mc_reason item's wrong reasons are its distractors' misconceptions,
    # the keys its stored options carry; free and teachback pair their lists.
    wrong = [w.model_dump() for w in common_wrong(draft)]
    options = None
    correct_option = None
    texts: list[str] = []
    correct: int | None = None
    if draft.format == _MC_REASON:
        # A37: code letters the options and places the correct one at a slot
        # keyed by the server secret; the stored shape ([{letter, text,
        # wrong_key}] + the letter) is what the grader and the routes read.
        lettered, letter = lettered_options(draft, slot_key=derive_key(OPTION_SLOT_PURPOSE))
        options = encrypt_json([o.model_dump() for o in lettered])
        correct_option = encrypt_if_present(letter)
        texts = [o.text for o in lettered]
        correct = next(i for i, o in enumerate(lettered) if o.letter == letter)
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
        # check (A124: the blind solve agreed with the key) or an instructor
        # confirmation (an admin's approval, an audit verdict "correct").
        "canonical_verified": verified,
        "stepwise": draft.stepwise,
        "source_chunk_ids": cited,
        "source_document_ids": source_docs,
        "question_hash": qh,
        # A32: every generated item is practice material, never graded coursework.
        "graded": False,
        # A113: the item-flaw linter over the STORED shape (lettered options,
        # the correct one by its letter) — what lint_check_item reads back, so
        # the backfill agrees. Codes only; flagged items are stored, not dropped.
        # A119: then what the alignment check changed (learning.item_alignment);
        # A124: then a key-hold code when the blind solve disputed the key;
        # A128: then `unsourced` when it cites no passage of a failed index.
        "lint_flags": merge_flags(lint_item(draft.prompt, texts, correct), flags),
        # A119: when the alignment check passed this draft; None = never checked
        # (create_items), which the alignment backfill picks up.
        "aligned_at": aligned_at,
        # A124: when the key check ran on this draft (agreed or held); None =
        # never (create_items), which the key backfill picks up.
        "key_checked_at": key_checked_at,
    }


# A top-up draft whose prompt a stored item of the concept already has (A37).
_REPEAT = "repeat: the prompt is a stored item's"
# A draft whose prompt is a question retired for the course (A113).
_RETIRED = "retired: the prompt repeats a question withdrawn from this course"
# A draft whose prompt is a question its reporters quarantined (A123): stored,
# held like the question's other rows, so it serves no one until staff decide.
_QUARANTINED = "quarantined: the prompt repeats a question held for staff review"


class _ConceptWrite(NamedTuple):
    """What one concept's write stored and dropped."""

    ids: list[str]  # the rows upserted
    # of those, the mc_reason rows a student can be served (A124: a held one is
    # not, so it counts toward no A37 floor): id -> difficulty
    mc_reason: dict[str, int]
    # each dropped (or, A124, held) mc_reason draft's reasons, "; "-joined
    mc_drops: list[str]
    # A119/A124: drafts dropped because a check gave no complete verdict for
    # them — the check's outcome, not the concept's (A41's allowlist)
    unverified: int = 0


class _Screened(NamedTuple):
    """One draft after repair and validation (and, on the generation path, the
    A119 alignment check and the A124 key check): stored as `draft`, or
    dropped for `reasons`."""

    format: str
    draft: CheckItemDraft | None  # repaired and valid; None = dropped
    # why it was dropped (or, A124, why it is stored held), "; "-joined
    reasons: str = ""
    flags: tuple[str, ...] = ()  # A119: what the alignment check changed; A124: a hold code
    aligned: bool = False  # A119: the alignment check passed it
    unverified: bool = False  # A119/A124: dropped for want of a verdict
    verified: bool = False  # A124: the blind solve agreed with its key
    key_checked: bool = False  # A124: the key check ran on it (agreed or held)


def _screen(course_id: str, concept_key: str, drafts: Iterable[CheckItemDraft]) -> list[_Screened]:
    """Repair each draft where no guess is needed (A37; logged at INFO by
    rule) and validate it (invalid → dropped + WARNING naming every rule), in
    draft order."""
    out: list[_Screened] = []
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
            out.append(_Screened(draft.format, None, "; ".join(reasons)))
            continue
        out.append(_Screened(draft.format, draft))
    return out


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
    dropped (the A37 top-up feeds those reasons back): `_screen`, then
    `_store_screened`. No alignment check (A119) and no key check (A124): the
    generation path screens, aligns, solves and stores in `_write_checked`."""
    return _store_screened(
        course_id,
        concept_key,
        document_id,
        _screen(course_id, concept_key, drafts),
        allowed_chunk_ids=allowed_chunk_ids,
        source_document_ids=source_document_ids,
        limit=limit,
        exclude_ids=exclude_ids,
    )


def _store_screened(
    course_id: str,
    concept_key: str,
    document_id: str | None,
    screened: Iterable[_Screened],
    *,
    allowed_chunk_ids: Iterable[str] = (),
    source_document_ids: Iterable[str] = (),
    limit: int | None = None,
    exclude_ids: Iterable[str] = (),
    unsourced: bool = False,
) -> _ConceptWrite:
    """Store the screened drafts of one concept in ONE upsert, saying what it
    stored and why each mc_reason draft was dropped. `limit` caps the valid
    rows stored (the top-up's missing count); the rest are logged, not stored.
    A draft whose row id is in `exclude_ids` (the top-up's stored items: the
    id is the prompt's question_hash) is a repeat: dropped before `limit`
    counts it, so it never rewrites the stored item or takes a new one's slot.
    A draft of a question retired for the course (A113) is dropped the same
    way, after one read of the batch's decisions; that read raises like the
    upsert does, so a blip drops the batch (the caller reports StorageError)
    rather than risk re-publishing a retired key. A119: an aligned draft
    carries the check's flags and `aligned_at`. A124: a key-checked draft
    carries `key_checked_at` and, agreed, `canonical_verified`; a held one its
    hold code — it is stored, but serves no one, so it takes no `limit` slot
    and counts toward no A37 floor, and its hold reason reaches the top-up.
    A123: a draft of a question its reporters quarantined is stored held the
    same way (`reports_threshold`: the database's trigger adds it whatever
    this write says — it is added here too so the slot count sees the hold).
    A128: `unsourced` (the call showed passages of a document whose indexing
    failed) marks every row that cites no chunk; it is no hold, so such a row
    still serves and takes its slot."""
    allowed = set(allowed_chunk_ids)
    exclude = set(exclude_ids)
    source_docs = sorted({d for d in source_document_ids if d})
    if not source_docs and document_id:
        source_docs = [document_id]
    stamp = _utcnow().isoformat()
    # (the entry, the reasons it was dropped) or (the entry, its row), in draft order
    built: list[tuple[_Screened, str | dict]] = []
    unverified = 0
    for entry in screened:
        if entry.draft is None:
            built.append((entry, entry.reasons))
            unverified += entry.unverified
            continue
        built.append(
            (
                entry,
                _build_row(
                    course_id,
                    concept_key,
                    document_id,
                    entry.draft,
                    allowed=allowed,
                    source_docs=source_docs,
                    flags=entry.flags,
                    aligned_at=stamp if entry.aligned else None,
                    verified=entry.verified,
                    key_checked_at=stamp if entry.key_checked else None,
                    unsourced=unsourced,
                ),
            )
        )
    hashes = [b["question_hash"] for _, b in built if isinstance(b, dict)]
    decided = review_statuses(course_id, hashes) if hashes else {}
    rows: list[dict] = []
    seen: set[str] = set()
    mc_drops: list[str] = []
    surplus = repeats = withdrawn = quarantined = served = 0
    for entry, row in built:
        fmt = entry.format
        if not isinstance(row, dict):
            if fmt == _MC_REASON:
                mc_drops.append(row)
            continue
        status = decided.get(row["question_hash"])
        if status == RETIRED:
            withdrawn += 1
            if fmt == _MC_REASON:
                mc_drops.append(_RETIRED)
            continue
        if row["id"] in seen:
            # Same normalized prompt twice in one batch: one upsert may not
            # name a row twice (PostgREST rejects it), and it is one item.
            continue
        if row["id"] in exclude:
            repeats += 1
            if fmt == _MC_REASON:
                mc_drops.append(_REPEAT)
            continue
        if status == QUARANTINED:
            row["lint_flags"] = merge_flags(row.get("lint_flags"), [REPORTS_THRESHOLD])
        held = _row_held(row)
        if limit is not None and not held and served >= limit:
            surplus += 1
            continue
        seen.add(row["id"])
        rows.append(row)
        if status == QUARANTINED:
            quarantined += 1
            if fmt == _MC_REASON:
                mc_drops.append(_QUARANTINED)
        elif held:
            if fmt == _MC_REASON and entry.reasons:
                mc_drops.append(entry.reasons)
        else:
            served += 1
    if repeats:
        logger.info(
            "check items: %d draft(s) repeat a stored item's prompt; not stored "
            "(course=%s concept=%s)",
            repeats,
            course_id,
            concept_key,
        )
    if withdrawn:
        logger.info(
            "check items: %d draft(s) repeat a question retired for the course; not stored "
            "(course=%s concept=%s)",
            withdrawn,
            course_id,
            concept_key,
        )
    if quarantined:
        logger.info(
            "check items: %d draft(s) repeat a question quarantined for the course; "
            "stored held (course=%s concept=%s)",
            quarantined,
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
        {r["id"]: r["difficulty"] for r in rows if r["format"] == _MC_REASON and not _row_held(r)},
        mc_drops,
        unverified,
    )


def _row_held(row: dict) -> bool:
    """A124, A123: a stored row (its plaintext columns) is held off every student path."""
    return held_flags(row.get("lint_flags"), row.get("canonical_verified"))


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
    caller logs it). It runs NO alignment check (A119) and NO key check
    (A124), and stamps neither `aligned_at` nor `key_checked_at` (its rows are
    unverified): tests and evals call it; generation writes through
    `_write_checked`, and no application module calls this (pinned)."""
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
        # A113: None on a row the linter has not read yet (plaintext codes).
        lint_flags=_lint_flags(row.get("lint_flags")),
    )


def _lint_flags(value) -> list[str] | None:
    """The stored lint codes, or None (never linted, or not a list of strings)."""
    if not isinstance(value, list):
        return None
    return [v for v in value if isinstance(v, str)]


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


def _unheld(items: Iterable[CheckItem]) -> list[CheckItem]:
    """A124: the items no hold withdraws — no key hold, and (A123) no staff
    hold: neither quarantined by reporters nor retired by staff. The student
    reads below drop a held item as if it were retired (A23: nothing serves a
    deleted item, and every loop and review path already handles an item gone
    mid-session — a posed check, an open post-test pose or a served review
    item reads as withdrawn, its key never released)."""
    return [i for i in items if not held(i)]


def list_items(
    course_id: str,
    concept_key: str,
    *,
    format: str | None = None,
    difficulty: int | None = None,
) -> list[CheckItem]:
    """Every item for one course concept a student may be served (A124: no
    held one), filtered on plaintext columns only."""
    filters = {"course_id": f"eq.{course_id}", "concept_key": f"eq.{concept_key}"}
    if format is not None:
        filters["format"] = f"eq.{format}"
    if difficulty is not None:
        filters["difficulty"] = f"eq.{difficulty}"
    rows = table(_TABLE).select(_COLUMNS, filters=filters, order="created_at,id")
    return _unheld(_to_items(rows))


def get_check_item(item_id: str, *, include_held: bool = False) -> CheckItem | None:
    """One item by its plaintext `id` (PKG-07: the loop route's ACTIVE item),
    decoded by the same `_row_to_item` decrypt boundary, so `final_answer` and
    `canonical_answer` come back decrypted like every other column. A missing
    id, no row, or a row that cannot be read → None (never raised). A124: a
    held item → None too (withdrawn, as a retired one is) unless
    `include_held` — the admin review queue's read."""
    if not item_id:
        return None
    rows = table(_TABLE).select(_COLUMNS, filters={"id": f"eq.{item_id}"}, limit=1)
    items = _to_items(rows)
    if not include_held:
        items = _unheld(items)
    return items[0] if items else None


def items_for_concepts(course_id: str, concept_keys: Iterable[str]) -> dict[str, list[CheckItem]]:
    """Every item a student may be served (A124: no held one) for the given
    keys, in ONE `in.(...)` select, grouped by key (every requested key
    present, [] when it has none)."""
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
    for item in _unheld(_to_items(rows)):
        grouped.setdefault(item.concept_key, []).append(item)
    return grouped


#: question hashes per `in.(...)` read in items_by_hash (a URL-length bound)
_HASH_BATCH = 100


def items_by_hash(hashes) -> list[CheckItem]:
    """The items with these question hashes, every course (PKG-14, spec §13
    A88: the open post-test poses a served turn is scanned against), decrypted,
    in batches of _HASH_BATCH. The caller matches each to its pose's course.
    A held item is kept (A124): one posed before its hold is still scanned."""
    keys = sorted({h for h in hashes or [] if h})
    out: list[CheckItem] = []
    for i in range(0, len(keys), _HASH_BATCH):
        batch = keys[i : i + _HASH_BATCH]
        rows = table(_TABLE).select(
            _COLUMNS,
            filters={"question_hash": f"in.({','.join(pg_quote_value(h) for h in batch)})"},
            order="id",
        )
        out.extend(_to_items(rows))
    return out


def items_by_ids(ids) -> list[CheckItem]:
    """The items with these plaintext ids, decrypted, in batches of _HASH_BATCH
    (PKG-14, spec §13 A101: the served-text scan set's posed steps and review
    items in a few `in.(...)` reads instead of one get_check_item per id; the
    admin review queue's text). Raises on a failed read (the scan set's caller
    fails closed). A held item is kept (A124): the scan still covers one posed
    before its hold, and staff review it."""
    keys = sorted({i for i in ids or [] if i})
    out: list[CheckItem] = []
    for i in range(0, len(keys), _HASH_BATCH):
        batch = keys[i : i + _HASH_BATCH]
        rows = table(_TABLE).select(
            _COLUMNS,
            filters={"id": f"in.({','.join(pg_quote_value(k) for k in batch)})"},
            order="id",
        )
        out.extend(_to_items(rows))
    return out


#: rows per read while course_has_items looks for an item no key hold withdraws
_HAS_ITEMS_PAGE = 50


def course_has_items(course_id: str) -> bool:
    """Whether the course has any item a student may be served — a held one
    (A124) does not count (feeds /probe/next's no_check_items and the A26 "No
    check items for this course yet" state). Plaintext columns only, read a
    page at a time until one unheld row: almost always the first row, all of
    them only for a course whose every item is held."""
    offset = 0
    while True:
        rows = table(_TABLE).select(
            "id,lint_flags,canonical_verified",
            filters={"course_id": f"eq.{course_id}"},
            order="id",
            limit=_HAS_ITEMS_PAGE,
            offset=offset,
        )
        rows = rows or []
        if any(not _row_held(r) for r in rows):
            return True
        if len(rows) < _HAS_ITEMS_PAGE:
            return False
        offset += _HAS_ITEMS_PAGE


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


# ── item quality (A113): the admin review queue and the lint backfill ──────
#
# The queue lists items by plaintext columns only (_QUEUE_COLUMNS) and
# decrypts just the page it shows, through items_by_ids (_row_to_item, the
# single decrypt boundary).


def flagged_item_rows() -> list[dict]:
    """Every item the linter flagged or the A119 alignment check changed
    (lint_flags overlaps QUEUE_FLAGS), by its plaintext columns, paged."""
    flags = "ov.{" + ",".join(pg_quote_value(f) for f in QUEUE_FLAGS) + "}"
    return list(page_all(table(_TABLE), _QUEUE_COLUMNS, filters={"lint_flags": flags}, order="id"))


def item_rows_for(keys: Iterable[tuple[str, str]]) -> list[dict]:
    """The stored rows of these (course_id, question_hash) course items, by
    their plaintext columns: one `in.(...)` read per _HASH_BATCH hashes, the
    course matched here. A retired item has no row."""
    wanted = {(c, h) for c, h in keys if c and h}
    hashes = sorted({h for _, h in wanted})
    out: list[dict] = []
    for start in range(0, len(hashes), _HASH_BATCH):
        batch = hashes[start : start + _HASH_BATCH]
        rows = table(_TABLE).select(
            _QUEUE_COLUMNS,
            filters={"question_hash": f"in.({','.join(pg_quote_value(h) for h in batch)})"},
            order="id",
        )
        out.extend(r for r in rows or [] if (r.get("course_id"), r.get("question_hash")) in wanted)
    return out


def items_to_lint(course_id: str | None = None, *, relint: bool = False) -> Iterator[CheckItem]:
    """The items scripts/backfill_check_item_lint.py reads, decrypted: those
    never linted (lint_flags NULL), or every item with `relint` (after a
    linter change); one course or all. Paged, in id order."""
    filters: dict[str, str] = {}
    if course_id:
        filters["course_id"] = f"eq.{course_id}"
    if not relint:
        filters["lint_flags"] = "is.null"
    for row in page_all(table(_TABLE), _COLUMNS, filters=filters, order="id"):
        items = _to_items([row])
        if items:
            yield items[0]


def lint_update(item: CheckItem) -> list[str] | None:
    """The item's lint flags as the write path would store them now, or None
    when they equal what is stored (nothing to write). The A119 alignment codes
    and the hold codes already stored are kept: they record what the alignment
    check changed and what a key check, an audit or a staff decision decided,
    which no re-lint can see again (dropping a key-hold code would release a
    held key; a staff-hold code the database restores either way)."""
    flags = merge_flags(lint_check_item(item), kept_flags(item.lint_flags))
    return None if item.lint_flags == flags else flags


def store_lint_flags(flags: Iterable[str], item_ids: Iterable[str]) -> int:
    """Write one set of lint codes (a plaintext column) onto these items,
    _DOC_ID_BATCH ids per `in.(...)` update; returns how many ids were sent.
    Raises on a failed write."""
    ids = [i for i in dict.fromkeys(item_ids) if i]
    for start in range(0, len(ids), _DOC_ID_BATCH):
        batch = ids[start : start + _DOC_ID_BATCH]
        table(_TABLE).update(
            {"lint_flags": list(flags)},
            filters={"id": "in.(" + ",".join(pg_quote_value(i) for i in batch) + ")"},
            prefer_return_minimal=True,
        )
    return len(ids)


def relint_course_item(course_id: str, question_hash: str) -> int:
    """Lint every row of a course item the current linter would flag
    differently (`lint_update`), one write per changed row; returns how many
    were written. Spec §13 A123: an approval runs it after lifting a staff
    hold. A row never linted (lint_flags NULL) that a quarantine held carries
    an empty list once the hold is lifted, which reads as "linted clean"
    (checks.lint_rank) — linting it now makes that true. Raises on a failed
    read or write (the approval answers 503; approving again finishes it)."""
    rows = table(_TABLE).select(
        _COLUMNS,
        filters={"course_id": f"eq.{course_id}", "question_hash": f"eq.{question_hash}"},
        order="id",
    )
    written = 0
    for item in _to_items(rows):
        flags = lint_update(item)
        if flags is not None:
            store_lint_flags(flags, [item.id])
            written += 1
    return written


# ── alignment backfill (A119) ───────────────────────────────────────────────
#
# scripts/backfill_check_item_alignment.py re-checks items stored before the
# alignment check existed (aligned_at NULL), or every item with --reverify,
# through the same check and the same learning.item_alignment rules as the
# write path. Evidence is never touched: node_mastery_events keys no foreign
# key on an item, so a re-keyed or rejected (deleted) item leaves every
# evidence row (its check_item_id, node and question_hash) exactly as recorded
# — only a STAFF retire voids evidence (spec §13 A123). Reports and reviews key
# on (course_id, question_hash), which a re-tag keeps.


def items_to_align(
    course_id: str | None = None, *, reverify: bool = False
) -> list[tuple[dict, CheckItem]]:
    """The rows the alignment backfill reads, each with its decrypted item:
    those never checked (aligned_at NULL), or every row with `reverify`; one
    course or all. Paged in id order and read IN FULL before the caller
    writes anything (a write moves a row out of the `aligned_at IS NULL`
    paging). A row that cannot be read is skipped (logged)."""
    filters: dict[str, str] = {}
    if course_id:
        filters["course_id"] = f"eq.{course_id}"
    if not reverify:
        filters["aligned_at"] = "is.null"
    out: list[tuple[dict, CheckItem]] = []
    for row in page_all(table(_TABLE), _ALIGN_COLUMNS, filters=filters, order="id"):
        items = _to_items([row])
        if items:
            out.append((row, items[0]))
    return out


def course_concept_names(course_id: str) -> dict[str, str]:
    """{concept_key: name} over every student's graph_nodes of the course —
    the first name per key, the backfill drafting's rule
    (scripts/backfill_check_items.py) — read-only and paged."""
    names: dict[str, str] = {}
    for row in page_all(
        _GraphNodesRead(), "concept_name", filters={"course_id": f"eq.{course_id}"}, order="id"
    ):
        name = row.get("concept_name") or ""
        key = concept_key(name)
        if key and key not in names:
            names[key] = name
    return names


def check_stored_alignment(
    course_id: str, items: list[CheckItem], scope: dict[str, str], *, flex: bool = True
) -> list[Alignment] | None:
    """The A119 decision for each stored item, in order: the alignment check
    over the item as stored (its own criteria, the reason criterion left out;
    its options with the correct one marked), applied by
    learning.item_alignment.align against `scope` ({concept_key: name}; each
    item's own concept is always in scope). None when the check was
    unavailable — the backfill then changes nothing (an outage never deletes
    a stored item). Usage is recorded against the system actor."""
    if not items:
        return []
    deps = SaplingDeps(
        user_id="",
        course_id=course_id,
        supabase=None,
        request_id=current_request_id() or f"check_items_verify:{course_id}",
        feature="check_items_verify",
    )
    found = _verdicts_for([_item_subject(i) for i in items], scope, deps=deps, flex=flex)
    if found is None:
        return None
    return [
        align(len(content_criteria(item)), item.concept_key, verdict, scope)
        for item, verdict in zip(items, found)
    ]


def mark_aligned(item_ids: Iterable[str], *, at: str) -> int:
    """Stamp `aligned_at` on items the check left as they are (_DOC_ID_BATCH
    ids per `in.(...)` update); returns how many ids were sent. Raises on a
    failed write."""
    ids = [i for i in dict.fromkeys(item_ids) if i]
    for start in range(0, len(ids), _DOC_ID_BATCH):
        batch = ids[start : start + _DOC_ID_BATCH]
        table(_TABLE).update(
            {"aligned_at": at},
            filters={"id": "in.(" + ",".join(pg_quote_value(i) for i in batch) + ")"},
            prefer_return_minimal=True,
        )
    return len(ids)


def apply_item_alignment(row: dict, item: CheckItem, result: Alignment, *, at: str) -> str:
    """Write what the check changed on one stored item: its rubric rebuilt
    from the kept criteria (checks.rubric_entries — numbered and closed with
    the reason criterion exactly as a fresh item's), its flags (the linter's
    over the stored shape, the alignment and A124 key-hold codes already
    stored and the new ones), `aligned_at`. On the same concept the row is
    updated in place. A re-tag re-keys it: the row as stored (every other
    column's ciphertext copied untouched, `canonical_verified` and the A124
    `key_checked_at` with it) is upserted under (course_id, the tested concept,
    question_hash) — its new id — and the old row deleted through the A23 retire
    path. Evidence is never written. Returns the item's id after the write;
    raises on a failed write (a re-run finishes a half-done re-key: the old
    row is still unchecked)."""
    criteria = content_criteria(item)
    update: dict = {
        "lint_flags": merge_flags(lint_check_item(item), kept_flags(item.lint_flags), result.flags),
        "aligned_at": at,
    }
    if len(result.keep) < len(criteria):
        rubric = rubric_entries([criteria[i] for i in result.keep], item.format)
        update["rubric_json"] = encrypt_if_present(json.dumps([r.model_dump() for r in rubric]))
    if result.concept_key == item.concept_key:
        table(_TABLE).update(update, filters={"id": f"eq.{item.id}"}, prefer_return_minimal=True)
        return item.id
    new_id = item_id(item.course_id, result.concept_key, item.question_hash)
    columns = [*_COLUMNS.split(","), "key_checked_at"]
    moved = {c: row[c] for c in columns if c in row}
    moved.update(update, id=new_id, concept_key=result.concept_key)
    table(_TABLE).upsert([moved], on_conflict=_ON_CONFLICT)
    retire_items_by_id([item.id])
    return new_id


# ── key backfill (A124) ─────────────────────────────────────────────────────
#
# scripts/backfill_check_item_keys.py solves stored items blind, through the
# same agents and the same learning.item_keys rules as the write path, from
# the passages of the documents each item cites (A23: shared course material
# only, ranked for its concept as a drafting call ranks them). What it may
# write: agreed → canonical_verified and the model's hold code cleared;
# disputed or not settled → the model's hold code (held, unless the key was
# already confirmed: a model never un-confirms a key — an earlier agreement,
# an admin's approval or an audit verdict "correct" stand, and the dispute is
# only recorded for staff); `key_checked_at` either way. An item a human
# audited wrong or ambiguous is never re-checked (a model never overrules a
# human). Nothing is ever deleted; an outage changes nothing.


def items_to_key_check(
    course_id: str | None = None, *, reverify: bool = False
) -> list[tuple[dict, CheckItem]]:
    """The rows the key backfill reads, each with its decrypted item: those
    never key-checked (key_checked_at NULL), or every row with `reverify`; one
    course or all. Paged in id order and read IN FULL before the caller writes
    anything (a write moves a row out of the `key_checked_at IS NULL` paging).
    A row that cannot be read is skipped (logged)."""
    filters: dict[str, str] = {}
    if course_id:
        filters["course_id"] = f"eq.{course_id}"
    if not reverify:
        filters["key_checked_at"] = "is.null"
    out: list[tuple[dict, CheckItem]] = []
    for row in page_all(table(_TABLE), _KEY_COLUMNS, filters=filters, order="id"):
        items = _to_items([row])
        if items:
            out.append((row, items[0]))
    return out


def _source_rows(document_ids: Iterable[str]) -> list[dict]:
    """The live (not deleted) document rows `source_chunks` needs, by id, in
    _DOC_ID_BATCH batches. Raises on a failed read."""
    ids = sorted({d for d in document_ids if d})
    rows: list[dict] = []
    for start in range(0, len(ids), _DOC_ID_BATCH):
        batch = ids[start : start + _DOC_ID_BATCH]
        rows.extend(
            table("documents").select(
                "id,user_id,shareability,shareability_confidence,extracted_text",
                filters={
                    "id": "in.(" + ",".join(pg_quote_value(d) for d in batch) + ")",
                    "deleted_at": "is.null",
                },
            )
            or []
        )
    return rows


def key_check_passages(rows: Iterable[dict], names: dict[str, str]) -> dict[str, list[dict]]:
    """{concept_key: passages} for the stored rows' concepts: every source
    document the concept's rows cite (`source_document_ids`, else
    `document_id`), read through `source_chunks` — shared course material
    only, its SHARED chunks (A23) — and ranked for the concept's name
    (`names`, else the key) exactly as a drafting call ranks them (at most
    CHECK_ITEM_MAX_CHUNKS). A concept whose sources yield nothing maps to []:
    the caller leaves its items unchecked rather than solve them blind of
    their course material. Raises on a failed read."""
    docs_by_key: dict[str, set[str]] = {}
    for row in rows:
        cited = list(row.get("source_document_ids") or []) or [row.get("document_id")]
        docs_by_key.setdefault(row.get("concept_key") or "", set()).update(d for d in cited if d)
    chunks_by_doc = {
        doc["id"]: source_chunks(doc)
        for doc in _source_rows(d for docs in docs_by_key.values() for d in docs)
    }
    out: dict[str, list[dict]] = {}
    for key, docs in docs_by_key.items():
        chunks = [c for d in sorted(docs) for c in chunks_by_doc.get(d, [])]
        out[key] = rank_chunks_for_concept(names.get(key) or key, chunks, limit=CHECK_ITEM_MAX_CHUNKS)
    return out


def check_stored_keys(
    course_id: str, items: list[CheckItem], passages: list[dict], *, flex: bool = True
) -> list[KeyCheck] | None:
    """The A124 decision for each stored item, in order: a blind solve of the
    item as stored (its stored options and letters) from `passages`,
    compared with its stored key in code, and the key match for free-text
    pairs code cannot settle. None when the check was unavailable — the
    backfill then changes nothing. Usage is recorded against the system actor."""
    if not items:
        return []
    deps = SaplingDeps(
        user_id="",
        course_id=course_id,
        supabase=None,
        request_id=current_request_id() or f"check_items_solve:{course_id}",
        feature="check_items_solve",
    )
    return _key_checks_for([_item_key_subject(i) for i in items], passages, deps=deps, flex=flex)


def _linted(flags, item: CheckItem) -> list[str]:
    """A stored row's flags, the A113 linter's codes filled in when it was
    never linted (NULL): a write of a key or audit code makes the column
    non-NULL, which says "linted" to the lint backfill and the post-test's
    lint tiers, so it must hold the linter's answer too."""
    return list(flags) if flags is not None else lint_check_item(item)


def key_check_update(item: CheckItem, check: KeyCheck, *, at: str) -> dict:
    """The columns the key backfill writes for one stored item it checked:
    its flags with the model's hold code replaced (checked_flags; a
    never-linted row linted now), the stamp, and `canonical_verified` true on
    an agreement or false on a dispute of a key nobody had confirmed — never
    lowered from true (a confirmed key stays confirmed; its dispute is
    recorded, and the review queue lists it)."""
    update: dict = {
        "lint_flags": checked_flags(_linted(item.lint_flags, item), check),
        "key_checked_at": at,
    }
    if check.verified:
        update["canonical_verified"] = True
    elif not item.canonical_verified:
        update["canonical_verified"] = False
    return update


def apply_key_check(item: CheckItem, update: dict) -> None:
    """Write `key_check_update`'s columns onto one stored item (its plaintext
    columns only). Raises on a failed write."""
    table(_TABLE).update(update, filters={"id": f"eq.{item.id}"}, prefer_return_minimal=True)


def audit_decided(item: CheckItem) -> bool:
    """A human audit verdict holds the item's key (`key_audit_wrong` /
    `key_audit_ambiguous`): no model run ever re-checks it."""
    return any(f in (KEY_AUDIT_WRONG, KEY_AUDIT_AMBIGUOUS) for f in item.lint_flags or ())


def confirm_course_item(course_id: str, question_hash: str) -> None:
    """A124: an admin's approval is the A22 instructor confirmation of the
    key — `canonical_verified` on every row of the course item (one per
    concept that holds the question), which lifts a key hold. Flags are kept
    (the history of what held it). A staff hold (A123) is not the key's: the
    decision itself lifts it (check_item_review_decide, in the database).
    Raises on a failed write."""
    table(_TABLE).update(
        {"canonical_verified": True},
        filters={"course_id": f"eq.{course_id}", "question_hash": f"eq.{question_hash}"},
        prefer_return_minimal=True,
    )


# ── the key audit (A124): a human measurement ───────────────────────────────
#
# Staff judge a stratified sample of a course's stored keys (learning/
# item_audit.py draws it) correct, wrong or ambiguous. One row per course item
# in check_item_audits (the latest verdict wins; the key's status at its first
# audit is kept, so the by-status rates stay a measurement of the key check).
# A verdict also acts on the item, as staff's word: "correct" confirms the key
# (canonical_verified; an earlier audit hold cleared); "wrong" / "ambiguous"
# holds it (canonical_verified false, `key_audit_wrong` / `key_audit_ambiguous`)
# until an approval or a later "correct" — a key staff found wrong is never
# served again on their say-so alone. Hashes, ids, enums and timestamps only.

_AUDITS = "check_item_audits"
_AUDITS_ON_CONFLICT = "course_id,question_hash"
_AUDIT_ROW_COLUMNS = (
    "course_id,question_hash,item_id,concept_key,format,difficulty,key_status,verdict,"
    "audited_by,audited_at"
)
#: The hold code each non-"correct" verdict sets.
_AUDIT_HOLD = {WRONG: KEY_AUDIT_WRONG, AMBIGUOUS: KEY_AUDIT_AMBIGUOUS}


def key_status(item) -> str:
    """The key's status as the audit records it: `verified` (confirmed),
    `held` (A124 key hold) or `unverified` (never checked, or checked with no
    verdict). A staff hold (A123) says nothing about the key, so it is not
    read here. Reads a CheckItem or a plaintext row."""
    get = item.get if isinstance(item, dict) else (lambda k: getattr(item, k, None))
    if get("canonical_verified"):
        return "verified"
    return "held" if key_held_flags(get("lint_flags"), False) else "unverified"


def audit_population(course_id: str) -> list[dict]:
    """The course's stored items an audit samples, by plaintext columns:
    every row that states a final answer (A34; a legacy row without one is
    never served). final_answer is read only to see that it is set — never
    decrypted, never filtered on (invariant 9) — and not returned. Paged."""
    out: list[dict] = []
    for row in page_all(
        table(_TABLE),
        _QUEUE_COLUMNS + ",final_answer",
        filters={"course_id": f"eq.{course_id}"},
        order="id",
    ):
        if row.get("final_answer") is None or not row.get("id"):
            continue
        out.append({k: v for k, v in row.items() if k != "final_answer"})
    return out


def course_audit_rows(course_id: str) -> list[dict]:
    """Every recorded audit verdict of the course (check_item_audits), paged."""
    return list(
        page_all(
            table(_AUDITS),
            _AUDIT_ROW_COLUMNS,
            filters={"course_id": f"eq.{course_id}"},
            order="question_hash",
        )
    )


def record_item_audit(item: CheckItem, verdict: str, *, auditor: str | None) -> str:
    """Record staff's verdict on a stored item's key and act on the item (see
    above). Returns the key status the audit row carries. Raises on a failed
    read or write: the caller answers 503, and recording the same verdict
    again finishes it (the row is upserted, the item updates are absolute)."""
    if verdict not in ITEM_AUDIT_VERDICTS:
        raise ValueError(f"unknown audit verdict {verdict!r}")
    scope = {"course_id": f"eq.{item.course_id}", "question_hash": f"eq.{item.question_hash}"}
    earlier = table(_AUDITS).select("key_status", filters=scope, limit=1) or []
    status = earlier[0].get("key_status") if earlier else key_status(item)
    table(_AUDITS).upsert(
        [
            {
                "course_id": item.course_id,
                "question_hash": item.question_hash,
                "item_id": item.id,
                "concept_key": item.concept_key,
                "format": item.format,
                "difficulty": item.difficulty,
                "key_status": status,
                "verdict": verdict,
                "audited_by": auditor,
                "audited_at": _utcnow().isoformat(),
            }
        ],
        on_conflict=_AUDITS_ON_CONFLICT,
    )
    code = _AUDIT_HOLD.get(verdict)
    # every row of the course item (one per concept that holds the question —
    # the same prompt): a never-linted one is linted from the audited item
    for row in table(_TABLE).select("id,lint_flags", filters=scope) or []:
        table(_TABLE).update(
            {
                "lint_flags": audited_flags(_linted(row.get("lint_flags"), item), code),
                "canonical_verified": verdict == CORRECT,
            },
            filters={"id": f"eq.{row['id']}"},
            prefer_return_minimal=True,
        )
    return status


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


#: Spec §13 A128: the one `documents.index_status` whose extracted-text
#: passages are NOT unsourced — indexing skipped by design (the #439 seam:
#: function mode, no key), a configured mode rather than a failure. Every
#: other status with no chunks (failed, exhausted, pending after a deferred
#: attempt, an unknown one) is a failed or unfinished index.
_SKIPPED_INDEX = "skipped"


def source_chunks(doc_row: dict) -> list[dict]:
    """The passages an item may be drafted from. Not a source → []. Indexed →
    its SHARED chunks only (none shared → [], never the fallback). Not indexed
    → its decrypted extracted_text, split by the indexer's block chunker into
    id-less passages (chunk_index 0, 1, …), so ranking bounds what each agent
    call carries exactly as for an indexed document — never the whole text in
    every batch. Every passage carries its `doc_id`. A128: a fallback passage
    of a document whose indexing FAILED (its `index_status` is anything but
    `skipped`) carries `unsourced: True`, and an item drafted from it that
    cites no chunk is stored with the `unsourced` code."""
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
    unsourced = doc_row.get("index_status") != _SKIPPED_INDEX
    if unsourced:
        logger.warning(
            "check items: document %s is not indexed (index_status=%s); drafting from "
            "its extracted text — items that cite no passage are stored `unsourced` (A128)",
            doc_id,
            doc_row.get("index_status"),
        )
    return [
        {
            "id": None,
            "chunk_index": i,
            "chunk_text": piece,
            "doc_id": doc_id,
            UNSOURCED: unsourced,
        }
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


class RetireOutcome(NamedTuple):
    """What a staff retire did (spec §13 A123)."""

    items: int  # stored rows of the question deleted (one per concept that held it)
    students: int  # students whose evidence was voided and state recomputed
    voided: int  # evidence rows voided


def retire_course_item(course_id: str, question_hash: str) -> RetireOutcome:
    """A113/A123: finish a STAFF retire of one question course-wide (the
    caller has recorded the 'retired' decision, so no new grade of it can
    commit and its rows are held — `staff_retired` — so nothing serves them
    while they wait here). First every student's evidence graded
    against it is VOIDED and their state recomputed from the rest of their
    journal — one apply_graph_update(void_evidence) per student with non-void
    rows left (learning.evidence_transaction.void_pending) — then every row
    of the course with this question_hash is deleted through
    retire_items_by_id, the A23/A34 retire path. Raises on any failure; the
    rows stay stored until every void is done, so the admin queue lists the
    item as retire-pending and a re-run finishes it (each void is idempotent,
    a finished student is no longer pending)."""
    from learning.evidence_transaction import void_pending
    from services.graph_service import apply_graph_update

    pending = void_pending(course_id, question_hash)
    for user_id in sorted(pending):
        apply_graph_update(user_id, {"void_evidence": {"question_hash": question_hash}}, course_id)
    rows = table(_TABLE).select(
        "id",
        filters={"course_id": f"eq.{course_id}", "question_hash": f"eq.{question_hash}"},
    )
    items = retire_items_by_id(r["id"] for r in rows or [] if r.get("id"))
    return RetireOutcome(items=items, students=len(pending), voided=sum(pending.values()))


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
    # A128: the call showed extracted-text passages of a document whose
    # indexing failed (`source_chunks`); a draft citing no chunk is unsourced
    unsourced: bool = False


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
    unsourced = False
    for ranked in ranked_lists:
        for chunk in ranked:
            pkey = _passage_key(chunk)
            if pkey in seen:
                continue
            seen.add(pkey)
            passages.append({"id": chunk.get("id"), "text": chunk.get("chunk_text") or ""})
            unsourced = unsourced or (not chunk.get("id") and chunk.get(UNSOURCED) is True)
            if chunk.get("doc_id"):
                shown_docs.add(chunk["doc_id"])
            if chunk.get("id"):
                allowed.add(chunk["id"])
    return _CallSources(passages, allowed, sorted(shown_docs), unsourced)


class _CallWrite(NamedTuple):
    stored: dict[str, _ConceptWrite]  # per concept whose write ran
    recheck_failed: bool = False  # the pre-write re-check failed: drafts dropped
    withdrawn: bool = False  # a source was withdrawn: drafts dropped, or items retired
    verify_failed: bool = False  # A119: the alignment check was unavailable: drafts dropped
    key_check_failed: bool = False  # A124: the key check was unavailable: drafts dropped


# ── alignment (A119) ───────────────────────────────────────────────────────
#
# One alignment check (agents/check_items_verify.py) per drafting call, over
# every draft the call left valid; learning/item_alignment.py applies its
# answers. The rule when the check is unavailable is FAIL CLOSED — the call's
# drafts are dropped, `learn.check_items_failed` (VerifyUnavailable) is
# reported, and the concepts count as unavailable, never as their own failure
# (A41's allowlist) — because an unchecked draft is exactly the population the
# check exists to stop, and the spec's other item guards fail the same way: a
# failed source re-check drops the call's drafts (A23), a failed retired-hash
# read drops the batch (A113), and an unavailable grade records nothing for
# either outcome (A22, invariant 28). A drop costs only a redraft: the next
# upload or the nightly backfill drafts every concept still below
# CHECK_ITEM_INITIAL_PER_CONCEPT. A stored item is never deleted on an outage
# (the backfill leaves it unchecked).

#: `learn.check_items_failed` reason when the alignment check was unavailable.
_VERIFY_UNAVAILABLE = "VerifyUnavailable"
#: How many characters of a dropped criterion the alignment log quotes.
_LOG_TEXT_CHARS = 120


class _Subject(NamedTuple):
    """What the alignment check reads of one item (agents.check_items_verify.
    VerifyItem without its per-call id)."""

    format: str
    prompt: str
    correct_option: str | None
    other_options: tuple[str, ...]
    criteria: tuple[str, ...]


def _draft_criteria(draft: CheckItemDraft) -> list[str]:
    """A draft's own criteria as stored_rubric numbers them (non-blank)."""
    return [t for t in draft.rubric if t.strip()]


def _draft_subject(draft: CheckItemDraft) -> _Subject:
    return _Subject(
        draft.format,
        draft.prompt,
        next((o.text for o in draft.options if o.is_correct), None),
        tuple(o.text for o in draft.options if not o.is_correct),
        tuple(_draft_criteria(draft)),
    )


def _item_subject(item: CheckItem) -> _Subject:
    options = item.options or []
    return _Subject(
        item.format,
        item.prompt,
        next((o.text for o in options if o.letter == item.correct_option), None),
        tuple(o.text for o in options if o.letter != item.correct_option),
        tuple(content_criteria(item)),
    )


def _verdicts_for(
    subjects: list[_Subject], scope: dict[str, str], *, deps: SaplingDeps, flex: bool
) -> list[Verdict | None] | None:
    """The alignment check's verdict for each subject, in order (None for one
    it left unanswered), CHECK_ITEM_VERIFY_MAX_ITEMS per call against the
    course concepts `scope` ({concept_key: name}). None when any call was
    unavailable: the caller's rule decides what that means."""
    names = list(scope.values())
    out: list[Verdict | None] = []
    for start in range(0, len(subjects), CHECK_ITEM_VERIFY_MAX_ITEMS):
        batch = subjects[start : start + CHECK_ITEM_VERIFY_MAX_ITEMS]
        items = [VerifyItem(str(n), *subject) for n, subject in enumerate(batch, start=1)]
        result = run_agent_sync(verify_items(names, items, deps=deps, flex=flex))
        if isinstance(result, CheckItemsUnavailable):
            return None
        found = verdicts(result)
        out.extend(found.get(item.id) for item in items)
    return out


def _retag_reason(name: str) -> str:
    """What the A37 top-up of the drafted concept is told about a draft the
    alignment check filed under another concept (it lost that item)."""
    return (
        f"concept: the question tests {' '.join(str(name).split())!r}, not this concept "
        "(alignment check); it was filed there"
    )


def _align_screened(
    screened: dict[str, list[_Screened]],
    scope: dict[str, str],
    *,
    deps: SaplingDeps,
    flex: bool,
    course_id: str,
) -> dict[str, list[_Screened]] | None:
    """A119: ONE alignment check over every valid draft of the call, applied
    in code by learning.item_alignment.align — an unasked criterion dropped
    (the stored rubric still ends with MC_REASON_CRITERION on an mc_reason
    item), a draft with no criterion left or testing no listed concept
    rejected, a draft that tests another listed concept moved under it. Each
    kept draft carries the check's flags and is stamped aligned. Returns the
    screened drafts per concept key (a re-tag can add a key), every drop with
    its reason in place; None when the check was unavailable (the caller
    fails closed). No valid draft → no call."""
    valid = [entry for rows in screened.values() for entry in rows if entry.draft is not None]
    if not valid:
        return screened
    found = _verdicts_for([_draft_subject(e.draft) for e in valid], scope, deps=deps, flex=flex)
    if found is None:
        return None
    verdict_at = iter(found)  # `valid` order: the loop below walks the same order
    out: dict[str, list[_Screened]] = {key: [] for key in screened}
    checked = trimmed = dropped_criteria = retagged = rejected = unverified = 0
    for key, rows in screened.items():
        for entry in rows:
            if entry.draft is None:
                out[key].append(entry)
                continue
            checked += 1
            criteria = _draft_criteria(entry.draft)
            result = align(len(criteria), key, next(verdict_at), scope)
            if result.reject:
                if result.unverified:
                    unverified += 1
                else:
                    rejected += 1
                logger.warning(
                    "check item draft dropped by the alignment check (course=%s concept=%s "
                    "format=%s): %s",
                    course_id,
                    key,
                    entry.format,
                    result.reject,
                )
                out[key].append(
                    _Screened(entry.format, None, result.reject, unverified=result.unverified)
                )
                continue
            draft = entry.draft
            if len(result.keep) < len(criteria):
                kept = [criteria[i] for i in result.keep]
                dropped = [c for i, c in enumerate(criteria) if i not in result.keep]
                trimmed += 1
                dropped_criteria += len(dropped)
                logger.info(
                    "check item draft: %d criterion(s) the question does not ask for dropped "
                    "(course=%s concept=%s format=%s): %s",
                    len(dropped),
                    course_id,
                    key,
                    entry.format,
                    " | ".join(c[:_LOG_TEXT_CHARS] for c in dropped),
                )
                draft = draft.model_copy(update={"rubric": kept})
            target = result.concept_key
            if target != key:
                retagged += 1
                name = scope.get(target, target)
                logger.info(
                    "check item draft re-tagged by the alignment check (course=%s format=%s): "
                    "%s -> %s",
                    course_id,
                    entry.format,
                    key,
                    target,
                )
                draft = draft.model_copy(update={"concept": name})
                out[key].append(_Screened(entry.format, None, _retag_reason(name)))
            out.setdefault(target, []).append(
                _Screened(entry.format, draft, flags=result.flags, aligned=True)
            )
    logger.info(
        "check items alignment (course=%s): %d draft(s) checked, %d trimmed (%d criteria "
        "dropped), %d re-tagged, %d rejected, %d unverified",
        course_id,
        checked,
        trimmed,
        dropped_criteria,
        retagged,
        rejected,
        unverified,
    )
    return out


# ── keys (A124) ────────────────────────────────────────────────────────────
#
# After the alignment check, every draft the call still holds valid is solved
# BLIND on the check_items_solve slot (agents/check_items_solve.py: question,
# an mc_reason item's options under their stored letters, the call's passages;
# never the key, rubric or reference), CHECK_ITEM_SOLVE_MAX_ITEMS per call, and
# learning/item_keys.py compares each answer with the key in code. A free-text
# pair code cannot settle (not the same answer tokens) goes to ONE key-match
# call per solve call (agents/check_items_key_match.py). Agreement stores the
# item verified; a different answer or "the passages do not settle one" stores
# it HELD with its code (never served, listed for staff); a draft with no
# usable answer is dropped alone (the check's outcome, not its concept's). The
# rule when either call is unavailable is FAIL CLOSED, as A119's: the call's
# drafts are dropped, `learn.check_items_failed` (KeyCheckUnavailable) is
# reported, and the concepts count as unavailable, never as their own failure
# (A41) — an unchecked key is exactly what the check exists to stop, and a drop
# costs only a redraft. A stored item is never changed on an outage.

#: `learn.check_items_failed` reason when the key check was unavailable.
_KEY_CHECK_UNAVAILABLE = "KeyCheckUnavailable"


def _draft_key_subject(draft: CheckItemDraft) -> KeySubject:
    """A valid draft as the key check reads it: an mc_reason draft's options
    under the letters it will be STORED with (checks.lettered_options with the
    server's slot key, exactly as _build_row letters them), so the letter the
    solver picks is compared with the stored correct letter."""
    options: tuple[tuple[str, str], ...] = ()
    letter = None
    if draft.format == _MC_REASON:
        lettered, letter = lettered_options(draft, slot_key=derive_key(OPTION_SLOT_PURPOSE))
        options = tuple((o.letter, o.text) for o in lettered)
    numeric = draft.answer_kind == _NUMERIC
    return KeySubject(
        draft.format,
        draft.prompt,
        options,
        draft.answer_kind,
        letter,
        draft.canonical_answer if numeric else None,
        parse_tolerance(draft),
        draft.final_answer,
    )


def _item_key_subject(item: CheckItem) -> KeySubject:
    """A stored item as the key check reads it (its stored options and key)."""
    return KeySubject(
        item.format,
        item.prompt,
        tuple((o.letter, o.text) for o in item.options or []),
        item.answer_kind,
        item.correct_option,
        item.canonical_answer if item.answer_kind == _NUMERIC else None,
        item.tolerance,
        item.final_answer or "",
    )


def _key_checks_for(
    subjects: list[KeySubject], passages: list[dict], *, deps: SaplingDeps, flex: bool
) -> list[KeyCheck] | None:
    """The key check's decision for each subject, in order: a blind solve of
    CHECK_ITEM_SOLVE_MAX_ITEMS subjects per call from `passages`, compared in
    code, and one key-match call over that batch's free-text pairs code could
    not settle. None when any call was unavailable: the caller's rule decides
    what that means."""
    out: list[KeyCheck] = []
    for start in range(0, len(subjects), CHECK_ITEM_SOLVE_MAX_ITEMS):
        batch = subjects[start : start + CHECK_ITEM_SOLVE_MAX_ITEMS]
        ids = [str(n) for n in range(1, len(batch) + 1)]
        items = [
            SolveItem(i, s.format, s.prompt, s.options, s.answer_kind) for i, s in zip(ids, batch)
        ]
        result = run_agent_sync(solve_items(passages, items, deps=deps, flex=flex))
        if isinstance(result, CheckItemsUnavailable):
            return None
        solved = solutions(result)
        outcomes = [compare(s, solved.get(i)) for i, s in zip(ids, batch)]
        pairs = [
            MatchItem(i, s.prompt, s.final_answer, solved[i].answer)
            for i, s, outcome in zip(ids, batch, outcomes)
            if outcome == TO_MATCH
        ]
        same: dict[str, bool] = {}
        if pairs:
            found = run_agent_sync(match_keys(pairs, deps=deps, flex=flex))
            if isinstance(found, CheckItemsUnavailable):
                return None
            same = matches(found)
        out.extend(settle(outcome, same.get(i)) for i, outcome in zip(ids, outcomes))
    return out


def _solve_screened(
    screened: dict[str, list[_Screened]],
    passages: list[dict],
    *,
    deps: SaplingDeps,
    flex: bool,
    course_id: str,
) -> dict[str, list[_Screened]] | None:
    """A124: the key check over every valid draft of the call, from the
    passages the call drafted from. Agreed → kept, `verified`; disputed or not
    settled by the passages → kept HELD (its hold code added to its flags, its
    reason kept for the A37 top-up); no usable answer → dropped alone
    (`unverified`). Every kept draft is marked key-checked. Returns the screened
    drafts per concept key, every drop with its reason in place; None when the
    check was unavailable (the caller fails closed). No valid draft → no call."""
    valid = [entry for rows in screened.values() for entry in rows if entry.draft is not None]
    if not valid:
        return screened
    found = _key_checks_for(
        [_draft_key_subject(e.draft) for e in valid], passages, deps=deps, flex=flex
    )
    if found is None:
        return None
    check_at = iter(found)  # `valid` order: the loop below walks the same order
    out: dict[str, list[_Screened]] = {}
    verified = held = unverified = 0
    for key, rows in screened.items():
        out[key] = []
        for entry in rows:
            if entry.draft is None:
                out[key].append(entry)
                continue
            check = next(check_at)
            if check.unverified:
                unverified += 1
                logger.warning(
                    "check item draft dropped by the key check (course=%s concept=%s "
                    "format=%s): %s",
                    course_id,
                    key,
                    entry.format,
                    check.reason,
                )
                out[key].append(_Screened(entry.format, None, check.reason or "", unverified=True))
                continue
            if check.verified:
                verified += 1
                out[key].append(entry._replace(verified=True, key_checked=True))
                continue
            held += 1
            logger.warning(
                "check item draft HELD by the key check (course=%s concept=%s format=%s "
                "question_hash=%s): %s",
                course_id,
                key,
                entry.format,
                question_hash(entry.draft.prompt)[:12],
                check.flag,
            )
            out[key].append(
                entry._replace(
                    flags=(*entry.flags, check.flag), reasons=check.reason or "", key_checked=True
                )
            )
    logger.info(
        "check items key check (course=%s): %d draft(s) solved, %d verified, %d held, "
        "%d unverified",
        course_id,
        len(valid),
        verified,
        held,
        unverified,
    )
    return out


def _write_checked(
    drafts_by_key: dict[str, list[CheckItemDraft]],
    sources: _CallSources,
    *,
    gone: set[str],
    user_id: str | None,
    document_id: str | None,
    course_id: str,
    scope: dict[str, str],
    deps: SaplingDeps,
    flex: bool,
    limit: int | None = None,
    exclude_ids: Iterable[str] = (),
) -> _CallWrite:
    """One call's write: its drafts screened (repair, validation), then the
    A119 alignment check against the run's course concepts `scope`, then the
    A124 key check (a blind solve from the call's passages), then A23's source
    re-check on both sides of the write. A concept whose write fails is
    reported (StorageError) and left out of `stored`; a withdrawn source is
    added to `gone`. An unavailable alignment check drops the call's drafts
    (fail closed, `verify_failed`), and so does an unavailable key check
    (`key_check_failed`). `limit` and `exclude_ids` (the top-up's) bind the
    call's own concepts; a concept a draft was re-tagged to is stored under no
    cap."""
    screened = {key: _screen(course_id, key, drafts) for key, drafts in drafts_by_key.items()}
    aligned = _align_screened(screened, scope, deps=deps, flex=flex, course_id=course_id)
    if aligned is None:
        logger.warning(
            "check items: the alignment check was unavailable (course=%s); the call's "
            "drafts are dropped — fail closed, a later run drafts them again (A119)",
            course_id,
        )
        _report_failure(user_id, document_id, course_id, _VERIFY_UNAVAILABLE)
        return _CallWrite({}, verify_failed=True)
    aligned = _solve_screened(
        aligned, sources.passages, deps=deps, flex=flex, course_id=course_id
    )
    if aligned is None:
        logger.warning(
            "check items: the key check was unavailable (course=%s); the call's drafts "
            "are dropped — fail closed, a later run drafts them again (A124)",
            course_id,
        )
        _report_failure(user_id, document_id, course_id, _KEY_CHECK_UNAVAILABLE)
        return _CallWrite({}, key_check_failed=True)
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
    for key, entries in aligned.items():
        try:
            stored[key] = _store_screened(
                course_id,
                key,
                document_id,
                entries,
                allowed_chunk_ids=sources.allowed,
                source_document_ids=sources.source_docs,
                limit=limit if key in drafts_by_key else None,
                exclude_ids=exclude_ids,
                unsourced=sources.unsourced,
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


def _stored_items(course_id: str, key: str) -> dict[str, tuple[str | None, int | None, bool]]:
    """The concept's stored items, id -> (format, difficulty, held) (plaintext
    columns only, invariant 9; held = A124's key hold)."""
    rows = table(_TABLE).select(
        "id,format,difficulty,lint_flags,canonical_verified",
        filters={"course_id": f"eq.{course_id}", "concept_key": f"eq.{key}"},
    )
    return {
        r["id"]: (r.get("format"), r.get("difficulty"), _row_held(r))
        for r in rows or []
        if r.get("id")
    }


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


class _TopUp(NamedTuple):
    """What a concept's top-up stored."""

    created: int  # rows written, under any concept (a re-tagged draft's included)
    own: int  # of those, the concept's own
    # A119/A124: the alignment or the key check was unavailable or left drafts unanswered
    unverified: bool


_NO_TOPUP = _TopUp(0, 0, False)


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
    scope: dict[str, str],
) -> int:
    """A37 (series coordinator's ruling, 2026-09-28): a concept this pass
    drafted that ends it with fewer than CHECK_ITEM_MC_MIN_PER_CONCEPT stored
    mc_reason items gets up to CHECK_ITEM_MC_TOPUP_CALLS focused calls, each
    for exactly the missing count at difficulties the concept lacks, shown
    the concept's own passages and told why its mc_reason drafts were
    dropped. The drafts pass the same repair and validation (no rule is
    relaxed), the same A119 alignment check against the run's concepts
    `scope`, the same A124 key check, and the write the same A23 re-checks.
    The count is the one read after the pass's write, which alone says what
    the concept holds (a pass item retired meanwhile is not counted, nor a
    held one: it serves no one, A124); a top-up draft whose prompt a stored
    item already has is a repeat, not stored. Each call is billed by
    the agent (llm_usage feature check_items_topup) and counted here
    (`learn.check_items_topup`). A concept still below is logged with its drop
    reasons and left to a later generation run or backfill, which drafts it
    again only while it has fewer than CHECK_ITEM_INITIAL_PER_CONCEPT items.
    Returns what the top-up stored (`_TopUp`)."""
    if len(first.mc_reason) >= CHECK_ITEM_MC_MIN_PER_CONCEPT:
        return _NO_TOPUP  # this pass alone stored enough: no read, no call
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
        return _NO_TOPUP
    have = {i: d for i, (fmt, d, held) in stored_items.items() if fmt == _MC_REASON and not held}
    exclude = set(stored_items)
    drops = list(first.mc_drops)
    created = own = calls = 0
    unverified = False
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
            {key: mine},
            sources,
            gone=gone,
            limit=missing,
            exclude_ids=exclude,
            scope=scope,
            deps=deps,
            flex=flex,
            **recheck,
        )
        result = write.stored.get(key)
        stored = len(result.ids) if result is not None else 0
        # as the pass counts its own: written, even if retired right after —
        # a draft the A119 check filed under another concept included
        created += sum(len(w.ids) for w in write.stored.values())
        own += stored
        unverified |= (
            write.verify_failed
            or write.key_check_failed
            or bool(result is not None and result.unverified)
        )
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
    return _TopUp(created, own, unverified)


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
# exception count for no concept. A multi-concept call whose output never
# validated is split and each concept re-run alone once (A38 fix round 2), so
# only the concept that fails on its own is counted.

_FAILURES_TABLE = "check_item_draft_failures"
_FAILURES_ON_CONFLICT = "course_id,concept_key"
# The only Unavailable reason that is the drafts' fault: the output failed
# validation on every retry (pydantic-ai raises UnexpectedModelBehavior).
_CONCEPT_FAILURE_REASONS = frozenset({"UnexpectedModelBehavior"})


def _drafting_version() -> str:
    """The drafting prompts' versions and the model, the A119 alignment
    check's prompt and model, and the A124 key check's prompts and model (each
    decides what of a draft is stored): a change to any is a new source, so a
    concept stalled under the old one is drafted again."""
    from agents import (
        check_items,
        check_items_key_match,
        check_items_solve,
        check_items_topup,
        check_items_verify,
    )
    from agents._providers import model_name_for

    return "|".join(
        (
            check_items._PROMPT_HASH,
            check_items_topup._PROMPT_HASH,
            model_name_for("check_items"),
            check_items_verify._PROMPT_HASH,
            model_name_for("check_items_verify"),
            check_items_solve._PROMPT_HASH,
            check_items_key_match._PROMPT_HASH,
            model_name_for("check_items_solve"),
        )
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
                "concept_key,failures,source_fp,updated_at,solo",
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

    def _fresh(self, row: dict) -> bool:
        stamp = _parse_stamp(row.get("updated_at"))
        ttl = timedelta(days=CHECK_ITEM_REDRAFT_FAILURE_TTL_DAYS)
        return stamp is not None and _utcnow() - stamp < ttl

    def solo(self, key: str, fp: str) -> bool:
        """Drafted alone: a split rescued it and every batch-mate on an
        unchanged source, within the TTL (A38 fix round 3)."""
        row = self.rows.get(key)
        return bool(row and row.get("solo") and row.get("source_fp") == fp and self._fresh(row))

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
        return self._fresh(row)

    def _write(self, key: str, failures: int, fp: str, *, solo: bool | None = None) -> None:
        old = self.rows.get(key) or {}
        if solo is None:  # kept while the source is unchanged
            solo = bool(old.get("solo")) and old.get("source_fp") == fp
        row = {
            "course_id": self.course_id,
            "concept_key": key,
            "failures": failures,
            "source_fp": fp,
            "solo": solo,
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

    def mark_solo(self, key: str, fp: str) -> None:
        self._write(key, 0, fp, solo=True)


class _SplitGroup:
    """The concepts of one split batch, as their solo re-runs settle. When the
    last one settles and every one stored items alone, the failure was the
    combination's: each is marked solo (A38 fix round 3)."""

    def __init__(self, batch: list):
        self.fps = {key: _source_fingerprint(ranked) for key, _, ranked in batch}
        self.ok: dict[str, bool] = {}

    def settle(self, key: str, *, ok: bool, ledger: _DraftFailures) -> None:
        if key not in self.fps or key in self.ok:
            return
        self.ok[key] = ok
        if len(self.ok) == len(self.fps) and all(self.ok.values()):
            for k, fp in self.fps.items():
                ledger.mark_solo(k, fp)


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
    Every call's drafts go through the A119 alignment check against ALL of
    the run's concept names (the scope a draft may be re-tagged into, the
    `max_concepts` cut and the skipped keys included), then the A124 key
    check (a blind solve from the call's passages: agreed → verified,
    disputed → stored held); an unavailable check drops the call's drafts and
    counts its concepts unavailable.
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
    # A119: the concepts a draft may be found to test (and re-tagged into)
    scope = dict(names_by_key)
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
    # (batch, split): a multi-concept call whose output never validated is
    # re-run one concept at a time, once, so the failure lands on the concept
    # that caused it and its batch-mates still get items this pass (A38 fix
    # round 2). At most 1 + CHECK_ITEM_CONCEPTS_PER_CALL calls per batch.
    # A concept whose last split rescued its whole batch (it and its mates
    # each drafted fine alone) is drafted alone while that holds (A38 fix
    # round 3), so a combination-only failure does not cost 1 + N calls a pass.
    solo = [t for t in todo if ledger.solo(t[0], _source_fingerprint(t[2]))]
    rest = [t for t in todo if t not in solo]
    queue: deque[tuple[list, _SplitGroup | None]] = deque(
        [([t], None) for t in solo]
        + [
            (rest[start : start + CHECK_ITEM_CONCEPTS_PER_CALL], None)
            for start in range(0, len(rest), CHECK_ITEM_CONCEPTS_PER_CALL)
        ]
    )
    while queue:
        batch, group = queue.popleft()
        split = group is not None
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
        if not split:  # a split re-run is the same concepts' same attempt
            attempted += len(batch)
        if isinstance(out, CheckItemsUnavailable):
            _report_failure(user_id, document_id, course_id, out.reason)
            if out.reason in _CONCEPT_FAILURE_REASONS and len(batch) > 1:
                new_group = _SplitGroup(list(batch))
                queue.extendleft(([concept], new_group) for concept in reversed(batch))
                continue
            if group is not None:
                group.settle(batch[0][0], ok=False, ledger=ledger)
            unavailable += len(batch)
            # Only a one-concept call's validation failure is that concept's
            # own outcome; anything else is no concept's fault (M2 allowlist).
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
            scope=scope,
            deps=deps,
            flex=flex,
        )
        if write.recheck_failed or write.verify_failed or write.key_check_failed:
            # no concept's fault: neither a re-check blip nor an unavailable
            # alignment check (A119) or key check (A124) is counted for a
            # concept (A41)
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
                    scope=scope,
                )
                created += topped.created
                # A write that failed (StorageError) is not the drafts' fault:
                # only a concept whose write ran is counted either way — and a
                # concept whose drafts the A119 check left unanswered is not
                # counted as failing (the check's outcome, not the concept's).
                fp = _source_fingerprint(ranked)
                ok = bool(write.stored[key].ids or topped.own)
                if ok:
                    ledger.succeeded(key, fp)
                elif not (write.stored[key].unverified or topped.unverified):
                    ledger.failed(key, fp)
                if group is not None:
                    group.settle(key, ok=ok, ledger=ledger)
            elif group is not None:
                group.settle(key, ok=False, ledger=ledger)

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
    of its concepts. Usage is attributed to the uploader.

    A128: it records how drafting ended on the document's row
    (`check_items_status`, `drafting_status_for`): `done`, `unavailable` (a
    model or check was unavailable for some concept: a later run drafts it),
    or `failed` (an exception escaped — re-raised). The upload hook set
    `pending` first (`mark_drafting`); `drafting_pending` reads it."""
    if not config.LEARNING_LOOP_ENABLED:
        return _NOTHING
    try:
        outcome = _generate_for_document(
            document_id,
            user_id=user_id,
            course_id=course_id,
            concept_names=concept_names,
            flex=flex,
        )
    except BaseException:
        mark_drafting(document_id, DRAFTING_FAILED)
        raise
    mark_drafting(document_id, drafting_status_for(outcome))
    return outcome


def _generate_for_document(
    document_id: str,
    *,
    user_id: str,
    course_id: str,
    concept_names: Iterable[str],
    flex: bool,
) -> GenerationOutcome:
    rows = table("documents").select(
        # index_status: A128 — an unindexed source drafts `unsourced` items
        # unless its indexing was skipped by design (`source_chunks`)
        "id,user_id,shareability,shareability_confidence,extracted_text,index_status",
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


# ── per-document drafting status (A128) ────────────────────────────────────
#
# `documents.check_items_status` (migration 20261108091912_learning_document_
# drafting.sql) says where an upload's check-item drafting is: `pending` from
# the upload hook until a run ends, then `done`, `unavailable` or `failed`;
# NULL = never drafted (a pre-A128 row, or the loop off). `check_items_at` is
# when the status was set. The loop reads it for one thing: while a student's
# own upload in a course with no servable item is still being drafted, the
# probe and "Check me" say "preparing", not "no check items". Bookkeeping
# only: a write that fails (or meets a database the migration has not reached)
# logs a WARNING and never fails an upload or a drafting run; a read that
# fails answers "not pending" — the pre-A128 state.

DRAFTING_PENDING = "pending"
DRAFTING_DONE = "done"
DRAFTING_FAILED = "failed"
DRAFTING_UNAVAILABLE = "unavailable"
#: The CHECK of `documents.check_items_status` (its migration pins the same list).
DRAFTING_STATUSES = (DRAFTING_PENDING, DRAFTING_DONE, DRAFTING_FAILED, DRAFTING_UNAVAILABLE)


def drafting_status_for(outcome: GenerationOutcome) -> str:
    """How a finished run ends a document's drafting: `unavailable` when any
    concept it attempted could not be drafted for want of a model or check
    (the run did not finish its work — a later one drafts it), else `done` —
    items stored, every concept already full, or nothing to draft from."""
    return DRAFTING_UNAVAILABLE if outcome.unavailable else DRAFTING_DONE


def _stamp(at: datetime) -> str:
    """UTC with a `Z`: the value also travels in a PostgREST filter."""
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def mark_drafting(document_id: str, status: str) -> None:
    """Record `status` (one of DRAFTING_STATUSES) on the document's row, now.
    Never raises on a failed write (bookkeeping, see above)."""
    if status not in DRAFTING_STATUSES:
        raise ValueError(f"not a drafting status: {status!r}")
    try:
        table("documents").update(
            {"check_items_status": status, "check_items_at": _stamp(_utcnow())},
            filters={"id": f"eq.{document_id}"},
            prefer_return_minimal=True,
        )
    except Exception as exc:
        # The class only, no traceback: bookkeeping, and before the migration
        # runs every upload meets it (a traceback per upload is noise).
        logger.warning(
            "check items: drafting status %r not recorded for document %s (%s)",
            status,
            document_id,
            type(exc).__name__,
        )


def drafting_pending(user_id: str, course_id: str | None) -> bool:
    """Whether one of the student's OWN live uploads in the course is still
    being drafted: `pending`, set within CHECK_ITEM_DRAFT_PENDING_TTL_S. The
    student's own, because the loop then says "from your upload" (and a
    classmate's upload is not theirs to hear about). One `limit=1` read; False
    on a read failure or when the course's offerings cannot be told."""
    if not course_id:
        return False
    try:
        offerings = course_offering_ids(course_id)
        if not offerings:
            return False
        cutoff = _stamp(_utcnow() - timedelta(seconds=CHECK_ITEM_DRAFT_PENDING_TTL_S))
        rows = table("documents").select(
            "id",
            filters={
                "user_id": f"eq.{user_id}",
                "offering_id": f"in.({','.join(pg_quote_value(o) for o in offerings)})",
                "check_items_status": f"eq.{DRAFTING_PENDING}",
                "check_items_at": f"gt.{cutoff}",
                "deleted_at": "is.null",
            },
            limit=1,
        )
    except Exception as exc:
        logger.warning(
            "check items: drafting status unreadable for course %s (%s); not preparing",
            course_id,
            type(exc).__name__,
        )
        return False
    return bool(rows)


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
