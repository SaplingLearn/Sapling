"""#119 / PR #838 review: WHO the per-user LLM budget sees and WHEN it decides.

* attribution — `log_llm_usage` rows with no named user belong to the acting
  user (the request's session user, or the job's `acting_for` user), so the
  upload pipeline, concept scans and vision OCR count toward the budget; the
  PostHog actor fallback stays request-only;
* the job worker — the upload and Gradescope job handlers run as the job's
  user for exactly the handler's duration, and a budget refusal there ends
  the upload with its own code (the stream's budget event, /upload/sync's 429);
* vision OCR — a refusal mid-document propagates (no `continue`) and never
  writes the shared OCR cache;
* one decision per unit of work — continuations (learn.py's textless-turn
  rescue, pydantic-ai's empty-response re-send) and background work (quiz
  submit's context update) are never refused on their own.
"""
from __future__ import annotations

import asyncio
import io
import json
import pickle
import threading
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from services import llm_budget, request_context
from services.llm_budget import LLMBudgetExceeded
from tests.test_llm_budget import (  # noqa: F401  (fixtures: _fresh is autouse)
    RESET,
    USER,
    _counting,
    _fresh,
    _over,
    _ResilientFn,
    session_user,
)
from tests.doc_patches import patch_documents


def _exc():
    return LLMBudgetExceeded(limit=1, used=1, reset_at=RESET, source="default")


@pytest.fixture
def budget(monkeypatch):
    """Script `read_status` (test_llm_budget's `status`): `.value` is the
    BudgetStatus (or exception) to answer; `.calls` lists the users read."""
    box = SimpleNamespace(value=llm_budget.BudgetStatus(
        limit=1000, used=0, source="default", reset_at=RESET), calls=[])

    def fake(user_id, *, timeout=None):
        box.calls.append(user_id)
        if isinstance(box.value, BaseException):
            raise box.value
        return box.value

    monkeypatch.setattr(llm_budget, "read_status", fake)
    return box


# ── the exception ────────────────────────────────────────────────────────


def test_the_budget_error_survives_a_pickle_round_trip():
    err = _exc()
    back = pickle.loads(pickle.dumps(err))
    assert isinstance(back, LLMBudgetExceeded)
    assert (back.limit, back.used, back.reset_at, back.source) == (1, 1, RESET, "default")
    assert back.status_code == 429 and back.detail == err.detail and back.code == err.code
    assert back.headers["Retry-After"]


def test_next_reset_is_the_next_utc_midnight():
    now = datetime(2026, 11, 8, 23, 59, tzinfo=timezone.utc)
    assert llm_budget.next_reset(now) == datetime(2026, 11, 9, tzinfo=timezone.utc)


# ── attribution ──────────────────────────────────────────────────────────


@pytest.fixture
def usage_sink(monkeypatch):
    from services import events_service

    rows, captures = [], []
    monkeypatch.setattr(events_service, "_logging_enabled", lambda: True)
    monkeypatch.setattr(events_service, "_enqueue", lambda t, row: rows.append(row))
    monkeypatch.setattr(events_service.posthog_client, "capture_ai_generation",
                        lambda **kw: captures.append(kw))
    return SimpleNamespace(rows=rows, captures=captures)


def _log(user_id=None):
    from services import events_service

    events_service.log_llm_usage(
        feature="document", task="ocr_vision", model="claude-haiku-5-5",
        usage={"input_tokens": 10, "output_tokens": 5}, user_id=user_id,
    )


def test_unattributed_usage_belongs_to_the_session_user(usage_sink):
    with session_user():
        _log()
    assert usage_sink.rows[-1]["user_id"] == USER
    assert usage_sink.captures[-1]["user_id"] == USER  # what _actor(None) resolved before


def test_unattributed_usage_in_a_job_belongs_to_the_job_user(usage_sink):
    with request_context.acting_for("user_job"):
        _log()
    assert usage_sink.rows[-1]["user_id"] == "user_job"
    assert usage_sink.captures[-1]["user_id"] == "user_job"


