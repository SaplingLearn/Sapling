"""PR #866 Z09: a drafting write never rewrites a stored item, and a new row of
a question staff audited wrong or ambiguous is stored held.

A draft whose normalized stem matches a stored row of its concept has that
row's id (course, concept, question_hash). The main pass upserted it ON
CONFLICT DO UPDATE, rewriting the key, `lint_flags` and `canonical_verified`
from the new model checks: a human audit's `key_audit_wrong` was dropped (the
item was served again with the key staff found wrong), an admin's approval
was undone by a fresh dispute, and the overwrite counted as "stored" for the
A41 redraft ledger, so a concept whose drafter keeps repeating its stems was
redrafted at full cost on every upload and backfill. The alignment backfill's
re-key upsert landed on an existing target row the same way.

Hermetic: generate_for_concepts over a stateful check_items table; the A119
alignment check passes every draft as drafted (tests/alignment_fakes.py) and
the A124 key check agrees or disputes as each test says."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from learning.checks import (
    KEY_AUDIT_WRONG,
    KEY_DISPUTED,
    held_flags,
    item_id,
    question_hash,
)
from tests.test_learning_check_items import _CHUNK, _ItemsTable, _cached_tables, _draft, _item

COURSE = "course-1"
KEY = "learning rate"
AUDITED_AT = "2026-11-10T12:00:00+00:00"


@pytest.fixture(autouse=True)
def _checks_pass(monkeypatch):
    """The A119 alignment check and the A124 key check agree with every draft."""
    from tests.alignment_fakes import install_passthrough

    install_passthrough(monkeypatch)


def _keys_disputed(monkeypatch):
    """The A124 blind solve disputes every draft's key (stored held)."""
    from services import check_item_service as svc

    def disputed(screened, passages, *, deps, flex, course_id):
        return {
            key: [
                e._replace(
                    key_checked=True,
                    verified=False,
                    flags=(*e.flags, KEY_DISPUTED),
                    reasons="key: an independent solve gave a different answer",
                )
                if e.draft is not None
                else e
                for e in rows
            ]
            for key, rows in screened.items()
        }

    monkeypatch.setattr(svc, "_solve_screened", disputed)


def _row(draft, concept_key: str = KEY, **over) -> dict:
    """The stored row of `draft`'s question under `concept_key`."""
    qh = question_hash(draft.prompt)
    return {
        "id": item_id(COURSE, concept_key, qh),
        "course_id": COURSE,
        "concept_key": concept_key,
        "format": draft.format,
        "difficulty": draft.difficulty,
        "question_hash": qh,
        **over,
    }


def _audit(draft, verdict: str = "wrong", **over) -> dict:
    return {
        "course_id": COURSE,
        "question_hash": question_hash(draft.prompt),
        "verdict": verdict,
        "audited_at": AUDITED_AT,
        **over,
    }


def _run(monkeypatch, drafts, *, items: _ItemsTable, decisions: dict | None = None):
    """One pass for "Learning Rate" whose drafting call answers `drafts`;
    `decisions` are the staff tables' rows (check_item_audits,
    check_item_reviews). Returns (outcome, ledger calls)."""
    import config
    from agents.check_items import CheckItemsOutput
    from services import check_item_service as svc

    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
    monkeypatch.setattr(svc, "CHECK_ITEM_MC_MIN_PER_CONCEPT", 0)  # no A37 top-up here
    factory, _ = _cached_tables(decisions or {})
    ledger: list[tuple[str, str]] = []
    monkeypatch.setattr(svc._DraftFailures, "failed", lambda self, k, fp: ledger.append(("failed", k)))
    monkeypatch.setattr(svc._DraftFailures, "succeeded", lambda self, k, fp: ledger.append(("ok", k)))

    async def fake_draft(concepts, passages, *, deps, flex):
        return CheckItemsOutput(items=list(drafts))

    with (
        patch.object(svc, "table", side_effect=lambda n: items if n == "check_items" else factory(n)),
        patch("learning.item_reports.table", side_effect=factory),
        patch.object(svc, "draft_items", side_effect=fake_draft),
        patch.object(svc, "_withdrawn_sources", return_value=[]),
        patch.object(svc, "log_event"),
    ):
        out = svc.generate_for_concepts(
            user_id="u1",
            course_id=COURSE,
            concept_names=["Learning Rate"],
            chunks=[_CHUNK],
            document_id="doc-1",
            flex=True,
        )
    return out, ledger


def _written_ids(items: _ItemsTable) -> list[str]:
    return [row["id"] for batch in items.upserts for row in batch]


def test_a_redraft_never_rewrites_an_item_staff_audited_wrong(monkeypatch):
    draft = _draft()
    audited = _row(draft, lint_flags=[KEY_AUDIT_WRONG], canonical_verified=False)
    items = _ItemsTable([audited])

    out, ledger = _run(monkeypatch, [draft], items=items, decisions={"check_item_audits": [_audit(draft)]})

    stored = items.rows[audited["id"]]
    assert stored["lint_flags"] == [KEY_AUDIT_WRONG] and stored["canonical_verified"] is False
    assert held_flags(stored["lint_flags"], stored["canonical_verified"])  # still served to no one
    assert audited["id"] not in _written_ids(items)
    assert out.items_created == 0


def test_a_redraft_never_undoes_an_approval(monkeypatch):
    """An admin approved a key-disputed item; the same solver disputes the
    same stem again on a redraft."""
    _keys_disputed(monkeypatch)
    draft = _draft()
    approved = _row(draft, lint_flags=[KEY_DISPUTED], canonical_verified=True)
    items = _ItemsTable([approved])

    _run(monkeypatch, [draft], items=items)

    stored = items.rows[approved["id"]]
    assert stored["canonical_verified"] is True  # the approval stands: served
    assert not held_flags(stored["lint_flags"], stored["canonical_verified"])
    assert approved["id"] not in _written_ids(items)


