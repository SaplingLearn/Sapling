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

from services import ai_budget
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


@pytest.mark.parametrize("in_job", [False, True])
def test_upload_drafting_starts_nothing_past_the_uploaders_generation_budget(in_job):
    """Z20: upload-time drafting (in-process and on the worker) is minutes of
    model calls billed to the uploader. It asks the generation budget once per
    document, fresh; past it the document is indexed, nothing is drafted or
    queued, and the `pending` mark is taken back so draft on enable claims it
    when the budget has room."""
    from services.documents import post_roll as rd

    job = jobs.Job(id="j-1", type="check_items.document", payload={}, attempt=1,
                   max_attempts=5, locked_by="w")
    token = jobs._CURRENT_JOB.set(job) if in_job else None
    try:
        with patch.object(rd, "model_mode", return_value="real"), \
             patch.object(ai_budget, "check", return_value=MagicMock(level="hard")) as check, \
             patch.object(rd, "index_document") as idx, \
             patch.object(rd, "generate_for_document") as gen, \
             patch.object(rd, "queue_generation_for_document") as queue, \
             patch.object(rd, "clear_drafting") as clear:
            rd._index_then_draft("doc-1", "u1", "c-1", ["A"])
    finally:
        if token is not None:
            jobs._CURRENT_JOB.reset(token)
    check.assert_called_once_with("u1", "generation")
    idx.assert_called_once_with("doc-1")
    gen.assert_not_called()
    queue.assert_not_called()
    clear.assert_called_once_with("doc-1")


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


# ── the uploader's loop gate, at run time ───────────────────────────────────


def test_with_the_loop_off_a_failed_indexing_raises_for_the_queue_to_retry():
    from services import check_item_service, document_indexing

    with patch.object(cij, "learning_loop_for_uploader", return_value=False), \
         patch.object(document_indexing, "index_document", side_effect=RuntimeError("down")), \
         patch.object(check_item_service, "clear_drafting") as clear:
        with pytest.raises(RuntimeError):
            cij._run_check_items_document_job({"doc_id": "doc-1", "user_id": "u1", "course_id": "c-1"})
    clear.assert_called_once_with("doc-1")  # the mark is back before anything can fail


def test_the_handler_rereads_the_loop_gate_and_drafts_nothing_when_it_is_off():
    """A kill switch thrown (or the uploader's flag turned off) after the
    enqueue: the job indexes the document — indexing is the upload's — takes
    its `pending` mark back, and drafts nothing."""
    from services import check_item_service, document_indexing
    from services import documents as rd

    with patch.object(cij, "learning_loop_for_uploader", return_value=False) as gate, \
         patch.object(document_indexing, "index_document") as idx, \
         patch.object(check_item_service, "clear_drafting") as clear, \
         patch.object(cij, "table") as table, \
         patch.object(rd, "_index_then_draft") as chain:
        cij._run_check_items_document_job({"doc_id": "doc-1", "user_id": "u1", "course_id": "c-1"})
    gate.assert_called_once_with("u1")
    idx.assert_called_once_with("doc-1")
    clear.assert_called_once_with("doc-1")
    chain.assert_not_called()
    table.assert_not_called()  # not even the concept names are read


def test_the_kill_switch_reaches_a_job_enqueued_before_it_was_thrown(monkeypatch):
    import config
    from services import check_item_service, document_indexing
    from services import documents as rd

    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", False)
    with patch.object(document_indexing, "index_document"), \
         patch.object(check_item_service, "clear_drafting"), \
         patch.object(rd, "_index_then_draft") as chain:
        cij._run_check_items_document_job({"doc_id": "doc-1", "user_id": "u1", "course_id": "c-1"})
    chain.assert_not_called()


def test_clear_drafting_takes_only_a_pending_mark_back():
    from services import check_item_service as svc

    table = MagicMock()
    with patch.object(svc, "table", table):
        svc.clear_drafting("doc-1")
    data, = table.return_value.update.call_args.args
    assert data == {"check_items_status": None, "check_items_at": None}
    assert table.return_value.update.call_args.kwargs["filters"] == {
        "id": "eq.doc-1", "check_items_status": "eq.pending",
    }
    table.return_value.update.side_effect = RuntimeError("down")
    with patch.object(svc, "table", table):
        svc.clear_drafting("doc-1")  # bookkeeping: never raises


# ── draft on enable (C3) ────────────────────────────────────────────────────


@pytest.fixture
def scans():
    cij.reset_enable_scans()
    yield
    cij.reset_enable_scans()


def test_enable_schedules_each_claimed_document_on_the_job_path(scans):
    from services import check_item_service as svc

    with patch.object(svc, "claim_undrafted_documents", return_value=["d1", "d2"]) as claim, \
         patch.object(cij, "enqueue_for_document", return_value=True) as enqueue, \
         patch.object(cij, "_draft_in_process") as inline:
        assert cij.draft_missing_for_course("u1", "c-1") == 2
    assert claim.call_args.args == ("u1", "c-1")
    assert claim.call_args.kwargs["limit"] == cij.ENABLE_MAX_DOCS
    assert [c.args for c in enqueue.call_args_list] == [("d1",), ("d2",)]
    assert all(c.kwargs == {"user_id": "u1", "course_id": "c-1"} for c in enqueue.call_args_list)
    inline.assert_not_called()


