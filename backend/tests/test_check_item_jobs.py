"""Upload-time check-item drafting on the job queue (#116 x learning-loop PKG-04).

services/check_item_jobs.py moves the loop's ordered index-then-draft chain
(services/documents/post_roll.py::_index_then_check_items) to the worker when the
`jobs_queue` flag is on for the uploader, exactly as main's
`schedule_document_index` moves the plain first index attempt. Pinned here:
flag off runs the chain in-process unchanged, flag on enqueues one job and
runs nothing in the request, a failed enqueue falls back in-process, and the
job's handler runs the same chain (indexing, then drafting on its own thread)
for the uploader, never refused by the per-user LLM budget.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services import check_item_jobs as cij
from services import jobs
from services.encryption import encrypt_json


# ── enqueue_for_document ────────────────────────────────────────────────────


def test_flag_off_enqueues_nothing():
    with patch.object(cij, "flag_on", return_value=False) as flag, \
         patch.object(jobs, "enqueue") as enqueue:
        assert cij.enqueue_for_document("doc-1", user_id="u1", course_id="c-1") is False
    flag.assert_called_once_with("jobs_queue", "u1")
    enqueue.assert_not_called()


def test_flag_on_enqueues_one_job_with_ids_only_and_a_per_document_dedupe_key():
    with patch.object(cij, "flag_on", return_value=True), \
         patch.object(jobs, "enqueue", return_value={"id": "j-1", "inserted": True}) as enqueue:
        assert cij.enqueue_for_document("doc-1", user_id="u1", course_id="c-1") is True
    enqueue.assert_called_once_with(
        "check_items.document",
        {"doc_id": "doc-1", "user_id": "u1", "course_id": "c-1"},
        dedupe_key="check_items.document:doc-1",
    )


def test_a_failed_enqueue_falls_back_to_the_request(caplog):
    with patch.object(cij, "flag_on", return_value=True), \
         patch.object(jobs, "enqueue", side_effect=RuntimeError("jobs migration missing")), \
         caplog.at_level("WARNING"):
        assert cij.enqueue_for_document("doc-1", user_id="u1", course_id="c-1") is False
    assert any("in-process" in r.getMessage() for r in caplog.records)


# ── the route's chain ───────────────────────────────────────────────────────


def test_the_chain_moves_to_the_worker_when_the_queue_takes_it():
    from services.documents import post_roll as rd  # spec §13 A149: the chain's home

    with patch.object(rd, "mark_drafting") as mark, \
         patch.object(rd.check_item_jobs, "enqueue_for_document", return_value=True) as enq, \
         patch.object(rd, "index_document") as idx, \
         patch.object(rd, "generate_for_document") as gen, \
         patch.object(rd, "queue_generation_for_document") as queue:
        rd._index_then_check_items("doc-1", "u1", "c-1", ["A"])
    # pending from the upload (A128), then nothing runs in the request
    mark.assert_called_once_with("doc-1", rd.DRAFTING_PENDING)
    enq.assert_called_once_with("doc-1", user_id="u1", course_id="c-1")
    idx.assert_not_called()
    gen.assert_not_called()
    queue.assert_not_called()


def test_the_chain_runs_in_process_when_the_queue_does_not_take_it():
    from services.documents import post_roll as rd  # spec §13 A149: the chain's home

    calls = []
    with patch.object(rd, "mark_drafting"), \
         patch.object(rd.check_item_jobs, "enqueue_for_document", return_value=False), \
         patch.object(rd, "model_mode", return_value="real"), \
         patch.object(rd, "index_document", side_effect=lambda d: calls.append(("index", d))), \
         patch.object(rd, "generate_for_document") as gen, \
         patch.object(rd, "queue_generation_for_document",
                      side_effect=lambda d, **k: calls.append(("queue", d))):
        rd._index_then_check_items("doc-1", "u1", "c-1", ["A"])
    assert calls == [("index", "doc-1"), ("queue", "doc-1")]  # the pre-#116 order
    gen.assert_not_called()


def test_inside_a_job_the_drafting_runs_on_the_jobs_own_thread():
    """The worker has no lifespan to drop a pool's queue at shutdown, and the
    job's lease and heartbeat cover the run: never queued on the pool there."""
    from services.documents import post_roll as rd  # spec §13 A149: the chain's home

    job = jobs.Job(id="j-1", type="check_items.document", payload={}, attempt=1,
                   max_attempts=5, locked_by="w")
    calls = []
    token = jobs._CURRENT_JOB.set(job)
    try:
        with patch.object(rd, "model_mode", return_value="real"), \
             patch.object(rd, "index_document", side_effect=lambda d: calls.append(("index", d))), \
             patch.object(rd, "generate_for_document",
                          side_effect=lambda d, **k: calls.append(("gen", d, k["flex"]))), \
             patch.object(rd, "queue_generation_for_document") as queue, \
             patch.object(rd, "mark_drafting") as mark:
            rd._index_then_draft("doc-1", "u1", "c-1", ["A"])
    finally:
        jobs._CURRENT_JOB.reset(token)
    assert calls == [("index", "doc-1"), ("gen", "doc-1", True)]
    queue.assert_not_called()
    mark.assert_not_called()  # generate_for_document records its own end


