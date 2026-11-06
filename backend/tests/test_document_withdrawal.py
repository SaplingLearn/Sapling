"""#758: deleting a document withdraws its contributions from course_chunks.

`DELETE /api/documents/doc/{id}` only stamped `deleted_at`, and
`match_course_chunks` never looked at `documents`, so a deleted upload —
private ones included — kept grounding the tutor. These drive
`withdraw_document_chunks` against an in-memory PostgREST that honours the
filters the module sends, so the joint-ownership rules are exercised rather
than mocked away. The retrieval-side half (the RPC refusing a chunk whose every
source is deleted) is SQL; its text is pinned at the bottom.
"""
import pathlib
import re

import pytest

from services import chunk_visibility as cv

MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"


def _unquote(v: str) -> str:
    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] == '"' else v


def _match(row, col, cond):
    op, _, val = cond.partition(".")
    cur = row.get(col)
    if op == "eq":
        return cur is not None and str(cur) == val
    if op == "neq":
        return str(cur) != val
    if op == "is":
        return cur is None if val == "null" else str(cur).lower() == val
    if op == "in":
        return str(cur) in {_unquote(v) for v in val.strip("()").split(",")}
    raise AssertionError(f"filter op {op!r} not modelled")


class FakeDB:
    KEYS = {
        "course_chunks": ("id",),
        "course_chunk_sources": ("chunk_id", "doc_id"),
        "course_chunk_contributors": ("chunk_id", "user_id"),
        "documents": ("id",),
        "user_settings": ("user_id",),
    }

    def __init__(self):
        self.rows = {name: [] for name in self.KEYS}

    def add(self, name, **row):
        self.rows[name].append(row)

    def ids(self, name, col="id"):
        return sorted(r[col] for r in self.rows[name])

    def table(self, name):
        db = self

        def hits(filters):
            return [r for r in db.rows[name]
                    if all(_match(r, k, v) for k, v in (filters or {}).items())]

        class _T:
            def select(self, columns="*", filters=None, limit=None, **_):
                return [dict(r) for r in hits(filters)][:limit] if limit else [
                    dict(r) for r in hits(filters)]

            def select_with_count(self, columns="*", filters=None, order=None,
                                  limit=None, offset=0, **_):
                rows = [dict(r) for r in hits(filters)]
                return rows[offset or 0:(offset or 0) + limit], len(rows)

            def update(self, data, filters, *, prefer_return_minimal=False):
                for r in hits(filters):
                    r.update(data)
                return []

            def upsert(self, data, on_conflict="id", **_):
                keys = on_conflict.split(",")
                for new in data if isinstance(data, list) else [data]:
                    old = [r for r in db.rows[name]
                           if all(r.get(k) == new.get(k) for k in keys)]
                    if old:
                        old[0].update(new)
                    else:
                        db.rows[name].append(dict(new))
                return []

            def delete(self, filters):
                gone = hits(filters)
                db.rows[name] = [r for r in db.rows[name] if r not in gone]
                if name == "course_chunks":
                    # The FKs from both ledgers cascade.
                    ids = {r["id"] for r in gone}
                    for ledger in ("course_chunk_sources", "course_chunk_contributors"):
                        db.rows[ledger] = [r for r in db.rows[ledger]
                                           if r["chunk_id"] not in ids]
                return []

        return _T()


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(cv, "table", fake.table)
    return fake


def _doc(db, doc_id, user, deleted=False):
    db.add("documents", id=doc_id, user_id=user,
           deleted_at="2026-11-06T00:00:00Z" if deleted else None)


def _chunk(db, cid, *, doc, uploader, visibility="shared", category="lecture_notes"):
    db.add("course_chunks", id=cid, doc_id=doc, uploader_id=uploader,
           visibility=visibility, category=category)


# ── the delete path ─────────────────────────────────────────────────────────


def test_a_private_documents_chunks_are_deleted(db):
    """The leak in its plainest form: an opted-out (or completed-work) upload
    lives in the private namespace, has no contributor rows, and nothing else
    holds it — so it goes, ledger and all."""
    _doc(db, "d1", "u1", deleted=True)
    for cid in ("p1", "p2"):
        _chunk(db, cid, doc="d1", uploader="u1", visibility="private")
        db.add("course_chunk_sources", chunk_id=cid, doc_id="d1")

    out = cv.withdraw_document_chunks("d1", "u1")

    assert db.rows["course_chunks"] == []
    assert db.rows["course_chunk_sources"] == []
    assert out["chunks_deleted"] == 2


