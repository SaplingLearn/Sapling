"""#116 (plan phase 2): uploads and indexing on the Postgres job queue.

Hermetic. Pins:
  * flag OFF: both upload routes and the indexing call sites behave exactly as
    before (nothing staged, nothing enqueued, index_document(doc_id) inline);
  * flag ON: `document.index` / `document.process` are enqueued with the right
    payload and dedupe key, and the routes relay the worker's progress as the
    same SSE events / sync JSON;
  * an enqueue failure, or no worker picking the job up, runs inline;
  * the worker handlers validate payloads and call the right functions.
What the SQL does with the rows (stage CHECK, unique request key, RLS bucket
E) is pinned against real Postgres in the migration commit's checks and
tests/integration/test_rls_policies_db.py.
"""
from __future__ import annotations

import asyncio
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import document_indexing as di
from services import document_jobs as dj
from services import jobs
from services.agent_events import SaplingEvent
from services.encryption import decrypt_bytes, decrypt_json, encrypt_bytes, encrypt_json
from tests.split_patches import patch_documents


# ── helpers ─────────────────────────────────────────────────────────────────


def _run(coro):
    return asyncio.run(coro)


async def _collect(agen):
    return [x async for x in agen]


def _text(n: int = 120) -> str:
    return ("This sample body is long enough to read as a real document. " * 4)[:n]


def _rows(*rows):
    """read_status side effect: each poll returns the next row, then the last."""
    seq = list(rows)

    def _next(_upload_id):
        return seq.pop(0) if len(seq) > 1 else seq[0]
    return _next


def _ago(seconds: float) -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


_FULL_PROGRESS = {"char_count": 1234, "category": "lecture_notes", "is_syllabus": False,
                  "concept_count": 2, "merged_count": 2}


# ── encryption helper ───────────────────────────────────────────────────────


def test_encrypt_bytes_round_trips_binary_and_is_not_the_plaintext():
    raw = bytes(range(256)) * 3
    enc = encrypt_bytes(raw)
    assert isinstance(enc, str) and raw not in enc.encode()
    assert decrypt_bytes(enc) == raw
    assert encrypt_bytes(raw) != enc  # fresh nonce per call


# ── document.index ──────────────────────────────────────────────────────────


def test_schedule_index_flag_off_indexes_inline_and_enqueues_nothing():
    with patch.object(di, "flag_on", return_value=False) as flag, \
         patch.object(di, "index_document") as idx, \
         patch.object(di.jobs, "enqueue") as enq:
        di.schedule_document_index("doc-1", "u1")
    flag.assert_called_once_with("jobs_queue", "u1")
    idx.assert_called_once_with("doc-1")
    enq.assert_not_called()


def test_schedule_index_flag_on_enqueues_a_deduped_job_and_does_not_index():
    with patch.object(di, "flag_on", return_value=True), \
         patch.object(di, "index_document") as idx, \
         patch.object(di.jobs, "enqueue", return_value={"id": "j1", "inserted": True}) as enq:
        di.schedule_document_index("doc-1", "u1")
    enq.assert_called_once_with("document.index", {"doc_id": "doc-1"},
                                dedupe_key="document.index:doc-1")
    idx.assert_not_called()


def test_schedule_index_falls_back_inline_when_the_enqueue_fails():
    with patch.object(di, "flag_on", return_value=True), \
         patch.object(di, "index_document") as idx, \
         patch.object(di.jobs, "enqueue", side_effect=RuntimeError("42P01")):
        di.schedule_document_index("doc-1", "u1")
    idx.assert_called_once_with("doc-1")


@pytest.mark.parametrize("payload", [{}, {"doc_id": ""}, {"doc_id": 7}, None])
def test_index_job_refuses_a_payload_without_a_doc_id(payload):
    with pytest.raises(jobs.PermanentJobError):
        di._run_document_index_job(payload)


@pytest.mark.parametrize("outcome", [
    di.IndexOutcome(di.INDEXED, 3),
    di.IndexOutcome(di.SKIPPED),
    di.IndexOutcome(di.EXHAUSTED, 0, "no_chunks"),
    di.IndexOutcome(di.INDEXING),  # someone else (the sweeper) holds the row
    di.IndexOutcome(di.FAILED, error="no_such_document"),
    # Short with budget left: recorded on the row, re-driven by the sweeper on
    # its own backoff — never a fast queue retry that burns the budget.
    di.IndexOutcome(di.FAILED, 0, "embed_failed"),
    di.IndexOutcome(di.PARTIAL, 2, "embed_failed"),
])
def test_index_job_completes_on_every_recorded_outcome(outcome):
    with patch.object(di, "index_document", return_value=outcome) as idx:
        di._run_document_index_job({"doc_id": "doc-1"})
    # Its own compare-and-swap claim (claimed=False), never the sweeper's SQL
    # claim, so the row's attempt budget and lease rules apply unchanged.
    idx.assert_called_once_with("doc-1")


def test_index_job_fails_so_the_queue_retries_when_the_row_is_unreachable():
    with patch.object(di, "index_document", side_effect=RuntimeError("PostgREST down")):
        with pytest.raises(RuntimeError):
            di._run_document_index_job({"doc_id": "doc-1"})


def test_the_worker_loads_both_new_job_types():
    from worker.__main__ import HANDLER_MODULES, load_handlers

    assert "services.document_indexing" in HANDLER_MODULES
    assert "services.document_jobs" in HANDLER_MODULES
    types = load_handlers()
    assert {"document.index", "document.process", "course_context.refresh"} <= set(types)
    assert jobs.get_handler("document.index") is di._run_document_index_job
    assert jobs.get_handler("document.process") is dj._run_document_process_job


# ── should_queue ────────────────────────────────────────────────────────────


def test_should_queue_follows_the_flag_for_the_uploader():
    with patch.object(dj, "flag_on", return_value=False) as flag:
        assert dj.should_queue("u1", 10) is False
    flag.assert_called_once_with("jobs_queue", "u1")
    with patch.object(dj, "flag_on", return_value=True):
        assert dj.should_queue("u1", 10) is True


def test_should_queue_keeps_big_files_inline_and_survives_a_flag_error():
    with patch.object(dj, "flag_on", return_value=True) as flag:
        assert dj.should_queue("u1", dj.QUEUED_UPLOAD_MAX_BYTES + 1) is False
    flag.assert_not_called()
    with patch.object(dj, "flag_on", side_effect=RuntimeError("store down")):
        assert dj.should_queue("u1", 10) is False


# ── staging ─────────────────────────────────────────────────────────────────

_STAGE_KW = dict(user_id="u1", offering_id="off-1", course_id="c-1", request_id="rid-1",
                 filename="notes.pdf", content_type="application/pdf", file_bytes=b"%PDF-1.4 x")


def test_stage_upload_inserts_an_encrypted_row_keyed_on_the_request():
    t = MagicMock()
    t.return_value.select.return_value = []
    t.return_value.insert.return_value = [{"id": "up-1"}]
    with patch.object(dj, "table", t):
        staged = dj.stage_upload(**_STAGE_KW)
    assert staged == dj.Staged(id="up-1", fresh=True)
    t.assert_any_call("document_uploads")
    row = t.return_value.insert.call_args.args[0]
    assert row["user_id"] == "u1" and row["request_id"] == "rid-1"
    assert row["stage"] == "queued" and row["file_size"] == len(b"%PDF-1.4 x")
    assert decrypt_bytes(row["file_data"]) == b"%PDF-1.4 x"
    assert row["offering_id"] == "off-1" and row["course_id"] == "c-1"


@pytest.mark.parametrize("stage,age", [("failed", 0), ("inline", dj.INLINE_STALE_SECONDS + 60)])
def test_stage_upload_requeues_an_ended_attempt_of_the_same_request(stage, age):
    t = MagicMock()
    t.return_value.select.return_value = [{"id": "up-1", "stage": stage,
                                           "updated_at": _ago(age)}]
    t.return_value.update.return_value = [{"id": "up-1"}]
    with patch.object(dj, "table", t):
        staged = dj.stage_upload(**_STAGE_KW)
    assert staged == dj.Staged(id="up-1", fresh=True)
    data, = t.return_value.update.call_args.args
    assert data["stage"] == "queued" and data["error_code"] is None
    assert data["job_id"] is None and data["progress"] == {}  # no stale owner / dead job
    assert t.return_value.update.call_args.kwargs["filters"] == {
        "id": "eq.up-1", "stage": f"eq.{stage}"}
    t.return_value.insert.assert_not_called()