def test_enable_runs_a_document_the_queue_did_not_take_on_the_drafting_pool(scans):
    from services import check_item_service as svc

    with patch.object(svc, "claim_undrafted_documents", return_value=["d1"]), \
         patch.object(cij, "enqueue_for_document", return_value=False), \
         patch.object(cij, "_draft_in_process") as inline:
        assert cij.draft_missing_for_course("u1", "c-1") == 1
    inline.assert_called_once_with("d1", "u1", "c-1")


def test_the_in_process_fallback_never_runs_on_the_callers_thread():
    import threading

    ran = {}

    def body(doc_id, user_id, course_id):
        ran.update(args=(doc_id, user_id, course_id), thread=threading.current_thread().name)

    with patch.object(cij, "_draft_document", side_effect=body):
        cij._draft_in_process("d1", "u1", "c-1").result(timeout=5)
    assert ran["args"] == ("d1", "u1", "c-1")
    assert ran["thread"].startswith("check-items") and ran["thread"] != threading.current_thread().name


def test_enable_rescans_a_course_at_most_once_per_interval(scans, monkeypatch):
    from services import check_item_service as svc

    clock = [1000.0]
    monkeypatch.setattr(cij.time, "monotonic", lambda: clock[0])
    with patch.object(svc, "claim_undrafted_documents", return_value=[]) as claim:
        cij.draft_missing_for_course("u1", "c-1")
        cij.draft_missing_for_course("u1", "c-1")  # the next request: no rescan
        cij.draft_missing_for_course("u1", "c-2")  # another course is its own scan
        clock[0] += cij.ENABLE_RESCAN_S
        cij.draft_missing_for_course("u1", "c-1")
    assert [c.args for c in claim.call_args_list] == [("u1", "c-1"), ("u1", "c-2"), ("u1", "c-1")]


@pytest.mark.parametrize("decision, ok", [
    ("normal", True), ("soft", True), ("hard", False),
    (ai_budget.AIBudgetUnavailable("usage unreadable"), False),
])
def test_enable_claims_nothing_past_the_generation_budget(scans, decision, ok):
    side = decision if isinstance(decision, Exception) else None
    ret = None if side else MagicMock(level=decision)
    with patch.object(ai_budget, "check", side_effect=side, return_value=ret) as check:
        assert cij.within_generation_budget("u1") is ok
    check.assert_called_once_with("u1", "generation")


def test_a_failed_scan_or_enqueue_never_fails_the_session(scans):
    from services import check_item_service as svc

    with patch.object(svc, "claim_undrafted_documents", side_effect=RuntimeError("down")):
        assert cij.draft_missing_for_course("u1", "c-1") == 0
    cij.reset_enable_scans()
    # the drafting pool refusing work (the app shutting down) skips that one only
    with patch.object(svc, "claim_undrafted_documents", return_value=["d1", "d2"]), \
         patch.object(cij, "enqueue_for_document", return_value=False), \
         patch.object(cij, "_draft_in_process",
                      side_effect=[RuntimeError("cannot schedule new futures after shutdown"), None]) as inline:
        assert cij.draft_missing_for_course("u1", "c-1") == 2
    assert inline.call_count == 2
    assert cij.draft_missing_for_course("", "c-1") == 0


def test_a_failure_on_the_drafting_pool_is_logged(caplog):
    from concurrent.futures import Future

    with patch.object(cij, "_draft_document", side_effect=RuntimeError("boom")):
        future = cij._draft_in_process("d1", "u1", "c-1")
        assert isinstance(future.exception(timeout=5), RuntimeError)
    failed = Future()
    failed.set_exception(RuntimeError("boom"))
    with caplog.at_level("ERROR"):
        cij._log_failure("d1", failed)
    assert any("draft on enable failed for doc d1" in r.getMessage() for r in caplog.records)


# ── claim_undrafted_documents, on a filter-honouring fake ───────────────────


def _cond(row: dict, expr: str) -> bool:
    """One PostgREST condition `col.op.value` (the ops the claim sends)."""
    col, op, val = expr.split(".", 2)
    cur = row.get(col)
    if op == "is":
        return cur is None
    if op == "eq":
        return cur is not None and str(cur) == val
    if op in ("lt", "gt"):
        return cur is not None and (str(cur) < val if op == "lt" else str(cur) > val)
    raise AssertionError(expr)


