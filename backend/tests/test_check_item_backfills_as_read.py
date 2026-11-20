"""PR #866 Z35: the key, lint and alignment backfills never overwrite a staff
decision recorded while they ran.

Each backfill reads every row up front, runs for minutes to hours (a blind
solve, an alignment check), then writes absolute `lint_flags` and, for keys,
`canonical_verified` by id. Staff working the audit and review queue at the
same time could see their decision lost: an item audited "wrong" after the
read lost `key_audit_wrong` (and, when the solve agreed, got
`canonical_verified` back) and was served again; an item approved after the
read was disputed and held again. Every such write now holds to the row as it
was read (`check_item_service.as_read_filters`): a row a decision changed is
left as staff left it, and counted for the next run."""

from __future__ import annotations

import importlib
import sys
from unittest.mock import patch

import pytest

from learning.checks import KEY_AUDIT_WRONG, KEY_DISPUTED, held_flags
from learning.item_keys import KeyCheck
from tests.test_learning_check_items import _ItemsTable, _item

AT = "2026-11-12T00:00:00+00:00"


class _Rows:
    """check_items as PostgREST answers a filtered read or update."""

    def __init__(self, rows):
        self.rows = {r["id"]: dict(r) for r in rows}
        self.writes: list[tuple[dict, dict]] = []

    def _hit(self, filters):
        out = []
        for row in self.rows.values():
            ok = True
            for key, value in (filters or {}).items():
                if key == "select":
                    continue
                if key == "id" and value.startswith("in.("):
                    ok &= row["id"] in [v.strip('"') for v in value[4:-1].split(",")]
                else:
                    ok &= _ItemsTable._matches(row.get(key), value)
            if ok:
                out.append(row)
        return out

    def select(self, columns, filters=None, **_kw):
        return [dict(r) for r in self._hit(filters)]

    def update(self, data, filters=None, prefer_return_minimal=False):
        hit = self._hit(filters)
        for row in hit:
            row.update(data)
            self.writes.append((dict(data), dict(filters or {})))
        return [] if prefer_return_minimal else [{"id": r["id"]} for r in hit]

    def upsert(self, rows, on_conflict=None, ignore_duplicates=False):
        for row in rows:
            if not (ignore_duplicates and row["id"] in self.rows):
                self.rows[row["id"]] = dict(row)
        return []

    def delete(self, filters=None):
        hit = self._hit(filters)
        for row in hit:
            self.rows.pop(row["id"])
        return [{"id": r["id"]} for r in hit]


def _read(**over):
    """The item as the backfill read it: linted clean, its key unconfirmed."""
    base = dict(id="i1", course_id="c1", concept_key="recursion", lint_flags=[], canonical_verified=False)
    return _item(**{**base, **over})


def _stored(item, **now) -> dict:
    """The row as it is NOW (after whatever staff did meanwhile)."""
    return {
        "id": item.id,
        "course_id": item.course_id,
        "concept_key": item.concept_key,
        "question_hash": item.question_hash,
        "lint_flags": list(item.lint_flags) if item.lint_flags is not None else None,
        "canonical_verified": item.canonical_verified,
        **now,
    }


# ── the key backfill (scripts/backfill_check_item_keys.py) ──────────────────


def test_an_audit_during_the_solve_is_never_overwritten_by_an_agreement():
    from services import check_item_service as svc

    item = _read()
    rows = _Rows([_stored(item, lint_flags=[KEY_AUDIT_WRONG], canonical_verified=False)])
    update = svc.key_check_update(item, KeyCheck(verified=True), at=AT)
    assert update["canonical_verified"] is True  # what the stale read would write

    with patch.object(svc, "table", return_value=rows):
        assert svc.apply_key_check(item, update) is False

    now = rows.rows["i1"]
    assert now["lint_flags"] == [KEY_AUDIT_WRONG] and now["canonical_verified"] is False
    assert held_flags(now["lint_flags"], now["canonical_verified"])  # never served again


def test_an_approval_during_the_solve_is_never_undone_by_a_dispute():
    from services import check_item_service as svc

    item = _read(lint_flags=[KEY_DISPUTED])
    rows = _Rows([_stored(item, canonical_verified=True)])  # approved meanwhile
    update = svc.key_check_update(item, KeyCheck(verified=False, flag=KEY_DISPUTED), at=AT)

    with patch.object(svc, "table", return_value=rows):
        assert svc.apply_key_check(item, update) is False

    assert rows.rows["i1"]["canonical_verified"] is True


