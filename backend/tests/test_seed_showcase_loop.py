"""The learning-loop showcase overlay (db/seed_showcase_loop.py) and its
hand-written CS101 bank (db/showcase_loop_items.py).

Hermetic: the seed's `table` and db.seed_helpers' `table` are replaced by a
recorder, so nothing reaches PostgREST, and no model is called. What is pinned:
every item passes the drafting path's own repair, validation and item lint;
every CS101 concept on a seeded graph has one item per (format, difficulty);
each row is the row services/check_item_service.py::_build_row writes for a
verified, aligned, key-checked draft; the rows hydrate as servable items that
leave the post-test its two reserves and the probe its items; the overlay
removes exactly the rich seed's placeholders; and no E2E lane runs it."""

from __future__ import annotations

import json
from collections import Counter
from itertools import product
from pathlib import Path

import pytest

from db import seed_helpers
from db import seed_local_rich as rich
from db import seed_showcase_loop as overlay
from db.showcase_loop_items import CONCEPTS, DRAFTS, MC_REASON, PASSAGES
from learning.checks import (
    is_servable,
    posttest_reserve_hashes,
    repair_draft,
    validate_draft,
)
from learning.item_lint import lint_check_item, lint_item
from learning.params import (
    CHECK_ITEM_DIFFICULTIES,
    CHECK_ITEM_FORMATS,
    CHECK_ITEM_INITIAL_PER_CONCEPT,
    CHECK_ITEM_MC_MIN_PER_CONCEPT,
    PROBE_ITEMS_PER_SKILL_MIN,
)
from services import check_item_service
from services.check_item_service import _build_row, _row_to_item
from services.encryption import decrypt_if_present
from services.graph_service import _normalize_concept

REPO = Path(__file__).resolve().parents[2]
STAMP = "2026-11-10T00:00:00+00:00"
SLOT_KEY = b"showcase-test-slot-key"


def _cs101_concepts() -> set[str]:
    loop = {name for _, name, _ in rich.LOOP_NODES}
    active = {name for _, name, _ in rich._GRAPH_NODES[rich.COURSE_CS]}
    return loop | active


# ── the bank ────────────────────────────────────────────────────────────────


def test_the_bank_covers_every_cs101_concept_on_a_seeded_graph():
    assert set(CONCEPTS) == set(PASSAGES) == _cs101_concepts()
    assert {d.concept for d in DRAFTS} == set(CONCEPTS)


def test_each_concept_has_one_item_per_format_and_difficulty():
    cells = Counter((d.concept, d.format, d.difficulty) for d in DRAFTS)
    expected = {
        (c, f, n) for c, f, n in product(CONCEPTS, CHECK_ITEM_FORMATS, CHECK_ITEM_DIFFICULTIES)
    }
    assert set(cells) == expected
    assert set(cells.values()) == {1}
    for concept in CONCEPTS:
        assert sum(1 for d in DRAFTS if d.concept == concept) == CHECK_ITEM_INITIAL_PER_CONCEPT


@pytest.mark.parametrize("draft", DRAFTS, ids=lambda d: f"{d.concept}-{d.format}-d{d.difficulty}")
def test_every_item_passes_repair_validation_and_lint(draft):
    """The drafting path's own gates (learning.checks.repair_draft /
    validate_draft, the A113 item lint): nothing to repair, nothing invalid,
    no flag — in every option order, since the lint's rules read none."""
    fixed, repairs = repair_draft(draft)
    assert repairs == []
    assert validate_draft(draft) == []
    texts = [o.text for o in draft.options]
    correct = next((i for i, o in enumerate(draft.options) if o.is_correct), None)
    assert lint_item(draft.prompt, texts, correct) == []
    assert "[e2e" not in draft.prompt + draft.reference_answer


def test_mc_reason_distractors_each_carry_a_misconception():
    for draft in DRAFTS:
        if draft.format != MC_REASON:
            assert draft.options == [] and len(draft.wrong_keys) == len(draft.wrong_texts) >= 1
            continue
        distractors = [o for o in draft.options if not o.is_correct]
        assert len(distractors) == len(draft.options) - 1
        assert all(o.misconception_key and o.misconception_text for o in distractors)
        assert draft.final_answer == next(o.text for o in draft.options if o.is_correct)


# ── the rows ────────────────────────────────────────────────────────────────


def _identity_encryption(monkeypatch, module):
    monkeypatch.setattr(module, "encrypt_if_present", lambda v: None if v is None else f"enc:{v}")
    monkeypatch.setattr(
        module, "encrypt_json", lambda v: "enc:" + json.dumps(v, separators=(",", ":"))
    )


def test_rows_are_the_service_writers_rows_for_a_verified_draft(monkeypatch):
    """Parity with services/check_item_service.py::_build_row: the same
    columns and values for a draft whose alignment (A119) and key (A124) checks
    passed, the option slot keyed by the same purpose string."""
    assert overlay.OPTION_SLOT_PURPOSE == check_item_service.OPTION_SLOT_PURPOSE
    for module in (overlay, check_item_service):
        _identity_encryption(monkeypatch, module)
    monkeypatch.setattr(check_item_service, "derive_key", lambda purpose: SLOT_KEY)
    chunks = overlay.concept_chunk_ids()
    for draft in DRAFTS:
        mine = overlay.item_row(draft, chunk=chunks[draft.concept], stamp=STAMP, slot_key=SLOT_KEY)
        key = _normalize_concept(draft.concept)
        theirs = _build_row(
            rich.COURSE_CS,
            key,
            overlay.SHOWCASE_DOC_ID,
            draft.model_copy(update={"chunk_ids": [chunks[draft.concept]]}),
            allowed={chunks[draft.concept]},
            source_docs=[overlay.SHOWCASE_DOC_ID],
            aligned_at=STAMP,
            verified=True,
            key_checked_at=STAMP,
        )
        assert mine == theirs, draft.prompt
        assert mine["concept_key"] == key  # learning.checks.normalize == graph_service's rule