def test_a_named_user_wins_and_no_actor_stays_anonymous(usage_sink):
    with session_user():
        _log("user_named")
    _log()
    assert [r["user_id"] for r in usage_sink.rows] == ["user_named", None]


def test_posthog_actor_fallback_stays_request_only():
    """acting_for attributes usage rows; it must NOT turn every personless
    PostHog capture in a job into one attributed to the job's student."""
    from services import posthog_client

    with request_context.acting_for("user_job"):
        assert request_context.current_session_user() is None
        assert request_context.current_acting_user() == "user_job"
        assert posthog_client._actor(None) is None


def test_acting_for_is_reset_on_exit_and_on_error():
    with pytest.raises(RuntimeError):
        with request_context.acting_for("user_job"):
            raise RuntimeError("handler blew up")
    assert request_context.current_acting_user() is None
    with request_context.acting_for(None):
        assert request_context.current_acting_user() is None


def test_acting_for_reaches_threads_and_nested_loops():
    seen = []

    async def inner():
        seen.append(request_context.current_acting_user())

    def in_thread():
        asyncio.run(inner())

    async def outer():
        await asyncio.to_thread(in_thread)

    with request_context.acting_for("user_job"):
        asyncio.run(outer())
    assert seen == ["user_job"]


# ── the job worker ───────────────────────────────────────────────────────


def _queued_row(**over):
    return {"id": "up1", "user_id": "user_job", "request_id": "rid", "stage": "queued",
            "file_data": "enc", "file_name": "a.pdf", "content_type": "application/pdf",
            "course_id": "c1", "offering_id": "o1", **over}


def test_the_upload_job_runs_as_its_user_and_clears_it(monkeypatch):
    from services import document_jobs as dj

    seen = []
    t = MagicMock()
    t.return_value.select.return_value = [_queued_row()]
    monkeypatch.setattr(dj, "table", t)  # the stage swaps report a won row
    monkeypatch.setattr(dj, "_process", lambda row, run: seen.append(
        request_context.current_acting_user()))
    dj._run_document_process_job({"upload_id": "up1"})
    assert seen == ["user_job"]
    assert request_context.current_acting_user() is None

    def boom(row, run):
        raise RuntimeError("worker crash")

    monkeypatch.setattr(dj, "_process", boom)
    with pytest.raises(RuntimeError):
        dj._run_document_process_job({"upload_id": "up1"})
    assert request_context.current_acting_user() is None


def test_the_gradescope_job_runs_as_its_user_and_clears_it(monkeypatch):
    from services import gradescope_jobs as gj

    seen, updates = [], []
    t = MagicMock()
    t.return_value.select.return_value = [{
        "id": "s1", "user_id": "user_gs", "enrollment_id": "e1", "link_id": None,
        "gradescope_course_id": "g1", "stage": "queued",
    }]
    t.return_value.update.side_effect = lambda data, **k: updates.append(data) or [{"id": "s1"}]
    monkeypatch.setattr(gj, "table", t)

    def outcome(row):
        seen.append(request_context.current_acting_user())
        return SimpleNamespace(row_fields=lambda: {"stage": "done"}, error_code=None)

    monkeypatch.setattr(gj, "_worker_outcome", outcome)
    gj._run_gradescope_sync_job({"sync_id": "s1"})
    assert seen == ["user_gs"]
    assert updates[-1] == {"stage": "done"}
    assert request_context.current_acting_user() is None


@pytest.fixture
def pipeline(monkeypatch):
    """`document_jobs._process` with its helpers stubbed; `.failed` records
    the codes it finishes with."""
    from services import document_jobs as dj

    docs = SimpleNamespace(
        _existing_doc_by_request_id=lambda uid, rid: None,
        extract_text_from_file=lambda b, n, c: "x" * 500,
        _has_usable_text=lambda text: True,
    )
    failed = []
    monkeypatch.setattr(dj, "_routes", lambda: docs)
    monkeypatch.setattr(dj, "decrypt_bytes", lambda raw: b"%PDF")
    t = MagicMock()  # the run's fenced stage writes report a won row
    monkeypatch.setattr(dj, "table", t)
    monkeypatch.setattr(dj, "_finish_failed", lambda run, code: failed.append(code))
    run = dj._Run(upload_id="up1", owner="w1#1", stage=dj.EXTRACTING)
    return SimpleNamespace(dj=dj, docs=docs, failed=failed, run=run)