def test_an_unchanged_row_is_written():
    from services import check_item_service as svc

    item = _read()
    rows = _Rows([_stored(item)])
    with patch.object(svc, "table", return_value=rows):
        assert svc.apply_key_check(item, svc.key_check_update(item, KeyCheck(verified=True), at=AT))
    assert rows.rows["i1"]["canonical_verified"] is True


@pytest.fixture
def keys_backfill(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    sys.modules.pop("scripts.backfill_check_item_keys", None)
    module = importlib.import_module("scripts.backfill_check_item_keys")
    monkeypatch.setattr(module, "_project_ref", lambda: "proj-a")
    monkeypatch.setattr(module, "model_mode", lambda: "real")
    yield module
    sys.modules.pop("scripts.backfill_check_item_keys", None)


def test_the_key_backfill_counts_a_changed_row_and_exits_1(keys_backfill, monkeypatch, capsys):
    item = _read()
    from collections import Counter

    planned = (1, [(item, KeyCheck(True), None)], Counter())
    monkeypatch.setattr(keys_backfill, "plan", lambda course, *, reverify: planned)
    monkeypatch.setattr(keys_backfill, "apply_key_check", lambda item, update: False)

    assert keys_backfill.main(["--apply", "--project", "proj-a"]) == 1
    out = capsys.readouterr().out
    assert "changed since read, not written: i1" in out and "1 changed since read" in out


# ── the lint backfill (scripts/backfill_check_item_lint.py) ─────────────────


@pytest.fixture
def lint_backfill(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    sys.modules.pop("scripts.backfill_check_item_lint", None)
    module = importlib.import_module("scripts.backfill_check_item_lint")
    monkeypatch.setattr(module, "_project_ref", lambda: "proj-a")
    yield module
    sys.modules.pop("scripts.backfill_check_item_lint", None)


def test_the_lint_backfill_never_drops_an_audit_code_written_meanwhile(lint_backfill, monkeypatch, capsys):
    """Read never linted (NULL); audited wrong before the write."""
    from services import check_item_service as svc

    item = _read(lint_flags=None, prompt="Which statement is false?")
    rows = _Rows([_stored(item, lint_flags=[KEY_AUDIT_WRONG], canonical_verified=False)])
    monkeypatch.setattr(lint_backfill, "items_to_lint", lambda course, *, relint: iter([item]))

    with patch.object(svc, "table", return_value=rows):
        assert lint_backfill.main(["--apply"]) == 1

    assert rows.rows["i1"]["lint_flags"] == [KEY_AUDIT_WRONG]  # still held
    assert "1 changed since read" in capsys.readouterr().out


def test_the_lint_backfill_writes_rows_that_did_not_change(lint_backfill, monkeypatch):
    from services import check_item_service as svc

    item = _read(lint_flags=None, prompt="Which statement is false?")
    rows = _Rows([_stored(item)])
    monkeypatch.setattr(lint_backfill, "items_to_lint", lambda course, *, relint: iter([item]))

    with patch.object(svc, "table", return_value=rows):
        assert lint_backfill.main(["--apply"]) == 0

    assert rows.rows["i1"]["lint_flags"] == ["negative_stem"]


# ── the alignment backfill (scripts/backfill_check_item_alignment.py) ───────


def test_an_alignment_rewrite_never_overwrites_an_audit_written_meanwhile():
    from learning.item_alignment import RUBRIC_UNASKED_DROPPED, Alignment
    from services import check_item_service as svc

    item = _read()
    rows = _Rows([_stored(item, lint_flags=[KEY_AUDIT_WRONG])])
    trim = Alignment((0,), "recursion", (RUBRIC_UNASKED_DROPPED,))

    with patch.object(svc, "table", return_value=rows):
        assert svc.apply_item_alignment(_stored(item), item, trim, at=AT) is None

    assert rows.rows["i1"]["lint_flags"] == [KEY_AUDIT_WRONG]


def test_an_alignment_rekey_moves_nothing_when_the_row_changed_meanwhile():
    from learning.item_alignment import CONCEPT_RETAGGED, Alignment
    from services import check_item_service as svc

    item = _read()
    rows = _Rows([_stored(item, lint_flags=[KEY_AUDIT_WRONG])])
    retag = Alignment((0,), "base case", (CONCEPT_RETAGGED,))

    with patch.object(svc, "table", return_value=rows):
        assert svc.apply_item_alignment(_stored(item), item, retag, at=AT) is None

    assert list(rows.rows) == ["i1"] and rows.rows["i1"]["lint_flags"] == [KEY_AUDIT_WRONG]