@pytest.mark.parametrize("stage", ["queued", "classifying", "done", "inline"])
def test_stage_upload_attaches_to_a_live_or_finished_attempt(stage):
    t = MagicMock()
    # A fresh row; `done` with its document still live (the same select answers
    # the documents lookup here); `inline` = another request is running it.
    t.return_value.select.return_value = [{"id": "up-1", "stage": stage, "user_id": "u1",
                                           "document_id": "doc-1", "updated_at": _ago(1)}]
    with patch.object(dj, "table", t):
        staged = dj.stage_upload(**_STAGE_KW)
    assert staged == dj.Staged(id="up-1", fresh=False)
    t.return_value.insert.assert_not_called()
    t.return_value.update.assert_not_called()


def test_stage_upload_attaches_when_a_concurrent_retry_wins_the_insert():
    t = MagicMock()
    t.return_value.select.side_effect = [[], [{"id": "up-9", "stage": "queued"}]]
    t.return_value.insert.side_effect = RuntimeError("23505")
    with patch.object(dj, "table", t):
        assert dj.stage_upload(**_STAGE_KW) == dj.Staged(id="up-9", fresh=False)


def test_stage_and_enqueue_enqueues_a_deduped_job_with_ids_only():
    with patch.object(dj, "stage_upload", return_value=dj.Staged("up-1", True)), \
         patch.object(dj.jobs, "enqueue", return_value={"id": "j-1", "inserted": True}) as enq, \
         patch.object(dj, "table") as t:
        assert dj.stage_and_enqueue(**_STAGE_KW) == "up-1"
    enq.assert_called_once_with("document.process", {"upload_id": "up-1"},
                                dedupe_key="document.process:up-1")
    t.return_value.update.assert_called_once()  # job_id recorded


def test_stage_and_enqueue_does_not_enqueue_twice_for_an_attached_retry():
    with patch.object(dj, "stage_upload", return_value=dj.Staged("up-1", False)), \
         patch.object(dj.jobs, "enqueue") as enq:
        assert dj.stage_and_enqueue(**_STAGE_KW) == "up-1"
    enq.assert_not_called()


def test_stage_and_enqueue_takes_the_upload_back_when_the_enqueue_fails():
    holder = dj.InlineClaim()
    token = dj._INLINE_CLAIM.set(holder)
    try:
        with patch.object(dj, "stage_upload", return_value=dj.Staged("up-1", True)), \
             patch.object(dj.jobs, "enqueue", side_effect=RuntimeError("PGRST202")), \
             patch.object(dj, "take_back", return_value=True) as back:
            assert dj.stage_and_enqueue(**_STAGE_KW) is None
    finally:
        dj._INLINE_CLAIM.reset(token)
    upload_id, tok = back.call_args.args
    assert upload_id == "up-1" and tok
    # This request now owns the inline run, and records its outcome there.
    assert (holder.upload_id, holder.token) == ("up-1", tok)


def test_stage_and_enqueue_watches_when_the_take_back_itself_errors():
    with patch.object(dj, "stage_upload", return_value=dj.Staged("up-1", True)), \
         patch.object(dj.jobs, "enqueue", side_effect=RuntimeError("PGRST202")), \
         patch.object(dj, "take_back", side_effect=RuntimeError("blip")):
        assert dj.stage_and_enqueue(**_STAGE_KW) == "up-1"


def test_stage_and_enqueue_runs_inline_when_staging_fails():
    with patch.object(dj, "stage_upload", side_effect=RuntimeError("42P01")), \
         patch.object(dj.jobs, "enqueue") as enq:
        assert dj.stage_and_enqueue(**_STAGE_KW) is None
    enq.assert_not_called()


# ── SSE progress mapping ────────────────────────────────────────────────────

_EXPECTED_STEPS = [
    ("progress", "extracting_text"), ("progress", "extracted_text"),
    ("progress", "classify"), ("progress", "classified"), ("progress", "extract"),
    ("progress", "extracted"), ("progress", "graph_update"), ("progress", "graph_updated"),
    ("result", "finalize"), ("status", "done"),
]


@pytest.mark.parametrize("rows", [
    # every stage seen
    [{"stage": s, "progress": _FULL_PROGRESS} for s in
     ("queued", "extracting", "classifying", "extracting_concepts", "merging", "saving")],
    # a poll that skips straight from queued to done still emits every stage once
    [{"stage": "queued", "progress": {}}],
])
def test_stream_emits_the_inline_event_sequence_however_polls_land(rows):
    done = {"id": "up-1", "stage": "done", "progress": _FULL_PROGRESS, "document_id": "doc-7"}
    stored = {"result": {"classification": {"category": "lecture_notes"}}, "categories": []}
    with patch.object(dj, "read_status", side_effect=_rows(*rows, done)), \
         patch.object(dj, "read_result", return_value=stored), \
         patch.object(dj, "POLL_INTERVAL_SECONDS", 0):
        watch = dj.Watch()
        events = _run(_collect(dj.stream_events("up-1", request_id="rid", outcome=watch)))
    assert [(e.type, e.step) for e in events] == _EXPECTED_STEPS
    assert watch.kind == "done"
    by_step = {e.step: e for e in events}
    assert by_step["classified"].data == {"category": "lecture_notes", "is_syllabus": False}
    assert by_step["extracted_text"].message == "Extracted 1,234 chars."
    assert by_step["finalize"].data == stored["result"]
    assert events[-1].data == {"document_id": "doc-7"}


def test_stream_maps_a_failed_upload_to_the_inline_error_tail():
    from routes.documents import UNREADABLE_DOCUMENT_DETAIL

    rows = [{"stage": "extracting", "progress": {}},
            {"stage": "failed", "error_code": "unreadable", "progress": {}}]
    with patch.object(dj, "read_status", side_effect=_rows(*rows)), \
         patch.object(dj, "POLL_INTERVAL_SECONDS", 0):
        watch = dj.Watch()
        events = _run(_collect(dj.stream_events("up-1", request_id="rid", outcome=watch)))
    assert [(e.type, e.step) for e in events] == [
        ("progress", "extracting_text"), ("error", "failed"), ("status", "done")]
    assert events[1].message == UNREADABLE_DOCUMENT_DETAIL
    assert events[1].data == {"request_id": "rid"}
    assert events[2].message == "Failed."


def test_stream_hands_back_to_inline_when_no_worker_picks_it_up():
    with patch.object(dj, "read_status", return_value={"stage": "queued", "progress": {}}), \
         patch.object(dj, "take_back", return_value=True) as back, \
         patch.object(dj, "PICKUP_GRACE_SECONDS", 0), \
         patch.object(dj, "POLL_INTERVAL_SECONDS", 0):
        watch = dj.Watch()
        events = _run(_collect(dj.stream_events("up-1", request_id="rid", outcome=watch)))
    assert events == [] and watch.kind == "inline"
    assert back.call_count == 1 and back.call_args.args[0] == "up-1"


def test_stream_keeps_watching_when_a_worker_wins_the_take_back_race():
    rows = [{"stage": "queued", "progress": {}},
            {"stage": "done", "progress": _FULL_PROGRESS, "document_id": "d"}]
    with patch.object(dj, "read_status", side_effect=_rows(*rows)), \
         patch.object(dj, "take_back", return_value=False), \
         patch.object(dj, "read_result", return_value={"result": {}}), \
         patch.object(dj, "PICKUP_GRACE_SECONDS", 0), \
         patch.object(dj, "POLL_INTERVAL_SECONDS", 0):
        watch = dj.Watch()
        events = _run(_collect(dj.stream_events("up-1", request_id=None, outcome=watch)))
    assert watch.kind == "done" and events[-1].step == "done"


def test_stream_gives_up_after_max_wait_with_an_honest_message():
    with patch.object(dj, "read_status", return_value={"stage": "classifying", "progress": {}}), \
         patch.object(dj, "POLL_INTERVAL_SECONDS", 0):
        watch = dj.Watch()
        events = _run(_collect(dj.stream_events("up-1", request_id="r", outcome=watch,
                                                max_wait=0)))
    assert watch.kind == "timeout"
    assert [(e.type, e.step) for e in events][-2:] == [("error", "failed"), ("status", "done")]
    assert events[-2].message == dj.TIMEOUT_MESSAGE


