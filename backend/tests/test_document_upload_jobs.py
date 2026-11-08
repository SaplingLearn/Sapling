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
from services.encryption import decrypt_bytes, decrypt_json, encrypt_bytes, encrypt_json


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


@pytest.mark.parametrize("stage", ["failed", "inline"])
def test_stage_upload_requeues_an_ended_attempt_of_the_same_request(stage):
    t = MagicMock()
    t.return_value.select.return_value = [{"id": "up-1", "stage": stage}]
    t.return_value.update.return_value = [{"id": "up-1"}]
    with patch.object(dj, "table", t):
        staged = dj.stage_upload(**_STAGE_KW)
    assert staged == dj.Staged(id="up-1", fresh=True)
    data, = t.return_value.update.call_args.args
    assert data["stage"] == "queued" and data["error_code"] is None
    assert t.return_value.update.call_args.kwargs["filters"] == {
        "id": "eq.up-1", "stage": f"eq.{stage}"}
    t.return_value.insert.assert_not_called()


@pytest.mark.parametrize("stage", ["queued", "classifying", "done"])
def test_stage_upload_attaches_to_a_live_or_finished_attempt(stage):
    t = MagicMock()
    t.return_value.select.return_value = [{"id": "up-1", "stage": stage}]
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
    with patch.object(dj, "stage_upload", return_value=dj.Staged("up-1", True)), \
         patch.object(dj.jobs, "enqueue", side_effect=RuntimeError("PGRST202")), \
         patch.object(dj, "take_back", return_value=True) as back:
        assert dj.stage_and_enqueue(**_STAGE_KW) is None
    back.assert_called_once_with("up-1")


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
    back.assert_called_once_with("up-1")


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
        patch("agents.tools.graph.apply_concepts_to_graph", AsyncMock(return_value=1)),
        patch("agents.usage.record_agent_usage", side_effect=lambda r, **kw: r),
    )


def _staged_row(**over):
    row = {"id": "up-1", "user_id": "u1", "offering_id": "off-1", "course_id": "c-1",
           "request_id": "rid-1", "file_name": "notes.pdf", "content_type": "application/pdf",
           "file_data": encrypt_bytes(b"%PDF-1.4 x"), "stage": "queued"}
    row.update(over)
    return row


class _Uploads:
    """A fake `table` whose document_uploads row records each update."""

    def __init__(self, row):
        self.row = dict(row)
        self.updates: list[tuple[dict, dict]] = []

    def __call__(self, name):
        assert name == "document_uploads", name
        fake = MagicMock()
        fake.select.side_effect = lambda *a, **k: [dict(self.row)]

        def update(data, filters, **_):
            want = filters.get("stage")
            if want is not None and want != f"eq.{self.row['stage']}":
                return []
            self.updates.append((dict(data), dict(filters)))
            self.row.update(data)
            return [dict(self.row)]
        fake.update.side_effect = update
        return fake