def test_a_budget_refusal_in_the_job_agents_records_its_own_code(pipeline, monkeypatch):
    import agents._run as run_mod

    def refused(coro):
        coro.close()
        raise _exc()

    monkeypatch.setattr(run_mod, "run_agent_sync", refused)
    pipeline.dj._process(_queued_row(), pipeline.run)
    assert pipeline.failed == [pipeline.dj.ERR_BUDGET]


def test_a_budget_refusal_in_the_job_ocr_records_its_own_code(pipeline):
    def refused(*a):
        raise _exc()

    pipeline.docs.extract_text_from_file = refused
    pipeline.dj._process(_queued_row(), pipeline.run)
    assert pipeline.failed == [pipeline.dj.ERR_BUDGET]


def test_the_queued_stream_ends_in_the_budget_event(monkeypatch):
    from services import document_jobs as dj

    monkeypatch.setattr(dj, "read_status",
                        lambda uid: {"stage": "failed", "error_code": dj.ERR_BUDGET, "progress": {}})

    async def collect():
        return [ev async for ev in dj.stream_events("up1", request_id="rid", outcome=dj.Watch())]

    err, done = asyncio.run(collect())
    assert err.type == "error" and "today's limit" in err.message
    assert err.data["code"] == "LLM_BUDGET_EXCEEDED" and err.data["request_id"] == "rid"
    assert err.data["reset_at"] == llm_budget.next_reset().isoformat()
    assert done.type == "status" and done.step == "done"


def test_queued_upload_sync_answers_the_budget_429(monkeypatch):
    from services import document_jobs as dj

    monkeypatch.setattr(dj, "stage_and_enqueue", lambda **kw: "up1")

    async def finished(upload_id, **kw):
        return dj.Watch(kind=dj.FAILED, row={"error_code": dj.ERR_BUDGET})

    monkeypatch.setattr(dj, "wait_for_upload", finished)
    with pytest.raises(LLMBudgetExceeded) as exc:
        asyncio.run(dj.sync_via_queue(user_id="u1"))
    assert exc.value.status_code == 429


def test_the_budget_applies_to_job_work(budget):
    """acting_for budgets the job's model calls like a request's."""
    budget.value = _over()
    fn, calls = _counting()
    with request_context.acting_for(USER), pytest.raises(LLMBudgetExceeded):
        asyncio.run(Agent(_ResilientFn(fn)).run("hi"))
    assert calls["n"] == 0 and budget.calls == [USER]


# ── vision OCR ───────────────────────────────────────────────────────────


def _fake_pdf(pages):
    from tests.test_extraction_service import _fake_pdf as fake

    return fake(pages=pages)


def _vision_env(monkeypatch):
    monkeypatch.setenv("OCR_ENGINE", "docling")
    monkeypatch.setenv("GOT_OCR_ENABLED", "false")
    monkeypatch.setenv("GEMINI_VISION_OCR_ENABLED", "true")
    monkeypatch.delenv("GEMINI_VISION_OCR_MAX_PAGES", raising=False)


def _ocr_run(monkeypatch, vision_side_effect):
    from services.extraction_service import extract_text_from_file

    _vision_env(monkeypatch)
    metadata = {"per_page_markdown": ["", "", ""], "fallback_pages": [0, 1, 2]}
    with (
        patch("services.extraction_service.cache.enabled", return_value=True),
        patch("services.extraction_service.cache.get_str", return_value=None),
        patch("services.extraction_service.cache.set_str") as set_str,
        patch("services.extraction_service.extract_text_from_pdf_native", return_value=("", 3)),
        patch("services.extraction_service.extract_pdf_with_docling",
              return_value=("", 3, metadata)),
        patch("pypdfium2.PdfDocument", return_value=_fake_pdf(3)),
        patch("services.extraction_service.extract_page_with_gemini_vision",
              side_effect=vision_side_effect) as vision,
    ):
        try:
            text = extract_text_from_file(b"%PDF-1.4", "a.pdf", "application/pdf")
        except LLMBudgetExceeded as e:
            text = e
    return text, set_str, vision