def test_watch_fails_an_upload_whose_job_was_dead_lettered():
    running = {"stage": "classifying", "progress": {}, "job_id": "j-1"}
    failed = {"stage": "failed", "error_code": "worker_failed", "progress": {}}
    reads = [running] * dj._JOB_CHECK_EVERY + [failed]
    with patch.object(dj, "read_status", side_effect=_rows(*reads)), \
         patch.object(dj, "job_status", return_value="dead"), \
         patch.object(dj, "fail_if_running", return_value=True) as fail, \
         patch.object(dj, "POLL_INTERVAL_SECONDS", 0):
        out = _run(dj.wait_for_upload("up-1"))
    fail.assert_called_once_with("up-1", "classifying", "worker_failed")
    assert out.kind == "failed"


# ── the worker: document.process ────────────────────────────────────────────


def _agent_patches(*, is_syllabus=False):
    from agents.classifier import DocumentClassification
    from agents.concept_extraction import Concept, ConceptList
    from agents.summary import Summary

    cls = DocumentClassification(category="lecture_notes", is_syllabus=is_syllabus,
                                 confidence=0.9, rationale="t")
    summary = Summary(headline="h", abstract="abstract.", key_points=["a", "b", "c"])
    concepts = ConceptList(concepts=[Concept(name="Backprop", description="d", importance=0.9)])
    return (
        patch("agents.classifier.classifier_agent.run",
              AsyncMock(return_value=SimpleNamespace(output=cls))),
        patch("agents.summary.summary_agent.run",
              AsyncMock(return_value=SimpleNamespace(output=summary))),
        patch("agents.concept_extraction.concept_extraction_agent.run",
              AsyncMock(return_value=SimpleNamespace(output=concepts))),
        patch("agents.document.apply_concepts_to_graph", AsyncMock(return_value=1)),
        patch("agents.document.record_agent_usage", side_effect=lambda r, **kw: r),
    )


def _staged_row(**over):
    row = {"id": "up-1", "user_id": "u1", "offering_id": "off-1", "course_id": "c-1",
           "request_id": "rid-1", "file_name": "notes.pdf", "content_type": "application/pdf",
           "file_data": encrypt_bytes(b"%PDF-1.4 x"), "stage": "queued"}
    row.update(over)
    return row


class _Uploads:
    """A fake `table` whose document_uploads row records each update. Honours
    the stage and owner compare-and-swap filters like PostgREST would; a
    `jobs` select answers from `job_row`."""

    def __init__(self, row, job_row=None):
        self.row = dict(row)
        self.job_row = job_row or {}
        self.updates: list[tuple[dict, dict]] = []
        self.refused: list[tuple[dict, dict]] = []

    def _owner(self, key):
        return (self.row.get("progress") or {}).get(key)

    def _matches(self, filters):
        for key, want in filters.items():
            if key == "id":
                continue
            if key == "stage":
                have = self.row.get("stage")
            elif key.startswith("progress->>"):
                have = self._owner(key.split("->>", 1)[1])
            else:
                have = self.row.get(key)
            if want == "is.null":
                if have is not None:
                    return False
            elif want != f"eq.{have}":
                return False
        return True

    def __call__(self, name):
        fake = MagicMock()
        if name == "jobs":
            fake.select.side_effect = lambda *a, **k: [dict(self.job_row)] if self.job_row else []
            return fake
        assert name == "document_uploads", name
        fake.select.side_effect = lambda *a, **k: [dict(self.row)]

        def update(data, filters, **_):
            if not self._matches(filters):
                self.refused.append((dict(data), dict(filters)))
                return []
            self.updates.append((dict(data), dict(filters)))
            self.row.update(data)
            return [dict(self.row)]
        fake.update.side_effect = update
        return fake


def _process(row, *, extract=None, persist=None, existing=None, agents=None, job_row=None):
    uploads = _Uploads(row, job_row)
    extract = extract or MagicMock(return_value=_text())
    persist = persist or MagicMock(return_value=("doc-1", {"id": "doc-1"}))
    patches = list(agents if agents is not None else _agent_patches())
    post = {name: MagicMock() for name in (
        "_invalidate_study_guide_cache", "_refresh_course_context",
        "_check_upload_achievements")}
    sched = MagicMock()
    with patch.object(dj, "table", uploads), \
         patch_documents("extract_text_from_file", extract), \
         patch_documents("_persist_document", persist), \
         patch_documents("_existing_doc_by_request_id", side_effect=existing or
               (lambda *a: None)), \
         patch_documents("_save_orchestrator_syllabus"), \
         patch_documents("_graph_backstop"), \
         patch_documents("_invalidate_study_guide_cache", post["_invalidate_study_guide_cache"]), \
         patch_documents("_refresh_course_context", post["_refresh_course_context"]), \
         patch_documents("_check_upload_achievements", post["_check_upload_achievements"]), \
         patch("services.document_indexing.schedule_document_index", sched):
        for p in patches:
            p.start()
        try:
            dj._run_document_process_job({"upload_id": row["id"]})
        finally:
            for p in patches:
                p.stop()
    return SimpleNamespace(uploads=uploads, extract=extract, persist=persist, post=post,
                           sched=sched)


@pytest.mark.parametrize("payload", [{}, {"upload_id": ""}, None, {"upload_id": 3}])
def test_process_job_refuses_a_payload_without_an_upload_id(payload):
    with pytest.raises(jobs.PermanentJobError):
        dj._run_document_process_job(payload)


def test_process_job_runs_the_pipeline_and_records_every_stage():
    out = _process(_staged_row())
    stages = [d["stage"] for d, _ in out.uploads.updates if "stage" in d]
    assert stages == ["extracting", "classifying", "extracting_concepts", "merging",
                      "saving", "done"]
    # The worker took it from `queued` with a compare-and-swap.
    assert out.uploads.updates[0][1] == {"id": "eq.up-1", "stage": "eq.queued"}
    out.extract.assert_called_once_with(b"%PDF-1.4 x", "notes.pdf", "application/pdf")
    kw = out.persist.call_args.kwargs
    assert kw["request_id"] == "rid-1" and kw["offering_id"] == "off-1"
    assert kw["extracted_text"] == _text() and kw["course_id"] == "c-1"
    final = out.uploads.row
    assert final["document_id"] == "doc-1" and final["file_data"] is None
    stored = decrypt_json(final["result"])
    assert stored["result"]["classification"]["category"] == "lecture_notes"
    assert stored["categories"] == []
    owner = final["progress"].pop("owner")
    assert owner.startswith("direct#")  # no worker claim in this test
    assert final["progress"] == {"char_count": len(_text()), "category": "lecture_notes",
                                 "is_syllabus": False, "concept_count": 1, "merged_count": 1}
    # Every write after the claim is fenced on that owner and the stage it left.
    for data, filters in out.uploads.updates[1:]:
        assert filters["progress->>owner"] == f"eq.{owner}"
        assert filters["stage"].startswith("eq.") and filters["stage"] != "eq.done"
    # The streaming route's post-roll, uploader threaded through.
    out.post["_invalidate_study_guide_cache"].assert_called_once_with("u1", "off-1")
    out.post["_refresh_course_context"].assert_called_once_with("off-1", "u1")
    out.post["_check_upload_achievements"].assert_called_once_with("u1")
    out.sched.assert_called_once_with("doc-1", "u1")


@pytest.mark.parametrize("stage", ["done", "failed", "inline"])
def test_process_job_is_a_no_op_on_a_terminal_upload(stage):
    out = _process(_staged_row(stage=stage))
    assert out.uploads.updates == []
    out.extract.assert_not_called()


def test_process_job_records_an_unreadable_document_without_calling_the_agents():
    agents = _agent_patches()
    out = _process(_staged_row(), extract=MagicMock(return_value="  "), agents=agents)
    assert out.uploads.row["stage"] == "failed"
    assert out.uploads.row["error_code"] == "unreadable"
    assert out.uploads.row["file_data"] is None
    out.persist.assert_not_called()


def test_process_job_records_an_extraction_crash():
    out = _process(_staged_row(), extract=MagicMock(side_effect=RuntimeError("docling")))
    assert (out.uploads.row["stage"], out.uploads.row["error_code"]) == ("failed",
                                                                        "extract_failed")


def test_process_job_records_an_agent_failure_and_saves_nothing():
    agents = list(_agent_patches())
    agents[0] = patch("agents.classifier.classifier_agent.run",
                      AsyncMock(side_effect=RuntimeError("provider down")))
    out = _process(_staged_row(), agents=agents)
    assert (out.uploads.row["stage"], out.uploads.row["error_code"]) == ("failed",
                                                                        "agent_failed")
    out.persist.assert_not_called()
    out.sched.assert_not_called()