def _rows() -> list[dict]:
    return overlay.showcase_rows(STAMP, SLOT_KEY)


def test_rows_hydrate_as_verified_servable_lint_clean_items():
    for row in _rows():
        assert decrypt_if_present(row["prompt"]) != row["prompt"], "prompt stored in plaintext"
        item = _row_to_item(row)
        assert is_servable(item)
        assert item.canonical_verified and row["aligned_at"] and row["key_checked_at"]
        assert item.lint_flags == [] == lint_check_item(item)
        assert item.source_chunk_ids and item.graded is False
        if item.format == MC_REASON:
            right = next(o for o in item.options if o.letter == item.correct_option)
            assert right.wrong_key is None and right.text == item.final_answer
            assert all(o.wrong_key for o in item.options if o is not right)
            assert {w.key for w in item.common_wrong} == {
                o.wrong_key for o in item.options if o.wrong_key
            }


def test_each_concept_keeps_two_posttest_reserves_and_its_practice():
    by_key: dict[str, list] = {}
    for row in _rows():
        by_key.setdefault(row["concept_key"], []).append(_row_to_item(row))
    assert set(by_key) == {_normalize_concept(c) for c in CONCEPTS}
    for key, items in by_key.items():
        reserves = posttest_reserve_hashes(items)
        assert len(reserves) == 2, key
        first = next(i for i in items if i.question_hash == reserves[0])
        assert (first.format, first.difficulty) == ("free", CHECK_ITEM_DIFFICULTIES[1])
        left = [i for i in items if i.question_hash not in reserves]
        assert len(left) >= PROBE_ITEMS_PER_SKILL_MIN
        assert sum(1 for i in items if i.format == MC_REASON) >= CHECK_ITEM_MC_MIN_PER_CONCEPT


# ── the overlay ─────────────────────────────────────────────────────────────


class _Recorder:
    def __init__(self):
        self.rows: dict[str, list[dict]] = {}
        self.deletes: list[tuple[str, dict]] = []

    def __call__(self, name):
        rec = self

        class _T:
            def select(self, cols, filters=None, limit=None, **kw):
                return []

            def upsert(self, row, on_conflict=None):
                rec.rows.setdefault(name, []).append(row)

            def insert(self, row):
                rec.rows.setdefault(name, []).append(row)

            def delete(self, filters):
                rec.deletes.append((name, filters))
                return []

        return _T()


@pytest.fixture
def recorder(monkeypatch):
    r = _Recorder()
    monkeypatch.setattr(seed_helpers, "table", r)
    monkeypatch.setattr(rich, "table", r)
    monkeypatch.setattr(overlay, "table", r)
    seed_helpers.reset_counts()
    return r


def test_overlay_removes_exactly_the_rich_seeds_placeholders(recorder):
    rich.seed_learning_loop()
    placeholders = [r["id"] for r in recorder.rows["check_items"]]
    overlay.remove_placeholder_items()
    ((name, filters),) = recorder.deletes
    assert name == "check_items" and list(filters) == ["id"]
    assert filters["id"] == f"in.({','.join(placeholders)})"
    assert sorted(placeholders) == sorted(overlay.placeholder_item_ids())


def test_overlay_writes_a_shared_indexed_document_the_items_cite(recorder):
    overlay.seed_showcase_document()
    overlay.seed_showcase_items()
    chunks = recorder.rows["course_chunks"]
    assert len(chunks) == len(CONCEPTS)
    assert all(
        c["visibility"] == "shared" and c["doc_id"] == overlay.SHOWCASE_DOC_ID for c in chunks
    )
    assert all(decrypt_if_present(c["chunk_text"]) != c["chunk_text"] for c in chunks)
    assert {r["chunk_id"] for r in recorder.rows["course_chunk_contributors"]} == {
        c["id"] for c in chunks
    }
    (doc,) = recorder.rows["documents"]
    assert doc["shareability"] == "course_material" and doc["index_status"] == "indexed"
    assert doc["user_id"] == rich.USER_LOOP and doc["offering_id"] == rich.OFF_CS_S26
    items = recorder.rows["check_items"]
    assert len(items) == len(DRAFTS)
    cited = {cid for r in items for cid in r["source_chunk_ids"]}
    assert cited == {c["id"] for c in chunks}
    assert all(r["canonical_verified"] is True and r["lint_flags"] == [] for r in items)


def test_no_e2e_lane_runs_the_overlay():
    """The overlay is a person's opt-in for a real-model demo. The E2E lanes
    assert on the placeholder constants, so nothing they run may apply it."""
    lanes = [
        REPO / "Makefile",
        *(REPO / "scripts").rglob("*"),
        *(REPO / ".github").rglob("*"),
        *(REPO / "frontend" / "e2e").rglob("*"),
        *(REPO / "backend" / "e2e_oracles").rglob("*"),
    ]
    offenders = [
        str(p.relative_to(REPO))
        for p in lanes
        if p.is_file()
        and "node_modules" not in p.parts
        and "seed_showcase_loop" in p.read_text(errors="ignore")
    ]
    assert offenders == []
    assert (
        "db.seed_showcase_loop" not in (REPO / "backend" / "db" / "seed_local_rich.py").read_text()
    )