def test_a_budget_refusal_mid_document_propagates_and_is_never_cached(monkeypatch):
    out, set_str, vision = _ocr_run(monkeypatch, ["page 0", _exc(), "page 2"])
    assert isinstance(out, LLMBudgetExceeded)
    assert vision.call_count == 2  # stopped at the refusal, no `continue`
    set_str.assert_not_called()


def test_a_page_that_raised_is_not_cached_either(monkeypatch):
    out, set_str, _ = _ocr_run(monkeypatch, ["page 0", RuntimeError("quota"), "page 2"])
    assert "page 0" in out and "page 2" in out  # still a partial document
    set_str.assert_not_called()


def test_a_clean_vision_run_is_cached(monkeypatch):
    out, set_str, _ = _ocr_run(monkeypatch, ["page 0", "page 1", "page 2"])
    assert "page 1" in out
    set_str.assert_called_once()


def test_an_ocr_budget_refusal_is_the_sync_upload_429():
    from tests.test_documents_routes import _make_upload, _mock_validate_user

    with (
        _mock_validate_user(),
        patch_documents("extract_text_from_file", side_effect=_exc()),
        patch_documents("table") as t,
    ):
        t.return_value.select.return_value = []
        r = _make_upload()
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "LLM_BUDGET_EXCEEDED"


def test_an_ocr_budget_refusal_is_the_streamed_upload_terminal_event():
    from fastapi.testclient import TestClient

    from main import app
    from tests.test_documents_routes import _mock_validate_user, _parse_sse_stream

    with (
        _mock_validate_user(),
        patch_documents("OCR_ASYNC_ENABLED", True),
        patch_documents("extract_text_from_file", side_effect=_exc()),
        patch_documents("process_document") as pipeline,
        patch_documents("table") as t,
    ):
        t.return_value.select.return_value = []
        with TestClient(app).stream(
            "POST", "/api/documents/upload",
            files={"file": ("notes.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")},
            data={"course_id": "c-1", "user_id": "u1"},
        ) as r:
            assert r.status_code == 200
            body = r.read()
    events = [(e["event"], json.loads(e["data"])) for e in _parse_sse_stream(body)]
    err = next(d for ev, d in events if ev == "error")
    assert err["data"]["code"] == "LLM_BUDGET_EXCEEDED" and "today's limit" in err["message"]
    assert (events[-1][0], events[-1][1]["step"]) == ("status", "done")
    pipeline.assert_not_called()


# ── one decision per unit of work ────────────────────────────────────────


def test_a_continuation_in_the_same_request_is_not_rechecked(budget):
    """learn.py's textless-turn rescue is a second run with a fresh user
    prompt ("Continue."): it must reuse the turn's decision, not be refused
    half-way through the turn the gate already let start."""
    from routes.learn import _continuation_text

    fn, calls = _counting("rescued")
    agent = Agent(_ResilientFn(fn))
    with session_user():
        first = asyncio.run(agent.run("hi"))
        budget.value = _over()  # spent by the first run
        llm_budget.clear_llm_budget_cache()
        text = asyncio.run(_continuation_text(agent, first, {}))
    assert text == "rescued" and calls["n"] == 2
    assert budget.calls == [USER]  # one read for the whole request


def test_a_refused_request_stays_refused_without_another_read(budget):
    budget.value = _over()
    fn, calls = _counting()
    with session_user():
        for _ in range(2):
            with pytest.raises(LLMBudgetExceeded):
                asyncio.run(Agent(_ResilientFn(fn)).run("hi"))
    assert calls["n"] == 0 and budget.calls == [USER]