def test_process_job_adopts_the_row_a_racing_attempt_saved():
    calls = iter([None, {"id": "doc-w"}])
    out = _process(_staged_row(), persist=MagicMock(side_effect=RuntimeError("23505")),
                   existing=lambda *a: next(calls))
    assert out.uploads.row["stage"] == "done"
    assert out.uploads.row["document_id"] == "doc-w"
    out.sched.assert_not_called()  # the winner already ran the post-roll


def test_process_job_rerun_adopts_a_document_an_earlier_attempt_saved():
    saved = {"id": "doc-old", "category": "other", "summary": "s", "concept_notes": []}
    out = _process(_staged_row(stage="saving"), existing=lambda *a: saved)
    assert out.uploads.row["stage"] == "done"
    assert out.uploads.row["document_id"] == "doc-old"
    out.extract.assert_not_called()


# ── routes, flag OFF: unchanged ─────────────────────────────────────────────


def _client():
    from fastapi.testclient import TestClient

    from main import app
    return TestClient(app)


def _parse(raw: bytes) -> list[tuple[str, dict]]:
    from tests.test_documents_routes import _parse_sse_stream

    return [(e["event"], json.loads(e["data"])) for e in _parse_sse_stream(raw)]


def _route_agent_patches():
    from agents.classifier import DocumentClassification
    from agents.concept_extraction import Concept, ConceptList
    from agents.summary import Summary

    cls = DocumentClassification(category="lecture_notes", is_syllabus=False,
                                 confidence=0.9, rationale="t")
    summary = Summary(headline="h", abstract="abstract.", key_points=["a", "b", "c"])
    concepts = ConceptList(concepts=[Concept(name="Backprop", description="d", importance=0.9)])
    return (
        patch("agents.classifier.classifier_agent.run",
              AsyncMock(return_value=SimpleNamespace(output=cls))),
        patch("agents.summary.summary_agent.run",
              AsyncMock(return_value=SimpleNamespace(output=summary))),
        patch("agents.concept_extraction.concept_extraction_agent.run",
              AsyncMock(return_value=SimpleNamespace(output=concepts))),
        patch("agents.document.apply_concepts_to_graph", AsyncMock(return_value=0)),
    )


def _stream_upload(client):
    with client.stream(
        "POST", "/api/documents/upload",
        files={"file": ("notes.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")},
        data={"course_id": "c-1", "user_id": "u1"},
    ) as r:
        assert r.status_code == 200
        return _parse(r.read())


_INLINE_STEPS = [("status", "start"), ("progress", "classify"), ("progress", "classified"),
                 ("progress", "extract"), ("progress", "extracted"),
                 ("progress", "graph_update"), ("progress", "graph_updated"),
                 ("result", "finalize"), ("status", "done")]


def test_flag_off_stream_is_unchanged_and_never_touches_the_queue():
    a, b, c, d = _route_agent_patches()
    with patch_documents("_validate_user"), \
         patch_documents("require_course_enrollment", return_value="off-1"), \
         patch.object(dj, "flag_on", return_value=False), \
         patch.object(dj, "stage_and_enqueue", side_effect=AssertionError("staged")), \
         patch_documents("extract_text_from_file", return_value=_text()) as ext, \
         a, b, c, d, \
         patch_documents("table") as t, \
         patch_documents("_spawn_post_roll") as spawn:
        t.return_value.select.return_value = []
        t.return_value.insert.return_value = [{"id": "stream-1"}]
        events = _stream_upload(_client())
    assert [(e, d["step"]) for e, d in events] == _INLINE_STEPS
    ext.assert_called_once()
    tasks = {task[0]: task[1:] for task in spawn.call_args.args}
    from routes import documents
    assert tasks["index_document"] == (documents.schedule_document_index, "stream-1", "u1")


def test_flag_off_sync_is_unchanged_and_never_touches_the_queue():
    from tests.test_documents_routes import _make_orchestrator_result

    result = _make_orchestrator_result()
    with patch_documents("_validate_user"), \
         patch_documents("require_course_enrollment", return_value="off-1"), \
         patch.object(dj, "flag_on", return_value=False), \
         patch.object(dj, "sync_via_queue", side_effect=AssertionError("queued")), \
         patch_documents("extract_text_from_file", return_value=_text()) as ext, \
         patch_documents("_existing_doc_by_request_id", return_value=None), \
         patch_documents("process_document", AsyncMock(return_value=result)), \
         patch_documents("_persist_document", return_value=("doc-1", {"id": "doc-1"})), \
         patch_documents("refresh_course_context"), \
         patch_documents("_invalidate_study_guide_cache"), \
         patch_documents("_check_upload_achievements"), \
         patch_documents("schedule_document_index") as sched:
        r = _client().post(
            "/api/documents/upload/sync",
            files={"file": ("notes.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")},
            data={"course_id": "c-1", "user_id": "u1"},
        )
    assert r.status_code == 200 and r.json() == {"id": "doc-1", "categories": []}
    ext.assert_called_once()
    sched.assert_called_once_with("doc-1", "u1")


# ── routes, flag ON ─────────────────────────────────────────────────────────


def test_flag_on_stream_relays_the_worker_and_runs_nothing_inline():
    done = {"id": "up-1", "stage": "done", "progress": _FULL_PROGRESS, "document_id": "doc-7"}
    with patch_documents("_validate_user"), \
         patch_documents("require_course_enrollment", return_value="off-1"), \
         patch_documents("_existing_doc_by_request_id", return_value=None), \
         patch.object(dj, "flag_on", return_value=True), \
         patch.object(dj, "stage_and_enqueue", return_value="up-1") as stage, \
         patch.object(dj, "read_status", side_effect=_rows(
             {"stage": "queued", "progress": {}}, done)), \
         patch.object(dj, "read_result", return_value={"result": {"id": "x"}}), \
         patch.object(dj, "POLL_INTERVAL_SECONDS", 0), \
         patch_documents("extract_text_from_file") as ext, \
         patch("agents.classifier.classifier_agent.run") as cls, \
         patch_documents("_spawn_post_roll") as spawn:
        events = _stream_upload(_client())
    assert [(e, d["step"]) for e, d in events] == [("status", "start"), *_EXPECTED_STEPS]
    assert events[-1][1]["data"] == {"document_id": "doc-7"}
    kw = stage.call_args.kwargs
    assert kw["user_id"] == "u1" and kw["offering_id"] == "off-1" and kw["course_id"] == "c-1"
    assert kw["file_bytes"] == b"%PDF-1.4 x" and kw["filename"] == "notes.pdf"
    ext.assert_not_called()
    cls.assert_not_called()
    spawn.assert_not_called()  # the worker runs the post-roll


def test_flag_on_stream_runs_inline_when_the_queue_cannot_take_it():
    a, b, c, d = _route_agent_patches()
    with patch_documents("_validate_user"), \
         patch_documents("require_course_enrollment", return_value="off-1"), \
         patch.object(dj, "flag_on", return_value=True), \
         patch.object(dj, "stage_and_enqueue", return_value=None), \
         patch_documents("extract_text_from_file", return_value=_text()) as ext, \
         a, b, c, d, \
         patch_documents("table") as t, \
         patch_documents("_spawn_post_roll") as spawn:
        t.return_value.select.return_value = []
        t.return_value.insert.return_value = [{"id": "stream-1"}]
        events = _stream_upload(_client())
    # The in-stream (OCR_ASYNC) path: extraction inside the stream, then as usual.
    assert [(e, d["step"]) for e, d in events] == [
        ("status", "start"), ("progress", "extracting_text"), ("progress", "extracted_text"),
        *_INLINE_STEPS[1:]]
    ext.assert_called_once()
    spawn.assert_called_once()


def _sync_post(client):
    return client.post(
        "/api/documents/upload/sync",
        files={"file": ("notes.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")},
        data={"course_id": "c-1", "user_id": "u1"},
    )


def _sync_flag_on(**over):
    base = dict(
        validate=patch_documents("_validate_user"),
        offering=patch_documents("require_course_enrollment", return_value="off-1"),
        replay=patch_documents("_existing_doc_by_request_id", return_value=None),
        flag=patch.object(dj, "flag_on", return_value=True),
        stage=patch.object(dj, "stage_and_enqueue", return_value="up-1"),
        poll=patch.object(dj, "POLL_INTERVAL_SECONDS", 0),
    )
    base.update(over)
    return base