def test_a_shared_chunk_nobody_else_holds_is_deleted(db):
    _doc(db, "d1", "u1", deleted=True)
    _chunk(db, "s1", doc="d1", uploader="u1")
    db.add("course_chunk_sources", chunk_id="s1", doc_id="d1")
    db.add("course_chunk_contributors", chunk_id="s1", user_id="u1")

    cv.withdraw_document_chunks("d1", "u1")

    assert db.rows["course_chunks"] == []
    assert db.rows["course_chunk_contributors"] == []


def test_a_shared_chunk_a_classmate_also_contributed_stays(db):
    """Jointly owned: the deleting student's contributor row goes, the
    classmate's — and the chunk — stay."""
    _doc(db, "d1", "u1", deleted=True)
    _doc(db, "d2", "u2")
    _chunk(db, "s1", doc="d1", uploader="u1")
    db.add("course_chunk_sources", chunk_id="s1", doc_id="d1")
    db.add("course_chunk_sources", chunk_id="s1", doc_id="d2")
    db.add("course_chunk_contributors", chunk_id="s1", user_id="u1")
    db.add("course_chunk_contributors", chunk_id="s1", user_id="u2")

    out = cv.withdraw_document_chunks("d1", "u1")

    assert db.ids("course_chunks") == ["s1"]
    assert db.ids("course_chunk_contributors", "user_id") == ["u2"]
    assert out == {"considered": 1, "chunks_deleted": 0,
                   "contributors_removed": 1, "to_private": 0}


def test_the_same_text_in_another_live_upload_of_mine_is_kept(db):
    """Two of my documents produce one private row (same text, same
    namespace). Deleting one must not take the other's content with it."""
    _doc(db, "d1", "u1", deleted=True)
    _doc(db, "d2", "u1")
    _chunk(db, "p1", doc="d2", uploader="u1", visibility="private")
    db.add("course_chunk_sources", chunk_id="p1", doc_id="d1")
    db.add("course_chunk_sources", chunk_id="p1", doc_id="d2")

    cv.withdraw_document_chunks("d1", "u1")

    assert db.ids("course_chunks") == ["p1"]


def test_my_contributor_row_stays_while_another_live_upload_of_mine_has_it(db):
    _doc(db, "d1", "u1", deleted=True)
    _doc(db, "d2", "u1")
    _chunk(db, "s1", doc="d1", uploader="u1")
    db.add("course_chunk_sources", chunk_id="s1", doc_id="d1")
    db.add("course_chunk_sources", chunk_id="s1", doc_id="d2")
    db.add("course_chunk_contributors", chunk_id="s1", user_id="u1")

    cv.withdraw_document_chunks("d1", "u1")

    assert db.ids("course_chunks") == ["s1"]
    assert db.ids("course_chunk_contributors", "user_id") == ["u1"]


def test_another_deleted_source_holds_nothing_up(db):
    _doc(db, "d1", "u1", deleted=True)
    _doc(db, "d0", "u1", deleted=True)
    _chunk(db, "p1", doc="d1", uploader="u1", visibility="private")
    db.add("course_chunk_sources", chunk_id="p1", doc_id="d0")
    db.add("course_chunk_sources", chunk_id="p1", doc_id="d1")

    cv.withdraw_document_chunks("d1", "u1")

    assert db.rows["course_chunks"] == []


def test_a_legacy_row_is_found_through_its_doc_id(db):
    """Rows written before the source ledger have only `doc_id` (their last
    writer) to go on."""
    _doc(db, "d1", "u1", deleted=True)
    _chunk(db, "p1", doc="d1", uploader="u1", visibility="private")

    cv.withdraw_document_chunks("d1", "u1")

    assert db.rows["course_chunks"] == []


def test_catalog_rows_are_never_touched(db):
    _doc(db, "d1", "u1", deleted=True)
    _chunk(db, "cat", doc="d1", uploader=None, category="catalog")
    db.add("course_chunk_sources", chunk_id="cat", doc_id="d1")

    cv.withdraw_document_chunks("d1", "u1")

    assert db.ids("course_chunks") == ["cat"]


def test_a_shared_row_left_with_only_opted_out_contributors_goes_private(db):
    """#629's rule after the departure: shared while ANY contributor is opted
    in. If the deleting student was that one, the row must stop being served
    to the class."""
    _doc(db, "d1", "u1", deleted=True)
    _chunk(db, "s1", doc="d1", uploader="u1")
    db.add("course_chunk_sources", chunk_id="s1", doc_id="d1")
    db.add("course_chunk_contributors", chunk_id="s1", user_id="u1")
    db.add("course_chunk_contributors", chunk_id="s1", user_id="u2")
    db.add("user_settings", user_id="u2", share_class_context=False)

    out = cv.withdraw_document_chunks("d1", "u1")

    assert db.rows["course_chunks"][0]["visibility"] == "private"
    assert out["to_private"] == 1


