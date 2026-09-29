"""PKG-07: the visibility-aware by-id chunk reader (A17/A18, invariant 29) and
the seen/revealed question-hash readers (A23). No DB: table()/page_all are faked."""

from __future__ import annotations

import inspect
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from learning.params import RUNG_NO_CREDIT_MIN


def _fake_table(rows_by_table: dict, calls: list):
    def factory(name):
        handle = MagicMock(name=name)

        def select(columns="*", filters=None, **kw):
            calls.append((name, dict(filters or {})))
            return [dict(r) for r in rows_by_table.get(name, [])]

        handle.select.side_effect = select
        return handle

    return factory


CHUNKS = [
    {
        "id": "c1",
        "course_id": "CS111",
        "chunk_text": "enc1",
        "visibility": "shared",
        "uploader_id": "u9",
    },
    {
        "id": "c2",
        "course_id": "CS111",
        "chunk_text": "enc2",
        "visibility": "private",
        "uploader_id": "u1",
    },
    {
        "id": "c3",
        "course_id": "CS111",
        "chunk_text": "enc3",
        "visibility": "private",
        "uploader_id": "u2",
    },
    {
        "id": "c4",
        "course_id": "CS111",
        "chunk_text": "enc4",
        "visibility": "private",
        "uploader_id": "u2",
    },
]


def test_chunks_for_ids_keeps_only_what_the_reader_may_see(monkeypatch):
    import services.rag_service as rag

    calls: list = []
    monkeypatch.setattr(
        rag,
        "table",
        _fake_table(
            {"course_chunks": CHUNKS, "course_chunk_contributors": [{"chunk_id": "c4"}]}, calls
        ),
    )
    monkeypatch.setattr(rag, "decrypt_if_present", lambda s: f"plain:{s}")
    got = rag.chunks_for_ids(["c4", "c3", "c2", "c1", "c1"], user_id="u1")
    assert [r["id"] for r in got] == ["c4", "c2", "c1"], (
        "contributed, own upload, shared — request order, deduped"
    )
    assert all(set(r) == {"id", "course_id", "chunk_text"} for r in got)
    assert got[-1]["chunk_text"] == "plain:enc1", "decrypted at this boundary"
    contributor_reads = [f for name, f in calls if name == "course_chunk_contributors"]
    assert contributor_reads and all("u1" in json.dumps(f) for f in contributor_reads)
    # the contributor read asks only about the rows the reader could not see otherwise
    assert '"c3"' in contributor_reads[0]["chunk_id"] and '"c4"' in contributor_reads[0]["chunk_id"]
    assert '"c1"' not in contributor_reads[0]["chunk_id"]


def test_chunks_for_ids_quotes_every_id(monkeypatch):
    """The chunk_visibility._in_list rule: an interpolated value is quoted, so an
    odd id can never reshape the in.(…) filter."""
    import services.rag_service as rag

    calls: list = []
    monkeypatch.setattr(rag, "table", _fake_table({}, calls))
    rag.chunks_for_ids(["a,b", 'c"d'], user_id="u1")
    assert calls == [("course_chunks", {"id": 'in.("a,b","c\\"d")'})]


def test_chunks_for_ids_skips_the_contributor_read_when_everything_is_visible(monkeypatch):
    import services.rag_service as rag

    calls: list = []
    monkeypatch.setattr(rag, "table", _fake_table({"course_chunks": CHUNKS[:2]}, calls))
    monkeypatch.setattr(rag, "decrypt_if_present", lambda s: s)
    assert [r["id"] for r in rag.chunks_for_ids(["c1", "c2"], user_id="u1")] == ["c1", "c2"]
    assert [name for name, _ in calls] == ["course_chunks"]


def test_chunks_for_ids_empty_input_reads_nothing(monkeypatch):
    import services.rag_service as rag

    calls: list = []
    monkeypatch.setattr(rag, "table", _fake_table({}, calls))
    assert rag.chunks_for_ids([], user_id="u1") == [] and calls == []
    assert rag.chunks_for_ids(["", None], user_id="u1") == [] and calls == []


def test_chunks_for_ids_requires_a_named_reader():
    from services.rag_service import chunks_for_ids

    param = inspect.signature(chunks_for_ids).parameters["user_id"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY and param.default is inspect.Parameter.empty


@pytest.fixture
def evidence_db(monkeypatch):
    import learning.loop_state_store as store

    rows = {
        "node_mastery_events": [
            {"question_hash": "qa", "correct": True, "max_rung": 0},
            {"question_hash": "qb", "correct": False, "max_rung": 0},
            {"question_hash": "qc", "correct": True, "max_rung": RUNG_NO_CREDIT_MIN},
            {"question_hash": "qe", "correct": True, "max_rung": None},
        ],
        "sessions": [  # the projected revealed list (m7: only reveal-bearing rows are read)
            {"revealed": ["qd"]},
            {"revealed": []},
        ],
    }
    seen_filters: list = []

    def page_all(handle, columns="*", *, filters=None, order, **kw):
        seen_filters.append((handle.name, dict(filters or {}), columns, order))
        return iter([dict(r) for r in rows.get(handle.name, [])])

    monkeypatch.setattr(store, "table", lambda name: SimpleNamespace(name=name))
    monkeypatch.setattr(store, "page_all", page_all)
    return seen_filters


def test_seen_hashes_are_every_evidence_hash(evidence_db):
    from learning.loop_state_store import seen_hashes

    assert seen_hashes("u1") == {"qa", "qb", "qc", "qe"}
    assert evidence_db and all("u1" in json.dumps(f) for _, f, _, _ in evidence_db), (
        "every read is scoped to the user"
    )
    ((name, filters, columns, order),) = evidence_db
    assert name == "node_mastery_events"
    assert filters["event_type"] == "eq.evidence" and "graph_nodes!inner(user_id)" in columns
    assert order == "id", "page_all needs a total order"


def test_revealed_hashes_are_wrong_or_no_credit_plus_shown_siblings(evidence_db):
    from learning.loop_state_store import revealed_hashes

    assert revealed_hashes("u1") == {"qb", "qc", "qd"}
    assert {name for name, _, _, _ in evidence_db} == {"node_mastery_events", "sessions"}
