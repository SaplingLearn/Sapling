"""Showcase overlay for the learning loop: real check items for CS101.

Run it once the local stack is up and the rich seed has run (from backend/,
with backend/.env pointing at the LOCAL stack):

    python -m db.seed_showcase_loop

The rich local seed (db/seed_local_rich.py::seed_learning_loop) fills the
loop's check items with the E2E placeholder constants ("[e2e-loop] Check item:
type the e2e grader's correct token…"). The deterministic Chapter 1 journeys
assert on those strings, so the rich seed keeps them; but a person demoing or
smoke-testing the tutor with REAL models (SAPLING_MODEL_MODE=real) reads them
as nonsense questions. This overlay, in the spirit of db/seed_showcase.py,
replaces them for that person:

  - a shared course-material document, "cs101-lecture-notes.pdf", uploaded by
    rich-user-loop (who consents to sharing) and indexed into one shared
    course_chunks row per concept — the passages the items cite;
  - the hand-written bank in db/showcase_loop_items.py: 72 items, one per
    (concept, format, difficulty) for the eight CS101 concepts the rich seed
    puts on a graph — the loop users' Binary Numbers, Bitwise Operators and
    Two's Complement, and rich-user-active's Variables and Types, Control Flow,
    Recursion, Pointers and Memory and Algorithms;
  - and it deletes the rich seed's placeholder items (seed_local_rich.
    loop_item_id), so the loop never serves "[e2e-loop]" text beside them.

Each item is written exactly as services/check_item_service.py::_build_row
writes a drafted item that passed every check (tests/test_seed_showcase_loop.py
pins the parity): encrypted columns, the lettered options with the correct one
at the server-keyed slot (A37), the code-appended mc_reason criterion, the
item lint's flags (none — the test lints every item), and the marks of an item
whose alignment check (A119) and blind key check (A124) passed:
`canonical_verified`, `aligned_at` and `key_checked_at`. The post-test
reserves are not stored: learning.checks.posttest_reserve_hashes reads them off
each concept's bank (the free item at difficulty 2 and its parallel form).

NEVER part of an E2E lane: no script, Makefile target or workflow runs it, and
a test pins that. Should it ever meet an E2E database anyway, the per-test
reset (frontend/e2e/support/db.ts) truncates check_items and reseeds the
placeholders. Re-running seed_local_rich brings the placeholders back beside
the showcase items; run this overlay again afterwards. LOCAL ONLY (the rich
seed's guard), idempotent (upserts on the same keys, a delete by fixed ids).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import seed_helpers as h  # noqa: E402
from db.chunk_ids import SHARED, chunk_id  # noqa: E402
from db.connection import table  # noqa: E402
from db.seed_local_rich import (  # noqa: E402
    COURSE_CS,
    COURSE_CS_CODE,
    LOOP_DOC_CATEGORY,
    LOOP_DOC_SHAREABILITY_CONFIDENCE,
    LOOP_NODES,
    OFF_CS_S26,
    SEED_LOOP_FORMATS,
    USER_LOOP,
    _guard_local,
    _seed_embedding,
    loop_item_id,
)
from db.showcase_loop_items import CONCEPTS, DRAFTS, MC_REASON, passage_text  # noqa: E402
from learning.checks import (  # noqa: E402
    CheckItemDraft,
    common_wrong,
    item_id,
    lettered_options,
    normalize,
    parse_tolerance,
    question_hash,
    stored_rubric,
)
from learning.item_lint import lint_item  # noqa: E402
from learning.params import CHECK_ITEM_DIFFICULTIES  # noqa: E402
from services.encryption import derive_key, encrypt_if_present, encrypt_json  # noqa: E402

SHOWCASE_DOC_ID = "rich-doc-showcase-cs101-notes"
SHOWCASE_DOC_FILE = "cs101-lecture-notes.pdf"

#: What derive_key names the mc_reason option-slot secret: the SAME purpose
#: string as services/check_item_service.py::OPTION_SLOT_PURPOSE (the test pins
#: the two together), so a showcase item's correct letter is placed by the key
#: the service would use. Copied, not imported: a db module stays below
#: services (backend/.importlinter), services.encryption aside.
OPTION_SLOT_PURPOSE = "check_items.option_slot.v1"

_NUMERIC = "numeric"


def placeholder_item_ids() -> list[str]:
    """Every placeholder item seed_local_rich.seed_learning_loop writes."""
    return [
        loop_item_id(slug, fmt, difficulty)
        for slug, _, _ in LOOP_NODES
        for fmt in SEED_LOOP_FORMATS
        for difficulty in CHECK_ITEM_DIFFICULTIES
    ]


def concept_chunk_ids() -> dict[str, str]:
    """concept -> the shared course_chunks id of its passage (content-addressed
    over the PLAINTEXT, as services/document_indexing.py writes it)."""
    return {c: chunk_id(COURSE_CS_CODE, passage_text(c), visibility=SHARED) for c in CONCEPTS}


def item_row(draft: CheckItemDraft, *, chunk: str, stamp: str, slot_key: bytes) -> dict:
    """One check_items row for a showcase draft: the shape
    check_item_service._build_row writes for a draft whose alignment and key
    checks passed (verified, aligned and key-checked at `stamp`), citing its
    concept's passage `chunk` from the showcase document."""
    qh = question_hash(draft.prompt)  # PLAINTEXT, before encryption
    key = normalize(draft.concept)
    rubric = [r.model_dump() for r in stored_rubric(draft)]
    wrong = [w.model_dump() for w in common_wrong(draft)]
    options = correct_option = None
    texts: list[str] = []
    correct: int | None = None
    if draft.format == MC_REASON:
        lettered, letter = lettered_options(draft, slot_key=slot_key)
        options = encrypt_json([o.model_dump() for o in lettered])  # 🔒
        correct_option = encrypt_if_present(letter)  # 🔒
        texts = [o.text for o in lettered]
        correct = next(i for i, o in enumerate(lettered) if o.letter == letter)
    numeric = draft.answer_kind == _NUMERIC
    return {
        "id": item_id(COURSE_CS, key, qh),
        "course_id": COURSE_CS,
        "concept_key": key,
        "document_id": SHOWCASE_DOC_ID,
        "format": draft.format,
        "difficulty": draft.difficulty,
        "prompt": encrypt_if_present(draft.prompt),  # 🔒
        "reference_answer": encrypt_if_present(draft.reference_answer),  # 🔒
        "final_answer": encrypt_if_present(draft.final_answer),  # 🔒 A34
        "rubric_json": encrypt_if_present(json.dumps(rubric)),  # 🔒
        "common_wrong_json": encrypt_if_present(json.dumps(wrong)),  # 🔒
        "options_json": options,
        "correct_option": correct_option,
        "answer_kind": draft.answer_kind,
        "canonical_answer": encrypt_if_present(draft.canonical_answer) if numeric else None,  # 🔒
        "tolerance": parse_tolerance(draft),
        # A22/A124: what an agreeing blind solve sets; the bank is hand-checked.
        "canonical_verified": True,
        "stepwise": draft.stepwise,
        "source_chunk_ids": [chunk],
        "source_document_ids": [SHOWCASE_DOC_ID],
        "question_hash": qh,
        "graded": False,  # A32: practice material, never graded coursework
        # A113: the item lint over the stored shape ([] for every showcase item).
        "lint_flags": lint_item(draft.prompt, texts, correct),
        "aligned_at": stamp,  # A119: the alignment check passed
        "key_checked_at": stamp,  # A124: the key check ran (and agreed)
    }


