"""The `async def` handlers that blocked the event loop with sync PostgREST
calls (#117; docs/design/async-db-client.md §1) no longer do.

Runtime half of design §4.2, end to end: nothing here patches a route's
``table``. Every DB call runs through the REAL ``SupabaseTable`` onto an
``httpx.MockTransport``, so

* the ``no_sync_db_on_loop`` fixture makes ``db.sync_on_loop`` raise -- any
  sync verb reached ON the loop, directly or through a service chain, fails
  the request -- and
* the transport records whether each request left from an event-loop thread.

The five handlers the design measured: ``quiz.generate_quiz``,
``admin_documents.reindex``, ``careers.apply``,
``gradescope.save_credentials_via_bu_sso``, ``profile.upload_user_avatar``;
plus ``extract`` (its limiter becomes a DB call under ``stateless_rate_limit``).
``careers.apply`` and ``profile.upload_user_avatar`` awaited nothing but their
hops, so they are plain ``def`` handlers now (one threadpool hop, by FastAPI);
the rest hop with ``run_in_threadpool`` -- one pool, AnyIO's 40-token limiter.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

import db.async_connection as adb
import db.connection as dbconn
from main import app

client = TestClient(app)


class Wire:
    def __init__(self):
        self.calls: list[tuple[str, str, bool]] = []  # sync client: (method, table, on_loop)
        self.native: list[tuple[str, str]] = []  # the native async client's requests
        self.rows: dict[tuple[str, str], object] = {}

    def _answer(self, request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=self.rows.get((request.method, name), []),
                              headers={"Content-Range": "0-0/1"})

    def handler(self, request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        self.calls.append((request.method, name, asyncio._get_running_loop() is not None))
        return self._answer(request)

    def native_handler(self, request: httpx.Request) -> httpx.Response:
        self.native.append((request.method, request.url.path.rsplit("/", 1)[-1]))
        return self._answer(request)

    def to(self, method: str, name: str) -> list[bool]:
        return [on_loop for m, n, on_loop in self.calls if (m, n) == (method, name)]


@pytest.fixture
def wire(monkeypatch, no_sync_db_on_loop):
    monkeypatch.setattr(dbconn, "REST_URL", "http://supabase.test/rest/v1")
    w = Wire()
    monkeypatch.setattr(dbconn, "_client", httpx.Client(
        transport=httpx.MockTransport(w.handler), headers=dbconn._HEADERS, timeout=30.0))
    native = httpx.MockTransport(w.native_handler)
    monkeypatch.setattr(adb, "_async_client", lambda: httpx.AsyncClient(transport=native))
    yield w
    assert not any(on_loop for _m, _n, on_loop in w.calls), (
        f"sync PostgREST request(s) sent from the event loop: {w.calls}")


def test_handlers_with_nothing_to_await_are_plain_defs():
    import inspect

    import routes.careers as careers
    import routes.profile as profile

    assert not inspect.iscoroutinefunction(careers.apply)
    assert not inspect.iscoroutinefunction(profile.upload_user_avatar)


def test_careers_apply(wire):
    wire.rows[("POST", "job_applications")] = [{"id": "app-1"}]
    r = client.post("/api/careers/apply", data={
        "position": "Engineer", "full_name": "Ada", "email": "ada@example.com",
        "linkedin_url": "https://linkedin.com/in/ada",
    })
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "id": "app-1"}
    assert wire.to("POST", "job_applications") == [False]


def test_careers_apply_with_a_resume_reads_the_spooled_file_off_the_loop(wire, monkeypatch):
    import routes.careers as careers

    wire.rows[("POST", "job_applications")] = [{"id": "app-2"}]
    seen = []

    def _upload(file, content):
        seen.append((content, asyncio._get_running_loop() is not None))
        return "r.pdf"
    monkeypatch.setattr(careers, "_upload_resume", _upload)
    form = {"position": "Engineer", "full_name": "Ada", "email": "ada@example.com",
            "linkedin_url": "https://linkedin.com/in/ada"}
    r = client.post("/api/careers/apply", data=form,
                    files={"resume": ("cv.pdf", b"%PDF-1.4", "application/pdf")})
    assert r.status_code == 200, r.text
    assert seen == [(b"%PDF-1.4", False)]
    big = b"x" * (careers.MAX_RESUME_SIZE + 1)  # the size bound is unchanged
    r = client.post("/api/careers/apply", data=form,
                    files={"resume": ("cv.pdf", big, "application/pdf")})
    assert r.status_code == 413


def test_profile_upload_user_avatar(wire, monkeypatch):
    import routes.profile as profile

    wire.rows[("GET", "users")] = [{"id": "user_andres", "email": None}]
    wire.rows[("GET", "user_profiles")] = [{"user_id": "user_andres"}]
    on_loop = []

    def _upload(user_id, data, content_type):
        on_loop.append(asyncio._get_running_loop() is not None)
        return "https://cdn.test/a.png"
    monkeypatch.setattr(profile, "upload_avatar", _upload)

    import base64
    r = client.post("/api/profile/user_andres/avatar", json={
        "file_b64": base64.b64encode(b"\x89PNG....").decode(), "content_type": "image/png",
    })
    assert r.status_code == 200, r.text
    assert on_loop == [False]  # the Storage PUT left the loop too
    assert wire.to("PATCH", "user_profiles") == [False]


def test_gradescope_bu_sso(wire):
    from services import gradescope_service as gs

    cookies = {"_gradescope_session": "s", "signed_token": "t"}
    with (
        patch.object(gs, "login_via_bu_sso", return_value=cookies),
        patch.object(gs, "login_with_cookies"),
    ):
        r = client.post("/api/gradescope/credentials/bu-sso", json={
            "user_id": "user_andres", "bu_username": "student", "bu_password": "pw",
        })
    assert r.status_code == 200, r.text
    assert wire.to("POST", "gradescope_credentials") == [False]


def test_admin_documents_reindex(wire):
    wire.rows[("GET", "documents")] = [{"id": "doc-1"}]
    outcome = SimpleNamespace(status="indexed", chunk_count=3, error=None)
    with patch("routes.admin_documents.index_document", return_value=outcome):
        r = client.post("/api/admin/documents/doc-1/reindex")
    assert r.status_code == 200, r.text
    assert wire.to("GET", "documents") == [False]


def test_quiz_generate(wire):
    from agents.quiz import Quiz, QuizQuestion

    wire.rows[("GET", "graph_nodes")] = [{
        "id": "node1", "user_id": "user_andres", "course_id": "course1",
        "concept_name": "Loops", "mastery_score": 0.5,
    }]
    wire.rows[("POST", "quiz_attempts")] = [{"id": "quiz-1"}]
    quiz = Quiz(questions=[QuizQuestion(
        question="Q?", type="multiple_choice", difficulty="easy",
        options=["a", "b", "c", "d"], correct_answer="a", explanation="x", concept="Loops",
    )])
    with patch("services.quiz.generation.quiz_agent.run",
               new=AsyncMock(return_value=SimpleNamespace(output=quiz))):
        r = client.post("/api/quiz/generate", json={
            "user_id": "user_andres", "concept_node_id": "node1", "num_questions": 1,
            "difficulty": "easy", "use_shared_context": False,
        })
    assert r.status_code == 200, r.text
    assert wire.to("GET", "graph_nodes") and wire.to("POST", "quiz_attempts") == [False]
    assert wire.to("GET", "llm_usage") == [False]  # the daily spend read


def test_quiz_generate_practise_missed_reads_off_the_loop(wire):
    wire.rows[("GET", "graph_nodes")] = [{"id": "node1", "user_id": "user_andres"}]
    wire.rows[("GET", "quiz_attempts")] = [{
        "id": "src", "user_id": "user_andres", "concept_node_id": "node1",
        "completed_at": "2026-11-01T00:00:00+00:00", "questions_json": None,
        "score": 0, "total": 1,
    }]
    with patch("services.quiz.generation.quiz_agent.run", new=AsyncMock(side_effect=RuntimeError("no model"))):
        client.post("/api/quiz/generate", json={
            "user_id": "user_andres", "concept_node_id": "node1", "num_questions": 1,
            "difficulty": "easy", "source_attempt_id": "src",
        })
    assert wire.to("GET", "quiz_attempts") and not any(wire.to("GET", "quiz_attempts"))
    assert wire.to("GET", "quiz_responses") == [False]


def test_extract_rate_limit_runs_off_the_loop(wire, monkeypatch):
    """With `stateless_rate_limit` on, the OCR limiter is an rpc; it must not
    run on the loop (the session check beside it can read the account too)."""
    monkeypatch.setenv("SAPLING_FLAG_STATELESS_RATE_LIMIT", "on")
    wire.rows[("POST", "claim_rate_limit")] = [{"hit_id": 7, "retry_after": None}]
    r = client.post("/api/extract/image", files={"file": ("a.gif", b"GIF8", "image/gif")})
    assert r.status_code == 400  # unsupported type: after the limiter ran
    assert wire.to("POST", "claim_rate_limit") == [False]


def test_the_fixture_would_catch_a_regression(wire, monkeypatch):
    """Sanity: put a sync read back on the loop and the request fails."""
    import routes.careers as careers

    async def _blocking_apply(**_kw):
        careers.table("job_applications").select("id")
        return {}

    with pytest.raises(adb.SyncDbOnLoop):
        asyncio.run(_blocking_apply())


# ── The first router read converted end to end (design §4.1, wave 2) ───────


@pytest.mark.parametrize("async_mode", ["off", "on"])
def test_quiz_list_attempts_on_the_async_seam(wire, monkeypatch, async_mode):
    monkeypatch.setenv("SAPLING_FLAG_ASYNC_DB_CLIENT", async_mode)
    wire.rows[("GET", "quiz_attempts")] = [{
        "id": "q1", "concept_node_id": "node1", "difficulty": "easy", "score": 1,
        "total": 2, "mastery_before": 0.5, "mastery_after": 0.6,
        "completed_at": None, "abandoned_at": None,
        "created_at": "2099-01-01T00:00:00+00:00",
    }]
    wire.rows[("GET", "graph_nodes")] = [
        {"id": "node1", "concept_name": "Loops", "course_id": "c1"}]
    wire.rows[("GET", "quiz_responses")] = [
        {"attempt_id": "q1", "answered_at": "2099-01-01T00:01:00+00:00"}]

    r = client.get("/api/quiz/attempts", params={"user_id": "user_andres"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    (attempt,) = body["attempts"]
    assert attempt["concept_name"] == "Loops" and attempt["status"] == "in_progress"
    # learning-loop PKG-14b: the per-attempt delta is p_after - p_before
    assert attempt["p_delta"] == 0.1

    reads = {("GET", "quiz_attempts"), ("GET", "graph_nodes"), ("GET", "quiz_responses")}
    if async_mode == "on":
        # The three handler reads went native, from the loop; only the sweep
        # (a sync service: its own reads + the conditional PATCH) used the
        # sync client, on a worker thread.
        assert reads <= set(wire.native)
        assert {(m, n) for m, n, _ in wire.calls} <= reads | {("PATCH", "quiz_attempts")}
        assert ("GET", "graph_nodes") not in {(m, n) for m, n, _ in wire.calls}
    else:
        assert wire.native == []
        assert reads <= {(m, n) for m, n, _ in wire.calls}
