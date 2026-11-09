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


def _http_error(status: int, code: str):
    import httpx

    request = httpx.Request("POST", "http://127.0.0.1:54321/rest/v1/offering_concept_stats")
    response = httpx.Response(status, json={"code": code, "message": "x"}, request=request)
    return httpx.HTTPStatusError(f"{status}", request=request, response=response)


def test_insert_if_absent_treats_a_concurrent_duplicate_as_present(monkeypatch):
    # The exists-check misses, then a live worker's course_context.refresh
    # upserts the same row before our INSERT lands: PostgREST answers 409/23505.
    h.reset_counts()
    tbl = MagicMock()
    tbl.select.return_value = []
    tbl.insert.side_effect = _http_error(409, "23505")
    monkeypatch.setattr(h, "table", lambda name: tbl)
    h.insert_if_absent("offering_concept_stats", "ocs1", {"offering_id": "o"})
    tbl.insert.assert_called_once()
    assert h.counts["offering_concept_stats"] == {"created": 0, "skipped": 1}


def test_insert_by_keys_treats_a_concurrent_duplicate_as_present(monkeypatch):
    h.reset_counts()
    tbl = MagicMock()
    tbl.select.return_value = []
    tbl.insert.side_effect = _http_error(409, "23505")
    monkeypatch.setattr(h, "table", lambda name: tbl)
    h.insert_by_keys("room_members", {"room_id": "r", "user_id": "u"}, "room_id,user_id")
    assert h.counts["room_members"] == {"created": 0, "skipped": 1}


def test_insert_if_absent_still_raises_a_foreign_key_409(monkeypatch):
    # PostgREST also answers 409 for a foreign-key violation (23503): a real
    # seed bug, never swallowed.
    import httpx
    import pytest

    h.reset_counts()
    tbl = MagicMock()
    tbl.select.return_value = []
    tbl.insert.side_effect = _http_error(409, "23503")
    monkeypatch.setattr(h, "table", lambda name: tbl)
    with pytest.raises(httpx.HTTPStatusError):
        h.insert_if_absent("offering_concept_stats", "ocs1", {"offering_id": "missing"})
    assert h.counts["offering_concept_stats"] == {"created": 0, "skipped": 0}


def test_insert_if_absent_still_raises_other_errors(monkeypatch):
    import httpx
    import pytest

    h.reset_counts()
    tbl = MagicMock()
    tbl.select.return_value = []
    tbl.insert.side_effect = _http_error(400, "22P02")
    monkeypatch.setattr(h, "table", lambda name: tbl)
    with pytest.raises(httpx.HTTPStatusError):
        h.insert_if_absent("offering_concept_stats", "ocs1", {"offering_id": "o"})