def showcase_rows(stamp: str, slot_key: bytes) -> list[dict]:
    chunks = concept_chunk_ids()
    return [item_row(d, chunk=chunks[d.concept], stamp=stamp, slot_key=slot_key) for d in DRAFTS]


def seed_showcase_document() -> None:
    """The shared course-material document and its index, exactly as the rich
    seed writes its loop document: content-addressed ids over the PLAINTEXT,
    🔒 chunk_text encrypted after hashing (ADR 0025), an embedding, and the
    contributor ledger row (#629)."""
    for i, (concept, cid) in enumerate(concept_chunk_ids().items()):
        text = passage_text(concept)
        h.upsert(
            "course_chunks",
            {
                "id": cid,
                "course_id": COURSE_CS_CODE,
                "doc_id": SHOWCASE_DOC_ID,
                "uploader_id": USER_LOOP,
                "chunk_index": i,
                "chunk_text": encrypt_if_present(text),  # 🔒
                "chunk_hash": cid,
                "embedding": _seed_embedding(text),
                "category": LOOP_DOC_CATEGORY,
                "visibility": SHARED,
                "semester": "current",
                "section_id": None,
                "school": "",
            },
            on_conflict="id",
        )
        h.upsert(
            "course_chunk_contributors",
            {"chunk_id": cid, "user_id": USER_LOOP},
            on_conflict="chunk_id,user_id",
        )
    h.upsert(
        "documents",
        {
            "id": SHOWCASE_DOC_ID,
            "user_id": USER_LOOP,
            "offering_id": OFF_CS_S26,
            "file_name": SHOWCASE_DOC_FILE,
            "category": LOOP_DOC_CATEGORY,
            # 🔒 summary / concept_notes / extracted_text
            "summary": encrypt_if_present(
                "CS101 lecture notes: binary numbers, bitwise operators, two's complement, "
                "variables and types, control flow, recursion, pointers and memory, and "
                "algorithms."
            ),
            "concept_notes": encrypt_json(
                [{"name": c, "description": passage_text(c)} for c in CONCEPTS]
            ),
            "extracted_text": encrypt_if_present("\n\n".join(passage_text(c) for c in CONCEPTS)),
            "shareability": "course_material",
            "shareability_confidence": LOOP_DOC_SHAREABILITY_CONFIDENCE,
            "index_status": "indexed",
            "index_chunk_count": len(CONCEPTS),
        },
        on_conflict="id",
    )


def remove_placeholder_items() -> int:
    """Delete the rich seed's placeholder items; returns how many went. No
    table references check_items, and the loop's evidence keys on the
    question hash, so nothing else needs removing."""
    ids = placeholder_item_ids()
    deleted = table("check_items").delete(filters={"id": f"in.({','.join(ids)})"}) or []
    return len(deleted)


def seed_showcase_items() -> None:
    stamp = datetime.now(timezone.utc).isoformat()
    for row in showcase_rows(stamp, derive_key(OPTION_SLOT_PURPOSE)):
        h.upsert("check_items", row, on_conflict="course_id,concept_key,question_hash")


def main() -> None:
    _guard_local()
    h.reset_counts()
    seed_showcase_document()
    removed = remove_placeholder_items()
    seed_showcase_items()
    h.print_summary(
        ["documents", "course_chunks", "course_chunk_contributors", "check_items"],
        "Learning-loop showcase overlay (on top of the rich local seed):",
    )
    print(f"  {'placeholder items removed':26s} {removed}")
    print(f"  {'concepts':26s} {', '.join(CONCEPTS)}")


if __name__ == "__main__":
    main()