def test_flag_on_sync_returns_the_saved_row_and_categories():
    done = {"id": "up-1", "stage": "done", "progress": {}, "document_id": "doc-7"}
    saved = {"id": "doc-7", "file_name": "notes.pdf", "summary": encrypt_json({"x": 1})}
    cms = _sync_flag_on()
    with cms["validate"], cms["offering"], cms["replay"], cms["flag"], cms["stage"], \
         cms["poll"], \
         patch.object(dj, "read_status", return_value=done), \
         patch.object(dj, "read_result", return_value={"categories": [{"name": "HW",
                                                                       "weight": 0.5}]}), \
         patch("services.documents_read.table") as t, \
         patch.object(dj, "clear_result") as clear, \
         patch_documents("extract_text_from_file") as ext, \
         patch_documents("process_document") as proc:
        t.return_value.select.return_value = [{**saved, "extracted_text": "secret"}]
        r = _sync_post(_client())
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "doc-7" and "extracted_text" not in body
    assert body["categories"] == [{"name": "HW", "weight": 0.5}]
    assert t.return_value.select.call_args.kwargs["filters"] == {
        "id": "eq.doc-7", "user_id": "eq.u1", "deleted_at": "is.null"}
    clear.assert_called_once_with("up-1")  # delivered: the outcome is dropped
    ext.assert_not_called()
    proc.assert_not_called()


@pytest.mark.parametrize("code,status", [
    ("unreadable", 422), ("extract_failed", 422), ("agent_failed", 502),
    ("persist_failed", 502), ("worker_failed", 502),
])
def test_flag_on_sync_maps_failures_like_the_inline_route(code, status):
    cms = _sync_flag_on()
    with cms["validate"], cms["offering"], cms["replay"], cms["flag"], cms["stage"], \
         cms["poll"], \
         patch.object(dj, "read_status",
                      return_value={"stage": "failed", "error_code": code, "progress": {}}):
        r = _sync_post(_client())
    assert r.status_code == status


def test_flag_on_sync_times_out_with_504():
    cms = _sync_flag_on()
    with cms["validate"], cms["offering"], cms["replay"], cms["flag"], cms["stage"], \
         cms["poll"], \
         patch.object(dj, "read_status", return_value={"stage": "merging", "progress": {}}), \
         patch.object(dj, "SYNC_MAX_WAIT_SECONDS", 0), \
         patch("services.document_jobs.wait_for_upload",
               AsyncMock(return_value=dj.Watch(kind="timeout"))):
        r = _sync_post(_client())
    assert r.status_code == 504


def test_flag_on_sync_runs_inline_when_the_queue_cannot_take_it():
    from tests.test_documents_routes import _make_orchestrator_result

    cms = _sync_flag_on(stage=patch.object(dj, "stage_and_enqueue", return_value=None))
    with cms["validate"], cms["offering"], cms["replay"], cms["flag"], cms["stage"], \
         patch_documents("extract_text_from_file", return_value=_text()) as ext, \
         patch_documents("process_document",
               AsyncMock(return_value=_make_orchestrator_result())), \
         patch_documents("_persist_document", return_value=("doc-1", {"id": "doc-1"})), \
         patch_documents("refresh_course_context"), \
         patch_documents("_invalidate_study_guide_cache"), \
         patch_documents("_check_upload_achievements"), \
         patch_documents("schedule_document_index"):
        r = _sync_post(_client())
    assert r.status_code == 200 and r.json()["id"] == "doc-1"
    ext.assert_called_once()


# ── #116 review: the owner fence on re-delivery ─────────────────────────────


def test_redelivery_while_the_row_still_moves_is_retried_not_restarted():
    # The earlier attempt wrote a stage seconds ago: it is alive (with the
    # heartbeat it would never have been re-delivered at all).
    row = _staged_row(stage="classifying", progress={"owner": "w1#1"}, updated_at=_ago(5))
    uploads = _Uploads(row)
    with patch.object(dj, "table", uploads), pytest.raises(dj.UploadBusy):
        dj._run_document_process_job({"upload_id": "up-1"})
    assert uploads.updates == [] and uploads.refused == []  # nothing moved or restarted


def test_redelivery_takes_over_a_quiet_row_fenced_on_the_previous_owner():
    row = _staged_row(stage="classifying", progress={"owner": "w1#1"},
                      updated_at=_ago(dj._LEASE_SECONDS + 30))
    out = _process(row)
    data, filters = out.uploads.updates[0]
    assert filters == {"id": "eq.up-1", "stage": "eq.classifying",
                       "progress->>owner": "eq.w1#1"}
    assert data["stage"] == "extracting" and data["progress"]["owner"] != "w1#1"
    assert out.uploads.row["stage"] == "done"


def test_redelivery_just_short_of_the_lease_waits_it_out_then_takes_over():
    row = _staged_row(stage="merging", progress={"owner": "w1#1"},
                      updated_at=_ago(dj._LEASE_SECONDS - 10))
    with patch.object(dj, "_sleep") as sleep:
        out = _process(row)
    (waited,), _ = sleep.call_args
    assert 0 < waited <= 11
    assert out.uploads.updates[0][1]["progress->>owner"] == "eq.w1#1"
    assert out.uploads.row["stage"] == "done"


def test_redelivery_that_finds_the_row_moved_after_the_wait_is_retried():
    row = _staged_row(stage="merging", progress={"owner": "w1#1"},
                      updated_at=_ago(dj._LEASE_SECONDS - 10))
    uploads = _Uploads(row)

    def moved(_seconds):  # the old owner was alive after all
        uploads.row.update(stage="saving")

    with patch.object(dj, "table", uploads), patch.object(dj, "_sleep", side_effect=moved), \
         pytest.raises(dj.UploadBusy):
        dj._run_document_process_job({"upload_id": "up-1"})
    assert uploads.updates == []


def test_a_superseded_attempt_never_moves_the_stage_again():
    uploads_box = {}

    def extract_then_lose_the_row(*_a):
        # Meanwhile the watcher saw the job dead-lettered and failed the row.
        uploads_box["u"].row.update(stage="failed", error_code="worker_failed")
        return _text()

    row = _staged_row()
    uploads = _Uploads(row)
    uploads_box["u"] = uploads
    persist = MagicMock()
    with patch.object(dj, "table", uploads), \
         patch_documents("extract_text_from_file", extract_then_lose_the_row), \
         patch_documents("_persist_document", persist), \
         patch_documents("_existing_doc_by_request_id", return_value=None):
        dj._run_document_process_job({"upload_id": "up-1"})  # returns quietly
    assert uploads.row["stage"] == "failed" and uploads.row["error_code"] == "worker_failed"
    assert [d["stage"] for d, _ in uploads.updates] == ["extracting"]
    assert uploads.refused and uploads.refused[0][0]["stage"] == "classifying"
    persist.assert_not_called()


def test_an_attempt_taken_over_mid_run_cannot_overwrite_the_new_owner():
    uploads_box = {}

    def extract_then_get_taken_over(*_a):
        uploads_box["u"].row.update(stage="extracting", progress={"owner": "w2#2"})
        return _text()

    uploads = _Uploads(_staged_row())
    uploads_box["u"] = uploads
    with patch.object(dj, "table", uploads), \
         patch_documents("extract_text_from_file", extract_then_get_taken_over), \
         patch_documents("_existing_doc_by_request_id", return_value=None):
        dj._run_document_process_job({"upload_id": "up-1"})
    assert uploads.row["progress"] == {"owner": "w2#2"}
    assert uploads.row["stage"] == "extracting"


def test_the_worker_claim_is_the_owner_and_a_stale_claim_does_nothing():
    job = jobs.Job(id="j-1", type="document.process", payload={}, attempt=2,
                   max_attempts=5, locked_by="w1")
    token = jobs._CURRENT_JOB.set(job)
    try:
        current = {"status": "running", "attempts": 2, "locked_by": "w1"}
        out = _process(_staged_row(), job_row=current)
        assert out.uploads.row["progress"]["owner"] == "w1#2"
        assert out.uploads.row["stage"] == "done"
        # The jobs row moved on (re-claimed as attempt 3): this attempt is stale.
        stale = _process(_staged_row(), job_row={**current, "attempts": 3})
        assert stale.uploads.updates == []
        stale.extract.assert_not_called()
    finally:
        jobs._CURRENT_JOB.reset(token)


def test_the_runner_exposes_the_claimed_job_to_its_handler():
    from worker.runner import Worker

    seen = {}
    queue = MagicMock()
    queue.get_handler.return_value = lambda payload: seen.setdefault("job", jobs.current_job())
    queue.complete.return_value = True
    job = jobs.Job(id="j-1", type="t", payload={}, attempt=1, max_attempts=5, locked_by="w")
    Worker(worker_id="w", types=["t"], queue=queue)._run(job)
    assert seen["job"] is job
    assert jobs.current_job() is None  # reset after the run


