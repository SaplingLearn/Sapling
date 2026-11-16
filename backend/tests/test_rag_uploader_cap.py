"""M6(c): one student cannot own a classmate's whole retrieval.

Enrollment is self-service, so a student can join a course and upload a stack
of near-identical documents. `match_course_chunks` ranks purely on similarity,
so without a cap those rows could fill every slot of every classmate's tutor
context. `rag_service.cap_per_uploader` keeps at most
MAX_CHUNKS_PER_UPLOADER rows per OTHER uploader per query.
"""

from __future__ import annotations

from unittest.mock import patch

from services import rag_service
from services.rag_service import MAX_CHUNKS_PER_UPLOADER, cap_per_uploader


def _rows(*ids: str) -> list[dict]:
    return [{"id": i, "chunk_text": f"text {i}", "similarity": 0.9} for i in ids]


def _owners(mapping: dict[str, str | None]):
    return patch.object(rag_service, "_uploaders_of", return_value=mapping)


def test_one_uploader_is_capped_and_others_fill_the_slots():
    rows = _rows("a1", "a2", "a3", "a4", "b1", "c1", "a5")
    owners = {"a1": "mallory", "a2": "mallory", "a3": "mallory", "a4": "mallory",
              "b1": "bob", "c1": "carol", "a5": "mallory"}
    with _owners(owners):
        out = cap_per_uploader(rows, reader_id="alice", k=5)
    assert [r["id"] for r in out] == ["a1", "a2", "b1", "c1"]
    assert sum(1 for r in out if owners[r["id"]] == "mallory") == MAX_CHUNKS_PER_UPLOADER


def test_the_readers_own_uploads_and_catalog_rows_are_not_capped():
    rows = _rows("m1", "m2", "m3", "cat1", "cat2", "cat3")
    owners = {"m1": "alice", "m2": "alice", "m3": "alice",
              "cat1": None, "cat2": None, "cat3": None}
    with _owners(owners):
        out = cap_per_uploader(rows, reader_id="alice", k=6)
    assert len(out) == 6


def test_rank_order_is_kept_and_k_is_respected():
    rows = _rows("b1", "c1", "d1", "e1", "f1", "g1")
    owners = {i: i[0] for i in ("b1", "c1", "d1", "e1", "f1", "g1")}
    with _owners(owners):
        out = cap_per_uploader(rows, reader_id="alice", k=5)
    assert [r["id"] for r in out] == ["b1", "c1", "d1", "e1", "f1"]


def test_an_unattributable_retrieval_fails_closed_to_the_cap():
    rows = _rows("a1", "a2", "a3", "a4")
    with patch.object(rag_service, "_uploaders_of", side_effect=RuntimeError("down")):
        out = cap_per_uploader(rows, reader_id="alice", k=5)
    assert len(out) == MAX_CHUNKS_PER_UPLOADER


def test_retrieval_overfetches_then_caps(monkeypatch):
    """The RPC is asked for more than k so the cap can still fill k."""
    monkeypatch.setattr(rag_service, "_embed_query", lambda q: [0.1] * 768)
    ranked = _rows(*(f"a{i}" for i in range(6)), "b1", "c1", "d1")
    owners = {r["id"]: ("mallory" if r["id"].startswith("a") else r["id"]) for r in ranked}
    with patch.object(rag_service, "rpc", return_value=ranked) as rpc, _owners(owners), \
            patch.object(rag_service, "decrypt_if_present", side_effect=lambda v: v):
        got = rag_service.retrieve_chunks("q", course_id="CAS CS 330", k=5, user_id="alice")
    assert rpc.call_args[0][1]["match_count"] == 15
    assert [r["id"] for r in got] == ["a0", "a1", "b1", "c1", "d1"]