def _split_top(body: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in body:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    return [*parts, cur]


def _or(row: dict, expr: str) -> bool:
    def one(term: str) -> bool:
        if term.startswith("and("):
            return all(one(t) for t in _split_top(term[4:-1]))
        return _cond(row, term)

    return any(one(t) for t in _split_top(expr[1:-1]))


def _matches(row: dict, filters: dict) -> bool:
    for col, f in filters.items():
        if col == "select":
            continue
        if col == "or":
            if not _or(row, f):
                return False
            continue
        op, _, val = f.partition(".")
        cur = row.get(col)
        if op == "in":
            if str(cur) not in {v.strip('"') for v in val.strip("()").split(",")}:
                return False
        elif op == "ov":
            if not set(cur or []) & {v.strip('"') for v in val.strip("{}").split(",")}:
                return False
        elif not _cond(row, f"{col}.{f}"):
            return False
    return True


class _Store:
    def __init__(self, tables):
        self.tables, self.writes = tables, []

    def __call__(self, name):
        store = self

        class _T:
            def select(self, cols, filters=None, order=None, limit=None, **_):
                rows = [dict(r) for r in store.tables.get(name, []) if _matches(r, filters or {})]
                if order:
                    key, _, way = order.partition(".")
                    rows.sort(key=lambda r: str(r.get(key)), reverse=way == "desc")
                return rows[:limit] if limit else rows

            def update(self, data, filters, *, prefer_return_minimal=False):
                hit = [r for r in store.tables.get(name, []) if _matches(r, filters)]
                store.writes.append((name, dict(data), dict(filters)))
                for r in hit:
                    r.update(data)
                return [] if prefer_return_minimal else [{"id": r["id"]} for r in hit]

        return _T()


def _doc(doc_id, **over):
    return {"id": doc_id, "user_id": "u1", "offering_id": "off-1", "deleted_at": None,
            "shareability": "course_material", "check_items_status": None,
            "check_items_at": None, "created_at": f"2026-11-0{doc_id[-1]}T00:00:00Z", **over}


def test_the_claim_marks_undrafted_course_material_pending_and_the_loop_says_preparing():
    from services import check_item_service as svc

    store = _Store({
        "documents": [
            _doc("d1"),                                       # never drafted
            _doc("d2"),                                       # never drafted, but has items
            _doc("d3", check_items_status="done"),            # drafted
            _doc("d4", shareability="personal_notes"),        # never a source
            _doc("d5", deleted_at="2026-11-10T00:00:00Z"),    # deleted
            _doc("d6", user_id="u2"),                         # a classmate's
            _doc("d7", check_items_status="pending",          # its run died long ago
                 check_items_at="2026-01-01T00:00:00Z"),
            _doc("d8", offering_id="off-other"),              # another course
        ],
        "check_items": [{"id": "i1", "source_document_ids": ["d2"]}],
    })
    asked = []
    with patch.object(svc, "table", store), \
         patch.object(svc, "course_offering_ids", return_value=["off-1"]):
        assert svc.drafting_pending("u1", "c-1") is False
        claimed = svc.claim_undrafted_documents(
            "u1", "c-1", limit=5, may_draft=lambda: asked.append(1) or True)
        assert sorted(claimed) == ["d1", "d7"]
        assert asked == [1]
        status = {d["id"]: d["check_items_status"] for d in store.tables["documents"]}
        assert status == {"d1": "pending", "d2": "done", "d3": "done", "d4": None, "d5": None,
                          "d6": None, "d7": "pending", "d8": None}
        # A128: the student's own fresh `pending` upload is what the loop's
        # "preparing" state reads (services/loop/planning.py::_preparing)
        assert svc.drafting_pending("u1", "c-1") is True
        # a second scan finds nothing left to claim
        assert svc.claim_undrafted_documents("u1", "c-1", limit=5) == []


def test_the_claim_claims_nothing_when_the_budget_says_no():
    from services import check_item_service as svc

    store = _Store({"documents": [_doc("d1")], "check_items": []})
    with patch.object(svc, "table", store), \
         patch.object(svc, "course_offering_ids", return_value=["off-1"]):
        assert svc.claim_undrafted_documents("u1", "c-1", limit=5, may_draft=lambda: False) == []
    assert store.tables["documents"][0]["check_items_status"] is None
    assert store.writes == []


def test_the_claim_is_conditional_so_two_scans_never_claim_one_document():
    from services import check_item_service as svc

    store = _Store({"documents": [_doc("d1")], "check_items": []})

    def racer():  # another replica claims d1 between our read and our write
        store.tables["documents"][0].update(check_items_status="pending",
                                            check_items_at="2099-01-01T00:00:00Z")
        return True

    with patch.object(svc, "table", store), \
         patch.object(svc, "course_offering_ids", return_value=["off-1"]):
        assert svc.claim_undrafted_documents("u1", "c-1", limit=5, may_draft=racer) == []


def test_the_claim_takes_the_newest_documents_first_up_to_its_limit():
    from services import check_item_service as svc

    store = _Store({"documents": [_doc(f"d{i}") for i in range(1, 5)], "check_items": []})
    with patch.object(svc, "table", store), \
         patch.object(svc, "course_offering_ids", return_value=["off-1"]):
        assert sorted(svc.claim_undrafted_documents("u1", "c-1", limit=2)) == ["d3", "d4"]


def test_a_course_with_no_offering_claims_nothing():
    from services import check_item_service as svc

    table = MagicMock()
    with patch.object(svc, "table", table), patch.object(svc, "course_offering_ids", return_value=[]):
        assert svc.claim_undrafted_documents("u1", "c-1", limit=5) == []
    table.assert_not_called()