# ── #116 review: the watch survives database blips ──────────────────────────


def test_watch_rides_out_a_failed_poll():
    done = {"id": "up-1", "stage": "done", "progress": _FULL_PROGRESS, "document_id": "doc-7"}
    reads = iter([RuntimeError("blip"), {"stage": "classifying", "progress": _FULL_PROGRESS},
                  RuntimeError("blip"), done])

    def read(_id):
        item = next(reads)
        if isinstance(item, Exception):
            raise item
        return item

    with patch.object(dj, "read_status", side_effect=read), \
         patch.object(dj, "read_result", return_value={"result": {"ok": 1}}), \
         patch.object(dj, "clear_result"), \
         patch.object(dj, "POLL_INTERVAL_SECONDS", 0):
        watch = dj.Watch()
        events = _run(_collect(dj.stream_events("up-1", request_id="r", outcome=watch)))
    assert watch.kind == "done" and events[-1].step == "done"
    assert events[-2].data == {"ok": 1}


def test_watch_gives_up_only_after_the_error_budget():
    read = MagicMock(side_effect=RuntimeError("PostgREST down"))
    with patch.object(dj, "read_status", read), \
         patch.object(dj, "POLL_INTERVAL_SECONDS", 0):
        watch = dj.Watch()
        events = _run(_collect(dj.stream_events("up-1", request_id="r", outcome=watch)))
    assert read.call_count == dj._MAX_DB_ERRORS
    assert watch.kind == "timeout"
    assert [(e.type, e.step) for e in events] == [("error", "failed"), ("status", "done")]
    assert events[0].message == dj.TIMEOUT_MESSAGE


def test_watch_retries_a_failed_take_back_and_job_check():
    rows = [{"stage": "queued", "progress": {}}, {"stage": "queued", "progress": {}}]
    back = MagicMock(side_effect=[RuntimeError("blip"), True])
    with patch.object(dj, "read_status", side_effect=_rows(*rows)), \
         patch.object(dj, "take_back", back), \
         patch.object(dj, "PICKUP_GRACE_SECONDS", 0), \
         patch.object(dj, "POLL_INTERVAL_SECONDS", 0):
        out = _run(dj.wait_for_upload("up-1"))
    assert out.kind == "inline" and back.call_count == 2

    running = {"stage": "merging", "progress": {}, "job_id": "j-1"}
    failed = {"stage": "failed", "error_code": "worker_failed", "progress": {}}
    reads = [running] * (2 * dj._JOB_CHECK_EVERY) + [failed]
    status = MagicMock(side_effect=[RuntimeError("blip"), "dead"])
    with patch.object(dj, "read_status", side_effect=_rows(*reads)), \
         patch.object(dj, "job_status", status), \
         patch.object(dj, "fail_if_running", return_value=True) as fail, \
         patch.object(dj, "POLL_INTERVAL_SECONDS", 0):
        out = _run(dj.wait_for_upload("up-1"))
    assert status.call_count == 2 and fail.call_count == 1 and out.kind == "failed"


def test_watch_owns_a_take_back_whose_answer_was_lost():
    box = {}

    def take_back(_id, token):
        box["token"] = token
        raise RuntimeError("timeout after the write landed")

    def read(_id):
        if "token" not in box:
            return {"stage": "queued", "progress": {}}
        return {"stage": "inline", "progress": {"inline_owner": box["token"]}}

    with patch.object(dj, "read_status", side_effect=read), \
         patch.object(dj, "take_back", side_effect=take_back), \
         patch.object(dj, "PICKUP_GRACE_SECONDS", 0), \
         patch.object(dj, "POLL_INTERVAL_SECONDS", 0):
        out = _run(dj.wait_for_upload("up-1"))
    assert out.kind == "inline"


def test_flag_on_sync_survives_a_status_blip():
    done = {"id": "up-1", "stage": "done", "progress": {}, "document_id": "doc-7",
            "user_id": "u1"}
    reads = iter([RuntimeError("blip"), done])

    def read(_id):
        item = next(reads, done)
        if isinstance(item, Exception):
            raise item
        return item

    cms = _sync_flag_on()
    with cms["validate"], cms["offering"], cms["replay"], cms["flag"], cms["stage"], \
         cms["poll"], \
         patch.object(dj, "read_status", side_effect=read), \
         patch.object(dj, "read_result", side_effect=[RuntimeError("blip"), {}]), \
         patch.object(dj, "saved_document", return_value={"id": "doc-7"}), \
         patch.object(dj, "clear_result"):
        r = _sync_post(_client())
    assert r.status_code == 200 and r.json() == {"id": "doc-7", "categories": []}


# ── #116 review: two requests on one row ────────────────────────────────────


def _foreign_inline(**over):
    return {"id": "up-1", "stage": "inline", "user_id": "u1", "request_id": "rid-1",
            "progress": {"inline_owner": "someone-else"}, **over}


def test_a_watcher_never_runs_a_row_another_request_took_inline():
    saved = {"id": "doc-9", "category": "lecture_notes", "summary": "s",
             "concept_notes": [{"name": "Backprop", "description": "d"}]}
    calls = iter([None, None, saved])
    with patch.object(dj, "read_status", return_value=_foreign_inline()), \
         patch_documents("_existing_doc_by_request_id",
               side_effect=lambda *a: next(calls)), \
         patch.object(dj, "read_result", return_value={}), \
         patch.object(dj, "saved_document", return_value=saved), \
         patch.object(dj, "clear_result"), \
         patch.object(dj, "take_back") as back, \
         patch.object(dj, "POLL_INTERVAL_SECONDS", 0):
        watch = dj.Watch()
        events = _run(_collect(dj.stream_events("up-1", request_id="r", outcome=watch)))
    back.assert_not_called()
    assert watch.kind == "done"
    # The owner's document, replayed: no stage events it never saw run.
    assert [(e.type, e.step) for e in events] == [("result", "finalize"), ("status", "done")]
    assert events[0].data["id"] == "doc-9" and events[0].data["replayed"] is True
    assert events[1].data == {"document_id": "doc-9"}


def test_a_watcher_reports_the_failure_the_inline_owner_recorded():
    rows = [_foreign_inline(), {**_foreign_inline(), "stage": "failed",
                                "error_code": "unreadable"}]
    with patch.object(dj, "read_status", side_effect=_rows(*rows)), \
         patch_documents("_existing_doc_by_request_id", return_value=None), \
         patch.object(dj, "POLL_INTERVAL_SECONDS", 0):
        out = _run(dj.wait_for_upload("up-1"))
    assert out.kind == "failed" and out.row["error_code"] == "unreadable"


def test_finish_inline_records_only_on_the_row_this_request_owns():
    t = MagicMock()
    t.return_value.update.return_value = [{"id": "up-1"}]
    claim = dj.InlineClaim(upload_id="up-1", token="tok")
    with patch.object(dj, "table", t):
        assert dj.finish_inline(claim, document_id="doc-1") is True
        assert dj.finish_inline(claim, document_id="doc-1") is False  # once
    data = t.return_value.update.call_args.args[0]
    assert data["stage"] == "done" and data["document_id"] == "doc-1"
    assert data["file_data"] is None and data["result"] is None
    assert t.return_value.update.call_args.kwargs["filters"] == {
        "id": "eq.up-1", "stage": "eq.inline", "progress->>inline_owner": "eq.tok"}
    t.reset_mock()
    with patch.object(dj, "table", t):
        dj.finish_inline(dj.InlineClaim("up-2", "tok"), error_code="extract_failed")
    data = t.return_value.update.call_args.args[0]
    assert data["stage"] == "failed" and data["error_code"] == "extract_failed"


def _claiming_stage(*_a, **_k):
    dj._claim_inline("up-1", "tok")
    return None  # the enqueue failed and this request took the row back


def test_flag_on_stream_records_the_inline_runs_outcome_on_the_row():
    a, b, c, d = _route_agent_patches()
    with patch_documents("_validate_user"), \
         patch_documents("require_course_enrollment", return_value="off-1"), \
         patch.object(dj, "flag_on", return_value=True), \
         patch.object(dj, "stage_and_enqueue", side_effect=_claiming_stage), \
         patch.object(dj, "finish_inline") as finish, \
         patch_documents("extract_text_from_file", return_value=_text()), \
         a, b, c, d, \
         patch_documents("table") as t, \
         patch_documents("_spawn_post_roll"):
        t.return_value.select.return_value = []
        t.return_value.insert.return_value = [{"id": "stream-1"}]
        events = _stream_upload(_client())
    assert events[-1][1]["data"] == {"document_id": "stream-1"}
    claim = finish.call_args.args[0]
    assert (claim.upload_id, claim.token) == ("up-1", "tok")
    assert finish.call_args.kwargs == {"document_id": "stream-1"}