def _process(row, *, extract=None, persist=None, existing=None, agents=None):
    uploads = _Uploads(row)
    extract = extract or MagicMock(return_value=_text())
    persist = persist or MagicMock(return_value=("doc-1", {"id": "doc-1"}))
    patches = list(agents if agents is not None else _agent_patches())
    post = {name: MagicMock() for name in (
        "_invalidate_study_guide_cache", "_refresh_course_context",
        "_check_upload_achievements")}
    sched = MagicMock()
    with patch.object(dj, "table", uploads), \
         patch("routes.documents.extract_text_from_file", extract), \
         patch("routes.documents._persist_document", persist), \
         patch("routes.documents._existing_doc_by_request_id", side_effect=existing or
               (lambda *a: None)), \
         patch("routes.documents._save_orchestrator_syllabus"), \
         patch("routes.documents._graph_backstop"), \
         patch("routes.documents._invalidate_study_guide_cache", post["_invalidate_study_guide_cache"]), \
         patch("routes.documents._refresh_course_context", post["_refresh_course_context"]), \
         patch("routes.documents._check_upload_achievements", post["_check_upload_achievements"]), \
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
    assert final["progress"] == {"char_count": len(_text()), "category": "lecture_notes",
                                 "is_syllabus": False, "concept_count": 1, "merged_count": 1}
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
        patch("routes.documents.classifier_agent.run",
              AsyncMock(return_value=SimpleNamespace(output=cls))),
        patch("routes.documents.summary_agent.run",
              AsyncMock(return_value=SimpleNamespace(output=summary))),
        patch("routes.documents.concept_extraction_agent.run",
              AsyncMock(return_value=SimpleNamespace(output=concepts))),
        patch("routes.documents.apply_concepts_to_graph", AsyncMock(return_value=0)),
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
    with patch("routes.documents._validate_user"), \
         patch("routes.documents.resolve_offering", return_value="off-1"), \
         patch.object(dj, "flag_on", return_value=False), \
         patch.object(dj, "stage_and_enqueue", side_effect=AssertionError("staged")), \
         patch("routes.documents.extract_text_from_file", return_value=_text()) as ext, \
         a, b, c, d, \
         patch("routes.documents.table") as t, \
         patch("routes.documents._spawn_post_roll") as spawn:
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
    with patch("routes.documents._validate_user"), \
         patch("routes.documents.resolve_offering", return_value="off-1"), \
         patch.object(dj, "flag_on", return_value=False), \
         patch.object(dj, "sync_via_queue", side_effect=AssertionError("queued")), \
         patch("routes.documents.extract_text_from_file", return_value=_text()) as ext, \
         patch("routes.documents._existing_doc_by_request_id", return_value=None), \
         patch("routes.documents.process_document", AsyncMock(return_value=result)), \
         patch("routes.documents._persist_document", return_value=("doc-1", {"id": "doc-1"})), \
         patch("routes.documents.refresh_course_context"), \
         patch("routes.documents._invalidate_study_guide_cache"), \
         patch("routes.documents._check_upload_achievements"), \
         patch("routes.documents.schedule_document_index") as sched:
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
    with patch("routes.documents._validate_user"), \
         patch("routes.documents.resolve_offering", return_value="off-1"), \
         patch("routes.documents._existing_doc_by_request_id", return_value=None), \
         patch.object(dj, "flag_on", return_value=True), \
         patch.object(dj, "stage_and_enqueue", return_value="up-1") as stage, \
         patch.object(dj, "read_status", side_effect=_rows(
             {"stage": "queued", "progress": {}}, done)), \
         patch.object(dj, "read_result", return_value={"result": {"id": "x"}}), \
         patch.object(dj, "POLL_INTERVAL_SECONDS", 0), \
         patch("routes.documents.extract_text_from_file") as ext, \
         patch("routes.documents.classifier_agent.run") as cls, \
         patch("routes.documents._spawn_post_roll") as spawn:
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
    with patch("routes.documents._validate_user"), \
         patch("routes.documents.resolve_offering", return_value="off-1"), \
         patch.object(dj, "flag_on", return_value=True), \
         patch.object(dj, "stage_and_enqueue", return_value=None), \
         patch("routes.documents.extract_text_from_file", return_value=_text()) as ext, \
         a, b, c, d, \
         patch("routes.documents.table") as t, \
         patch("routes.documents._spawn_post_roll") as spawn:
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
        validate=patch("routes.documents._validate_user"),
        offering=patch("routes.documents.resolve_offering", return_value="off-1"),
        replay=patch("routes.documents._existing_doc_by_request_id", return_value=None),
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
         patch.object(dj, "table") as t, \
         patch("routes.documents.extract_text_from_file") as ext, \
         patch("routes.documents.process_document") as proc:
        t.return_value.select.return_value = [{**saved, "extracted_text": "secret"}]
        r = _sync_post(_client())
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "doc-7" and "extracted_text" not in body
    assert body["categories"] == [{"name": "HW", "weight": 0.5}]
    assert t.return_value.select.call_args.kwargs["filters"] == {
        "id": "eq.doc-7", "user_id": "eq.u1"}
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
         patch("routes.documents.extract_text_from_file", return_value=_text()) as ext, \
         patch("routes.documents.process_document",
               AsyncMock(return_value=_make_orchestrator_result())), \
         patch("routes.documents._persist_document", return_value=("doc-1", {"id": "doc-1"})), \
         patch("routes.documents.refresh_course_context"), \
         patch("routes.documents._invalidate_study_guide_cache"), \
         patch("routes.documents._check_upload_achievements"), \
         patch("routes.documents.schedule_document_index"):
        r = _sync_post(_client())
    assert r.status_code == 200 and r.json()["id"] == "doc-1"
    ext.assert_called_once()