def test_a_drafting_failure_inside_a_job_is_logged_never_raised(caplog):
    from services.documents import post_roll as rd  # spec §13 A149: the chain's home

    job = jobs.Job(id="j-1", type="check_items.document", payload={}, attempt=1,
                   max_attempts=5, locked_by="w")
    token = jobs._CURRENT_JOB.set(job)
    try:
        with patch.object(rd, "model_mode", return_value="real"), \
             patch.object(rd, "index_document"), \
             patch.object(rd, "generate_for_document", side_effect=RuntimeError("boom")), \
             patch.object(rd, "mark_drafting") as mark, \
             caplog.at_level("ERROR"):
            rd._index_then_draft("doc-1", "u1", "c-1", ["A"])
    finally:
        jobs._CURRENT_JOB.reset(token)
    mark.assert_not_called()  # generate_for_document marked `failed` itself
    assert any("Check items for doc doc-1 failed" in r.getMessage() for r in caplog.records)


# ── the worker's handler ────────────────────────────────────────────────────


@pytest.mark.parametrize("payload", [
    None, {}, {"doc_id": "doc-1"}, {"doc_id": "doc-1", "user_id": "u1"},
    {"doc_id": "", "user_id": "u1", "course_id": "c-1"},
    {"doc_id": "doc-1", "user_id": 3, "course_id": "c-1"},
])
def test_the_handler_refuses_a_payload_without_its_three_ids(payload):
    with pytest.raises(jobs.PermanentJobError):
        cij._run_check_items_document_job(payload)


def _documents_table(rows):
    fake = MagicMock()
    fake.return_value.select.return_value = rows
    return fake


def test_the_handler_runs_the_chain_for_the_uploader_with_the_stored_concepts():
    from services import documents as rd  # the job handler's lookup (spec §13 A149)
    from services import llm_budget
    from services.request_context import current_acting_user

    notes = encrypt_json([{"name": "Backprop", "description": "d"},
                          {"name": "Gradient Descent", "description": "d"}])
    seen = {}

    def chain(doc_id, user_id, course_id, names):
        seen.update(args=(doc_id, user_id, course_id, names), actor=current_acting_user(),
                    background=llm_budget._BACKGROUND.get())

    table = _documents_table([{"id": "doc-1", "concept_notes": notes}])
    with patch.object(cij, "table", table), patch.object(rd, "_index_then_draft", chain):
        cij._run_check_items_document_job({"doc_id": "doc-1", "user_id": "u1", "course_id": "c-1"})
    assert seen["args"] == ("doc-1", "u1", "c-1", ["Backprop", "Gradient Descent"])
    # the uploader's work (usage attribution), never refused by the LLM budget
    assert seen["actor"] == "u1" and seen["background"] is True
    filters = table.return_value.select.call_args.kwargs["filters"]
    assert filters == {"id": "eq.doc-1", "deleted_at": "is.null"}
    assert current_acting_user() is None  # nothing leaks to the worker's next job


def test_the_handler_does_nothing_for_a_document_that_is_gone():
    from services import documents as rd  # the job handler's lookup (spec §13 A149)

    with patch.object(cij, "table", _documents_table([])), \
         patch.object(rd, "_index_then_draft") as chain:
        cij._run_check_items_document_job({"doc_id": "doc-1", "user_id": "u1", "course_id": "c-1"})
    chain.assert_not_called()


def test_unreadable_concept_notes_still_index_and_draft_nothing():
    from services import documents as rd  # the job handler's lookup (spec §13 A149)

    with patch.object(cij, "table", _documents_table([{"id": "doc-1", "concept_notes": "junk"}])), \
         patch.object(rd, "_index_then_draft") as chain:
        cij._run_check_items_document_job({"doc_id": "doc-1", "user_id": "u1", "course_id": "c-1"})
    chain.assert_called_once_with("doc-1", "u1", "c-1", [])


def test_the_worker_loads_the_check_items_job():
    from worker.__main__ import HANDLER_MODULES, load_handlers

    assert "services.check_item_jobs" in HANDLER_MODULES
    assert "check_items.document" in load_handlers()
    assert jobs.get_handler("check_items.document") is cij._run_check_items_document_job