def test_flag_on_stream_records_an_inline_failure_with_its_code():
    with patch_documents("_validate_user"), \
         patch_documents("require_course_enrollment", return_value="off-1"), \
         patch_documents("_existing_doc_by_request_id", return_value=None), \
         patch.object(dj, "flag_on", return_value=True), \
         patch.object(dj, "stage_and_enqueue", side_effect=_claiming_stage), \
         patch.object(dj, "finish_inline") as finish, \
         patch_documents("extract_text_from_file", side_effect=RuntimeError("ocr")):
        events = _stream_upload(_client())
    assert [(e, d["step"]) for e, d in events][-2:] == [("error", "failed"), ("status", "done")]
    assert finish.call_args.kwargs == {"error_code": "extract_failed"}


def test_flag_on_stream_records_nothing_when_the_worker_ran_it():
    done = {"id": "up-1", "stage": "done", "progress": _FULL_PROGRESS, "document_id": "doc-7"}
    with patch_documents("_validate_user"), \
         patch_documents("require_course_enrollment", return_value="off-1"), \
         patch_documents("_existing_doc_by_request_id", return_value=None), \
         patch.object(dj, "flag_on", return_value=True), \
         patch.object(dj, "stage_and_enqueue", return_value="up-1"), \
         patch.object(dj, "read_status", return_value=done), \
         patch.object(dj, "read_result", return_value={"result": {"id": "x"}}), \
         patch.object(dj, "clear_result") as clear, \
         patch.object(dj, "finish_inline") as finish, \
         patch.object(dj, "POLL_INTERVAL_SECONDS", 0):
        _stream_upload(_client())
    finish.assert_not_called()
    clear.assert_called_once_with("up-1")  # the result was delivered


@pytest.mark.parametrize("extract,code", [
    (MagicMock(return_value="  "), "unreadable"),
    (MagicMock(side_effect=RuntimeError("ocr")), "extract_failed"),
])
def test_flag_on_sync_records_an_inline_failure(extract, code):
    cms = _sync_flag_on(stage=patch.object(dj, "stage_and_enqueue",
                                           side_effect=_claiming_stage))
    with cms["validate"], cms["offering"], cms["replay"], cms["flag"], cms["stage"], \
         patch.object(dj, "finish_inline") as finish, \
         patch_documents("extract_text_from_file", extract):
        r = _sync_post(_client())
    assert r.status_code == 422
    assert finish.call_args.kwargs == {"error_code": code}


def test_flag_on_sync_records_the_inline_success():
    from tests.test_documents_routes import _make_orchestrator_result

    cms = _sync_flag_on(stage=patch.object(dj, "stage_and_enqueue",
                                           side_effect=_claiming_stage))
    with cms["validate"], cms["offering"], cms["replay"], cms["flag"], cms["stage"], \
         patch.object(dj, "finish_inline") as finish, \
         patch_documents("extract_text_from_file", return_value=_text()), \
         patch_documents("process_document",
               AsyncMock(return_value=_make_orchestrator_result())), \
         patch_documents("_persist_document", return_value=("doc-1", {"id": "doc-1"})), \
         patch_documents("refresh_course_context"), \
         patch_documents("_invalidate_study_guide_cache"), \
         patch_documents("_check_upload_achievements"), \
         patch_documents("schedule_document_index"):
        r = _sync_post(_client())
    assert r.status_code == 200
    assert finish.call_args.kwargs == {"document_id": "doc-1", "error_code": None}


def test_sync_adopts_a_duplicate_that_saved_first_instead_of_500():
    from tests.test_documents_routes import _make_orchestrator_result

    winner = {"id": "doc-w", "file_name": "notes.pdf", "summary": "s", "concept_notes": []}
    with patch_documents("_validate_user"), \
         patch_documents("require_course_enrollment", return_value="off-1"), \
         patch.object(dj, "flag_on", return_value=False), \
         patch_documents("extract_text_from_file", return_value=_text()), \
         patch_documents("_existing_doc_by_request_id", side_effect=[None, winner]), \
         patch_documents("process_document",
               AsyncMock(return_value=_make_orchestrator_result())), \
         patch_documents("_persist_document", side_effect=RuntimeError("23505")), \
         patch_documents("schedule_document_index") as sched:
        r = _sync_post(_client())
    assert r.status_code == 200 and r.json() == {**winner, "categories": []}
    sched.assert_not_called()  # the winner ran the post-roll


def test_sync_still_fails_when_the_insert_fails_and_nothing_was_saved():
    from tests.test_documents_routes import _make_orchestrator_result

    with patch_documents("_validate_user"), \
         patch_documents("require_course_enrollment", return_value="off-1"), \
         patch.object(dj, "flag_on", return_value=False), \
         patch_documents("extract_text_from_file", return_value=_text()), \
         patch_documents("_existing_doc_by_request_id", return_value=None), \
         patch_documents("process_document",
               AsyncMock(return_value=_make_orchestrator_result())), \
         patch_documents("_persist_document", side_effect=RuntimeError("boom")):
        from fastapi.testclient import TestClient

        from main import app
        r = TestClient(app, raise_server_exceptions=False).post(
            "/api/documents/upload/sync",
            files={"file": ("notes.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")},
            data={"course_id": "c-1", "user_id": "u1"},
        )
    assert r.status_code == 500


# ── #116 review: retention and abandoned rows ───────────────────────────────


def test_clear_result_drops_the_outcome_of_a_finished_row_only():
    t = MagicMock()
    with patch.object(dj, "table", t):
        dj.clear_result("up-1")
    data, = t.return_value.update.call_args.args
    assert data == {"result": None, "file_data": None}
    assert t.return_value.update.call_args.kwargs["filters"] == {
        "id": "eq.up-1", "stage": "in.(done,failed)"}
    t.return_value.update.side_effect = RuntimeError("blip")
    with patch.object(dj, "table", t):
        dj.clear_result("up-1")  # best-effort: never raises


def test_every_failure_clears_the_bytes_and_any_stored_outcome():
    out = _process(_staged_row(), persist=MagicMock(side_effect=RuntimeError("down")))
    assert (out.uploads.row["stage"], out.uploads.row["error_code"]) == ("failed",
                                                                        "persist_failed")
    assert out.uploads.row["file_data"] is None and out.uploads.row["result"] is None
    t = MagicMock()
    with patch.object(dj, "table", t):
        dj.fail_if_running("up-1", "merging", "worker_failed")
    data, = t.return_value.update.call_args.args
    assert data["file_data"] is None and data["result"] is None


@pytest.mark.parametrize("job,fresh", [(None, True), ("dead", True), ("succeeded", True),
                                       ("queued", False), ("running", False),
                                       ("failed", False)])
def test_stage_upload_restages_an_abandoned_queued_row(job, fresh):
    t = MagicMock()
    seen = _ago(dj.PICKUP_GRACE_SECONDS + 60)
    t.return_value.select.return_value = [{"id": "up-1", "stage": "queued", "user_id": "u1",
                                           "updated_at": seen, "job_id": None}]
    t.return_value.update.return_value = [{"id": "up-1"}]
    with patch.object(dj, "table", t), patch.object(dj, "job_status", return_value=job):
        staged = dj.stage_upload(**_STAGE_KW)
    assert staged == dj.Staged(id="up-1", fresh=fresh)
    if fresh:
        assert t.return_value.update.call_args.kwargs["filters"] == {
            "id": "eq.up-1", "stage": "eq.queued", "updated_at": f"eq.{seen}"}
    else:
        t.return_value.update.assert_not_called()


def test_stage_upload_attaches_to_a_queued_row_when_the_job_check_fails():
    t = MagicMock()
    t.return_value.select.return_value = [{"id": "up-1", "stage": "queued", "user_id": "u1",
                                           "updated_at": _ago(dj.PICKUP_GRACE_SECONDS + 60)}]
    with patch.object(dj, "table", t), \
         patch.object(dj, "job_status", side_effect=RuntimeError("blip")):
        assert dj.stage_upload(**_STAGE_KW) == dj.Staged(id="up-1", fresh=False)


# ── #116 review: a done row whose document was deleted ──────────────────────