def test_the_decision_is_per_user(budget):
    """A decision recorded for one user never answers for another (a job
    scope nested in nothing, then a request for someone else)."""
    fn, _ = _counting()
    with session_user():
        asyncio.run(Agent(_ResilientFn(fn)).run("hi"))
        state = request_context.current_work_state()
        assert state[llm_budget._DECISION_KEY] == (USER, None)
        state["user_id"] = "someone_else"
        asyncio.run(Agent(_ResilientFn(fn)).run("hi"))
    assert budget.calls == [USER, "someone_else"]


def test_the_empty_response_resend_is_not_a_new_run(budget):
    """pydantic-ai re-sends an EMPTY ModelRequest after an empty response. It
    is the same run: never a run start, even with no request state at all."""
    seen = []

    def fn(messages, info):
        seen.append(list(messages))
        if len(seen) == 1:
            budget.value = _over()
            llm_budget.clear_llm_budget_cache()
            return ModelResponse(parts=[])
        return ModelResponse(parts=[TextPart("second try")])

    with session_user():
        assert asyncio.run(Agent(_ResilientFn(fn)).run("hi")).output == "second try"
    assert len(seen) == 2
    assert llm_budget.starts_run(seen[0])
    assert not llm_budget.starts_run(seen[1])
    assert isinstance(seen[1][-1], ModelRequest) and seen[1][-1].parts == []
    # Even outside a request's shared state the heuristic alone holds.
    assert not llm_budget.starts_run(
        [ModelRequest(parts=[UserPromptPart("hi")]), ModelResponse(parts=[]), ModelRequest(parts=[])]
    )
    assert budget.calls == [USER]


def test_background_work_is_never_refused(budget):
    budget.value = _over()
    fn, calls = _counting()
    with session_user(), llm_budget.background_work():
        assert asyncio.run(Agent(_ResilientFn(fn)).run("hi")).output == "ok"
    assert calls["n"] == 1 and budget.calls == []
    with session_user(), pytest.raises(LLMBudgetExceeded):  # foreground still is
        asyncio.run(Agent(_ResilientFn(fn)).run("hi"))


def test_quiz_submit_context_update_never_sees_a_refusal(budget):
    """Quiz submit makes no foreground model call, so its post-response
    context update is the request's FIRST gated run — it must not be the one
    that gets refused (nobody is left to tell, and the adaptive write is lost)."""
    from fastapi.testclient import TestClient

    from main import app
    from tests.test_quiz_context_repair import _submit_factory

    budget.value = _over()
    seen = {}

    async def ctx_run(prompt, *a, **k):
        seen["user"] = request_context.current_acting_user()
        # what the model chokepoint does before the run's first request
        await llm_budget.check_before_request([ModelRequest(parts=[UserPromptPart(prompt)])])
        return SimpleNamespace(output=SimpleNamespace(model_dump=lambda: {}))

    with (
        patch("routes.quiz.table", side_effect=_submit_factory()),
        patch("routes.quiz.quiz_context_agent.run", new=ctx_run),
        patch("routes.quiz.save_quiz_context") as save,
        patch("routes.quiz.record_agent_usage", side_effect=lambda r, **k: r),
        # what auth_guard's stamp on request.state.user_id gives the gate (the
        # hermetic app bypasses the real guard)
        patch("services.request_context.current_session_user", return_value=USER),
    ):
        r = TestClient(app).post("/api/quiz/submit", json={
            "quiz_id": "quiz1", "answers": [{"question_id": 1, "selected_label": "A"}],
        })
        # control: the same check in the foreground IS refused
        with pytest.raises(LLMBudgetExceeded):
            asyncio.run(llm_budget.check_before_request(
                [ModelRequest(parts=[UserPromptPart("x")])]))
    assert r.status_code == 200, r.text
    assert seen["user"] == USER
    save.assert_called_once()


def test_background_work_flag_does_not_leak_to_other_threads():
    out = []
    with llm_budget.background_work():
        t = threading.Thread(target=lambda: out.append(llm_budget._BACKGROUND.get()))
        t.start()
        t.join()
    assert out == [False] and llm_budget._BACKGROUND.get() is False
