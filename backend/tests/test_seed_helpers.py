from unittest.mock import MagicMock
import db.seed_helpers as h


def test_upsert_records_created_when_absent(monkeypatch):
    h.reset_counts()
    tbl = MagicMock()
    tbl.select.return_value = []          # not present → created
    monkeypatch.setattr(h, "table", lambda name: tbl)
    h.upsert("schools", {"id": "s1", "slug": "x"}, on_conflict="slug")
    tbl.upsert.assert_called_once()
    assert h.counts["schools"]["created"] == 1
    assert h.counts["schools"]["skipped"] == 0


def test_upsert_records_skipped_when_present(monkeypatch):
    h.reset_counts()
    tbl = MagicMock()
    tbl.select.return_value = [{"slug": "x"}]   # present → skipped
    monkeypatch.setattr(h, "table", lambda name: tbl)
    h.upsert("schools", {"id": "s1", "slug": "x"}, on_conflict="slug")
    assert h.counts["schools"]["skipped"] == 1


def test_insert_if_absent_skips_existing(monkeypatch):
    h.reset_counts()
    tbl = MagicMock()
    tbl.select.return_value = [{"id": "r1"}]
    monkeypatch.setattr(h, "table", lambda name: tbl)
    h.insert_if_absent("enrollments", "r1", {"user_id": "u"})
    tbl.insert.assert_not_called()
    assert h.counts["enrollments"]["skipped"] == 1