def test_stage_upload_restages_a_done_row_whose_document_was_deleted():
    t = MagicMock()
    upload = [{"id": "up-1", "stage": "done", "user_id": "u1", "document_id": "doc-1"}]
    t.side_effect = lambda name: _table_with(name, uploads=upload, documents=[])
    with patch.object(dj, "table", t):
        staged = dj.stage_upload(**_STAGE_KW)
    assert staged == dj.Staged(id="up-1", fresh=True)
    docs_select = _TABLES["documents"].select.call_args.kwargs["filters"]
    assert docs_select["deleted_at"] == "is.null"


def test_stage_upload_restages_a_done_row_whose_document_was_hard_deleted():
    t = MagicMock()
    upload = [{"id": "up-1", "stage": "done", "user_id": "u1", "document_id": None}]
    t.side_effect = lambda name: _table_with(name, uploads=upload, documents=[{"id": "x"}])
    with patch.object(dj, "table", t):
        assert dj.stage_upload(**_STAGE_KW) == dj.Staged(id="up-1", fresh=True)


_TABLES: dict = {}


def _table_with(name, *, uploads, documents):
    if name not in _TABLES or getattr(_TABLES[name], "_fresh_for", None) is not uploads:
        fake = MagicMock()
        fake._fresh_for = uploads
        fake.select.return_value = uploads if name == "document_uploads" else documents
        fake.update.return_value = [{"id": "up-1"}]
        _TABLES[name] = fake
    return _TABLES[name]


def test_saved_document_never_returns_a_soft_deleted_row():
    from services import documents_read

    with patch("services.documents_read.table") as t:
        t.return_value.select.return_value = []
        assert documents_read.saved_document("doc-1", "u1") is None
    assert t.return_value.select.call_args.kwargs["filters"]["deleted_at"] == "is.null"


# ── #116 review: adopting an earlier attempt's saved document ───────────────


def test_rerun_adoption_restores_the_stored_result_categories_and_quiet_progress():
    cats = [{"name": "Exams", "weight": 0.6}]
    stored = {"result": {"classification": {"category": "syllabus", "is_syllabus": True}},
              "categories": cats}
    saved = {"id": "doc-old", "category": "syllabus", "summary": "s",
             "concept_notes": [{"name": "A"}, {"name": "B"}]}
    row = _staged_row(stage="saving", result=encrypt_json(stored),
                      progress={"owner": "w1#1"}, updated_at=_ago(dj._LEASE_SECONDS + 5))
    out = _process(row, existing=lambda *a: saved)
    final = out.uploads.row
    assert final["stage"] == "done" and final["document_id"] == "doc-old"
    assert decrypt_json(final["result"]) == stored
    progress = {k: v for k, v in final["progress"].items() if k != "owner"}
    assert progress == {"adopted": True, "category": "syllabus", "concept_count": 2}
    out.extract.assert_not_called()
    out.sched.assert_not_called()

    # The stream for that row: no "Extracted 0 chars" from a run that never ran.
    with patch.object(dj, "read_status", return_value={**final, "id": "up-1"}), \
         patch.object(dj, "clear_result"), \
         patch.object(dj, "POLL_INTERVAL_SECONDS", 0), \
         patch.object(dj, "table", out.uploads):
        watch = dj.Watch()
        events = _run(_collect(dj.stream_events("up-1", request_id="r", outcome=watch)))
    assert [(e.type, e.step) for e in events] == [("result", "finalize"), ("status", "done")]
    assert events[0].data == stored["result"]


def test_rerun_adoption_without_a_stored_outcome_replays_the_saved_row():
    saved = {"id": "doc-old", "category": "other", "summary": "s", "concept_notes": []}
    row = _staged_row(stage="saving", updated_at=_ago(dj._LEASE_SECONDS + 5))
    out = _process(row, existing=lambda *a: saved)
    stored = decrypt_json(out.uploads.row["result"])
    assert stored["categories"] == [] and stored["result"]["id"] == "doc-old"
    assert stored["result"]["replayed"] is True


def test_the_pipeline_stores_its_outcome_before_the_insert():
    seen = {}

    def persist(**_kw):
        seen["row"] = dict(box["u"].row)
        return ("doc-1", {"id": "doc-1"})

    box = {}
    uploads = _Uploads(_staged_row())
    box["u"] = uploads
    patches = list(_agent_patches())
    with patch.object(dj, "table", uploads), \
         patch_documents("extract_text_from_file", return_value=_text()), \
         patch_documents("_persist_document", side_effect=persist), \
         patch_documents("_existing_doc_by_request_id", return_value=None), \
         patch_documents("_save_orchestrator_syllabus"), \
         patch_documents("_graph_backstop"), \
         patch("services.document_indexing.schedule_document_index"), \
         patch_documents("_invalidate_study_guide_cache"), \
         patch_documents("_refresh_course_context"), \
         patch_documents("_check_upload_achievements"):
        for p in patches:
            p.start()
        try:
            dj._run_document_process_job({"upload_id": "up-1"})
        finally:
            for p in patches:
                p.stop()
    assert seen["row"]["stage"] == "saving"
    assert decrypt_json(seen["row"]["result"])["categories"] == []


# ── #116 review: dead-letter detection without the recorded job id ─────────


def test_job_status_falls_back_to_the_dedupe_key():
    t = MagicMock()
    t.return_value.select.return_value = [{"status": "dead"}]
    with patch.object(dj, "table", t):
        assert dj.job_status("up-1", None) == "dead"
    kw = t.return_value.select.call_args.kwargs
    assert kw["filters"] == {"dedupe_key": "eq.document.process:up-1"}
    assert kw["order"] == "created_at.desc"
    with patch.object(dj, "table", t):
        dj.job_status("up-1", "j-1")
    assert t.return_value.select.call_args.kwargs["filters"] == {"id": "eq.j-1"}


def test_watch_fails_a_dead_lettered_upload_that_never_recorded_its_job():
    running = {"stage": "classifying", "progress": {}}  # no job_id
    failed = {"stage": "failed", "error_code": "worker_failed", "progress": {}}
    reads = [running] * dj._JOB_CHECK_EVERY + [failed]
    with patch.object(dj, "read_status", side_effect=_rows(*reads)), \
         patch.object(dj, "job_status", return_value="dead") as status, \
         patch.object(dj, "fail_if_running", return_value=True) as fail, \
         patch.object(dj, "POLL_INTERVAL_SECONDS", 0):
        out = _run(dj.wait_for_upload("up-1"))
    status.assert_called_once_with("up-1", None)
    fail.assert_called_once_with("up-1", "classifying", "worker_failed")
    assert out.kind == "failed"


# ── #116 review: one decrypt for a saved row ────────────────────────────────


def test_decrypt_document_row_is_shared_by_the_replay_and_the_queue():
    from services.documents_read import decrypt_document_row
    from services.encryption import encrypt

    row = {"id": "d", "summary": encrypt("plain"), "concept_notes": encrypt_json([{"name": "A"}]),
           "extracted_text": "secret"}
    out = decrypt_document_row(row)
    assert out == {"id": "d", "summary": "plain", "concept_notes": [{"name": "A"}]}
    assert decrypt_document_row({"concept_notes": "garbage!"})["concept_notes"] == []
    with patch_documents("table") as t:
        t.return_value.select.return_value = [row]
        from routes.documents import _existing_doc_by_request_id
        assert _existing_doc_by_request_id("u1", "r")["summary"] == "plain"


def test_record_inline_outcome_marks_an_abandoned_inline_run():
    from services.agent_events import sapling_event_to_sse

    async def inner():
        dj._claim_inline("up-1", "tok")
        yield sapling_event_to_sse(SaplingEvent(type="status", step="start", message="go"))
        yield sapling_event_to_sse(SaplingEvent(type="progress", step="classify", message="x"))

    async def consume_one():
        gen = dj.record_inline_outcome(inner())
        await gen.__anext__()
        await gen.aclose()  # the client went away mid-run

    with patch.object(dj, "finish_inline") as finish:
        _run(consume_one())
    claim = finish.call_args.args[0]
    assert claim.upload_id == "up-1"
    assert finish.call_args.kwargs == {"error_code": "abandoned"}


def test_record_inline_outcome_is_inert_without_a_claim():
    from services.agent_events import sapling_event_to_sse

    async def inner():
        yield sapling_event_to_sse(SaplingEvent(type="status", step="done", message="Saved.",
                                                data={"document_id": "d"}))

    with patch.object(dj, "finish_inline") as finish:
        frames = _run(_collect(dj.record_inline_outcome(inner())))
    assert len(frames) == 1
    finish.assert_not_called()