def test_it_is_idempotent(db):
    _doc(db, "d1", "u1", deleted=True)
    _chunk(db, "p1", doc="d1", uploader="u1", visibility="private")
    db.add("course_chunk_sources", chunk_id="p1", doc_id="d1")

    cv.withdraw_document_chunks("d1", "u1")
    again = cv.withdraw_document_chunks("d1", "u1")

    assert again["considered"] == 0


def test_a_failure_is_logged_never_raised(monkeypatch, caplog):
    """It runs after the delete is recorded; raising would 500 a request whose
    effect already happened."""
    def broken(name):
        raise RuntimeError("PostgREST down")

    monkeypatch.setattr(cv, "table", broken)
    with caplog.at_level("ERROR", logger="services.chunk_visibility"):
        out = cv.withdraw_document_chunks("d1", "u1")

    assert out["failed"] is True
    assert any(r.levelname == "ERROR" for r in caplog.records)


# ── the source ledger ───────────────────────────────────────────────────────


def test_record_sources_upserts_on_the_composite_key(db):
    cv.record_sources(["c1", "c2", "c1"], "d1")
    cv.record_sources(["c1"], "d1")

    assert sorted((r["chunk_id"], r["doc_id"])
                  for r in db.rows["course_chunk_sources"]) == [("c1", "d1"), ("c2", "d1")]


def test_record_sources_is_best_effort(monkeypatch, caplog):
    def broken(name):
        raise RuntimeError("404: relation does not exist")

    monkeypatch.setattr(cv, "table", broken)
    with caplog.at_level("WARNING", logger="services.chunk_visibility"):
        cv.record_sources(["c1"], "d1")

    assert any(r.levelname == "WARNING" for r in caplog.records)


# ── the migration ───────────────────────────────────────────────────────────


def _migration() -> str:
    hits = sorted(MIG_DIR.glob("*_course_chunk_sources.sql"))
    assert len(hits) == 1, hits
    return hits[0].read_text()


def _latest_match_course_chunks() -> str:
    """The body of the LAST migration that defines match_course_chunks."""
    for path in sorted(MIG_DIR.glob("*.sql"), reverse=True):
        sql = path.read_text()
        if "FUNCTION match_course_chunks(" in sql:
            return sql
    raise AssertionError("no match_course_chunks definition")


def test_retrieval_refuses_a_chunk_whose_every_source_is_deleted():
    sql = _latest_match_course_chunks()
    assert "course_chunk_sources" in sql
    assert re.search(r"JOIN documents d ON d\.id = s\.doc_id", sql)
    assert "d.deleted_at IS NULL" in sql
    # …and keeps the #629 reader filter it replaced.
    assert "c.visibility = 'shared'" in sql
    assert "course_chunk_contributors k" in sql


def test_retrieval_keeps_its_signature_so_no_overload_appears():
    sql = _migration()
    assert "CREATE OR REPLACE FUNCTION match_course_chunks(" in sql
    assert re.search(
        r"query_embedding\s+VECTOR\(768\),\s*match_count\s+INTEGER DEFAULT 5,\s*"
        r"filter_course_id\s+TEXT DEFAULT NULL,\s*filter_user_id\s+TEXT DEFAULT NULL",
        sql,
    )
    assert "DROP FUNCTION" not in sql


def test_sources_cascade_with_the_chunk_but_survive_the_document():
    sql = _migration()
    assert re.search(r"chunk_id\s+TEXT NOT NULL REFERENCES course_chunks\(id\) ON DELETE CASCADE", sql)
    assert not re.search(r"doc_id[^\n]*REFERENCES documents", sql)


def test_the_seed_covers_existing_rows_but_never_catalog():
    sql = _migration()
    assert "INSERT INTO course_chunk_sources" in sql
    assert "IS DISTINCT FROM 'catalog'" in sql


# ── rag_service hands the ids back ──────────────────────────────────────────


def test_indexing_reports_the_ids_it_upserted_private_ones_included():
    """document_indexing records sources from these, so a PRIVATE row (no
    contributor ledger entry) is findable when its document is deleted."""
    from unittest.mock import patch

    from services.rag_service import chunk_id, index_document_chunks_detailed

    with patch("services.rag_service._embed_documents_batch",
               return_value=[[0.1] * 768, [0.2] * 768]), \
         patch("services.rag_service.table") as t:
        t.return_value.upsert.return_value = []
        out = index_document_chunks_detailed(
            "CAS CS 330", "doc-1", "u1", ["alpha", "beta"],
            visibility="private", category="lecture_notes",
        )

    assert out.chunk_ids == tuple(
        chunk_id("CAS CS 330", c, visibility="private", uploader_id="u1")
        for c in ("alpha", "beta")
    )