def test_a_pass_that_only_repeats_stored_stems_fails_for_the_ledger(monkeypatch):
    """A41: only NEW rows are a pass's success, so a concept whose drafter
    keeps repeating its stored stems stalls instead of being redrafted at full
    cost on every upload and backfill."""
    draft = _draft()
    items = _ItemsTable([_row(draft, lint_flags=[], canonical_verified=True)])

    out, ledger = _run(monkeypatch, [draft], items=items)

    assert ledger == [("failed", KEY)] and out.items_created == 0


def test_a_new_draft_beside_a_repeat_is_stored_and_counts(monkeypatch):
    repeat = _draft()
    fresh = _draft(prompt="In one sentence, what happens when the learning rate is too large?")
    items = _ItemsTable([_row(repeat, lint_flags=[], canonical_verified=True)])

    out, ledger = _run(monkeypatch, [repeat, fresh], items=items)

    assert _written_ids(items) == [_row(fresh)["id"]]
    assert out.items_created == 1 and ledger == [("ok", KEY)]


def test_a_new_row_of_an_audited_question_is_stored_held(monkeypatch):
    """The question is stored under another concept and audited wrong; the
    same stem drafted for this concept is a new row of that course item, and
    carries the audit's hold whatever the solve said."""
    draft = _draft()
    items = _ItemsTable([_row(draft, "momentum", lint_flags=[KEY_AUDIT_WRONG], canonical_verified=False)])

    out, _ = _run(monkeypatch, [draft], items=items, decisions={"check_item_audits": [_audit(draft)]})

    new = items.rows[_row(draft)["id"]]
    assert KEY_AUDIT_WRONG in new["lint_flags"] and new["canonical_verified"] is False
    assert held_flags(new["lint_flags"], new["canonical_verified"])


def test_an_approval_after_the_audit_lifts_its_hold_from_a_new_row(monkeypatch):
    draft = _draft()
    items = _ItemsTable()
    decisions = {
        "check_item_audits": [_audit(draft)],
        "check_item_reviews": [
            {"question_hash": question_hash(draft.prompt), "status": "approved",
             "approved_at": "2026-11-11T09:00:00+00:00"},
        ],
    }

    _run(monkeypatch, [draft], items=items, decisions=decisions)

    new = items.rows[_row(draft)["id"]]
    assert KEY_AUDIT_WRONG not in (new["lint_flags"] or [])
    assert new["canonical_verified"] is True  # its own solve agreed


def test_the_insert_never_rewrites_a_row_stored_after_the_read(monkeypatch):
    """The stored-id read and the insert are two calls: the insert is ON
    CONFLICT DO NOTHING, so a row another run stored in between is kept."""
    from services import check_item_service as svc

    draft = _draft()
    items = _ItemsTable()
    real = svc._stored_ids
    monkeypatch.setattr(svc, "_stored_ids", lambda ids: set())  # the read saw nothing yet
    _run(monkeypatch, [draft], items=items)
    monkeypatch.setattr(svc, "_stored_ids", real)
    assert items.rows[_row(draft)["id"]]["canonical_verified"] is True
    items.rows[_row(draft)["id"]].update(lint_flags=[KEY_AUDIT_WRONG], canonical_verified=False)
    monkeypatch.setattr(svc, "_stored_ids", lambda ids: set())

    _run(monkeypatch, [draft], items=items)

    stored = items.rows[_row(draft)["id"]]
    assert stored["lint_flags"] == [KEY_AUDIT_WRONG] and stored["canonical_verified"] is False


def test_an_alignment_rekey_onto_a_stored_row_keeps_that_row(monkeypatch):
    """scripts/backfill_check_item_alignment.py: an item misfiled under
    "momentum" tests "learning rate", where the question is already stored
    and audited wrong. The stored row is kept; the misfiled copy goes."""
    from learning.item_alignment import CONCEPT_RETAGGED, Alignment
    from services import check_item_service as svc
    from services.encryption import bind, encrypt_if_present

    draft = _draft()
    misfiled_id = item_id(COURSE, "momentum", question_hash(draft.prompt))
    misfiled = _row(draft, "momentum", lint_flags=[], canonical_verified=True)
    misfiled["prompt"] = encrypt_if_present(draft.prompt, bind=bind("check_items", "prompt", misfiled_id))
    target = _row(draft, lint_flags=[KEY_AUDIT_WRONG], canonical_verified=False)
    items = _ItemsTable([misfiled, target])
    deleted: list = []
    items.delete = lambda filters=None: deleted.append(filters) or [{"id": misfiled_id}]
    stored_item = _item(
        id=misfiled_id, course_id=COURSE, concept_key="momentum", prompt=draft.prompt,
        lint_flags=[], canonical_verified=True,  # as the backfill read the row
    )
    with patch.object(svc, "table", side_effect=lambda n: items):
        new_id = svc.apply_item_alignment(
            dict(misfiled), stored_item, Alignment((0, 1), KEY, (CONCEPT_RETAGGED,)), at="2026-11-12T00:00:00Z"
        )

    assert new_id == target["id"]
    kept = items.rows[target["id"]]
    assert kept["lint_flags"] == [KEY_AUDIT_WRONG] and kept["canonical_verified"] is False
    assert deleted and misfiled_id in deleted[0]["id"]
