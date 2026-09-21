"""scripts/backfill_document_chunks.py — the operator's re-drive (#482, #628).

It used to reimplement indexing: its own chunking, its own `_already_indexed`
(unreliable — on a shared row `doc_id` names only the last writer, #629), and
its own visibility call passing `confidence=1.0` whenever a shareability was
stored. That premise was false: `_persist_document` stores the classifier's
RAW label and the 0.6 confidence floor applies only at index time, so this
script would re-index as SHARED a document the live path had kept private.

It is now a thin caller of `services.document_indexing.index_document`, the
same entry point the uploads and the sweeper use, so it cannot drift again.
"""
import importlib
import sys

import pytest

from services.document_indexing import IndexOutcome


@pytest.fixture
def backfill(monkeypatch):
    # The script runs `load_dotenv(".env.staging")` at import. Neutralise it so
    # importing it here can never point this process at a live project.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    sys.modules.pop("scripts.backfill_document_chunks", None)
    module = importlib.import_module("scripts.backfill_document_chunks")
    monkeypatch.setattr(module.time, "sleep", lambda s: None)
    yield module
    sys.modules.pop("scripts.backfill_document_chunks", None)


class _Handle:
    def __init__(self, name):
        self.name = name


def _stub(backfill, monkeypatch, *, targets, unrecoverable=(), outcome):
    reads = []

    def fake_page_all(handle, columns="*", *, filters=None, order):
        reads.append(dict(filters or {}))
        if (filters or {}).get("extracted_text") == "is.null":
            return iter({"id": d} for d in unrecoverable)
        return iter({"id": d, "file_name": f"{d}.pdf"} for d in targets)

    driven = []

    def fake_index(doc_id, **kw):
        driven.append((doc_id, kw))
        return outcome(doc_id) if callable(outcome) else outcome

    monkeypatch.setattr(backfill, "page_all", fake_page_all)
    monkeypatch.setattr(backfill, "table", _Handle)
    monkeypatch.setattr(backfill, "index_document", fake_index)
    return reads, driven


def test_it_re_drives_through_the_shared_entry_point(backfill, monkeypatch, capsys):
    _, driven = _stub(backfill, monkeypatch, targets=["doc-1", "doc-2"],
                      outcome=IndexOutcome("indexed", 4))

    backfill.main([])

    # force: an operator's run resets the budget of a row the sweeper gave up on.
    assert driven == [("doc-1", {"force": True}), ("doc-2", {"force": True})]
    out = capsys.readouterr().out
    assert "4 chunks indexed" in out
    assert "2 ok" in out and "0 failed" in out


def test_zero_indexed_chunks_is_a_failure_not_an_ok(backfill, monkeypatch, capsys):
    """Counting a run that indexed NOTHING as `ok` made it end "Done: 5 ok,
    0 failed" — on the script whose whole job is recovery."""
    _stub(backfill, monkeypatch, targets=["doc-1"],
          outcome=IndexOutcome("failed", 0, "ClientError"))

    with pytest.raises(SystemExit) as exit_info:
        backfill.main([])

    out = capsys.readouterr().out
    assert exit_info.value.code == 1
    assert "FAIL" in out and "ClientError" in out
    assert "0 ok" in out and "1 failed" in out


def test_a_partial_index_is_a_failure(backfill, monkeypatch):
    _stub(backfill, monkeypatch, targets=["doc-1"],
          outcome=IndexOutcome("partial", 3, "ServerError"))

    with pytest.raises(SystemExit):
        backfill.main([])


def test_function_mode_leaking_in_is_a_failure_with_a_hint(backfill, monkeypatch,
                                                            capsys):
    """SAPLING_MODEL_MODE=function still exported from an E2E cycle disables
    embedding: every document comes back 'skipped' and nothing is indexed."""
    _stub(backfill, monkeypatch, targets=["doc-1"], outcome=IndexOutcome("skipped"))

    with pytest.raises(SystemExit) as exit_info:
        backfill.main([])

    assert exit_info.value.code == 1
    assert "SAPLING_MODEL_MODE" in capsys.readouterr().out


def test_a_live_lease_is_skipped_not_failed(backfill, monkeypatch, capsys):
    """The sweeper is indexing it right now; that is not this run's failure."""
    _stub(backfill, monkeypatch, targets=["doc-1"], outcome=IndexOutcome("indexing"))

    backfill.main([])

    out = capsys.readouterr().out
    assert "1 skipped" in out and "0 failed" in out


def test_dry_run_indexes_nothing(backfill, monkeypatch):
    _, driven = _stub(backfill, monkeypatch, targets=["doc-1"],
                      outcome=IndexOutcome("indexed", 4))

    backfill.main(["--dry-run"])

    assert driven == []


def test_unrecoverable_documents_are_reported_not_failed(backfill, monkeypatch,
                                                         capsys):
    """No extracted_text means no source to index from: the original file is
    discarded after upload. Prod has two. Counting them as failures would make
    every run in prod exit 1 forever, so they are reported, never driven."""
    reads, driven = _stub(backfill, monkeypatch, targets=["doc-1"],
                          unrecoverable=["n1", "n2"],
                          outcome=IndexOutcome("indexed", 4))

    backfill.main([])

    assert [d for d, _ in driven] == ["doc-1"]
    assert "2 unrecoverable" in capsys.readouterr().out
    target_filters = [f for f in reads if f.get("extracted_text") == "not.is.null"]
    assert target_filters, "targets must exclude documents with no text"


def test_default_targets_are_every_unfinished_live_document(backfill, monkeypatch):
    reads, _ = _stub(backfill, monkeypatch, targets=[],
                     outcome=IndexOutcome("indexed", 4))

    backfill.main([])

    (targets,) = [f for f in reads if f.get("extracted_text") == "not.is.null"]
    assert targets["index_status"] == "in.(pending,indexing,partial,failed)"
    assert targets["deleted_at"] == "is.null"


def test_one_document_by_id(backfill, monkeypatch):
    reads, driven = _stub(backfill, monkeypatch, targets=["doc-9"],
                          outcome=IndexOutcome("indexed", 2))

    backfill.main(["--doc", "doc-9"])

    (targets,) = [f for f in reads if f.get("extracted_text") == "not.is.null"]
    assert targets["id"] == "eq.doc-9"
    assert "index_status" not in targets   # an explicit id is re-driven whatever it is
    assert driven == [("doc-9", {"force": True})]


def test_the_script_makes_no_visibility_decision_of_its_own(backfill):
    """The confidence=1.0 bypass lived here. With the decision made only in
    index_document, from the stored confidence, it cannot come back quietly."""
    source = open(backfill.__file__).read()
    assert "decide_visibility" not in source
    assert "index_document_chunks" not in source
