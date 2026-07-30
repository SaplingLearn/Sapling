"""Seam tests for issue #117 — observability event capture.

Every instrumented seam (middleware errors, auth denials, logins, documents,
quiz, chat, sessions, notes) must emit exactly the pinned taxonomy through
``services.events_service.log_event``, with privacy-safe payloads (paths not
URLs, fingerprints not content, counts not text), and a failing events
pipeline must never break the route being observed.

Patterns follow tests/test_events_service.py (the `sink` fixture +
`flush_now()` for deterministic draining — the worker thread never runs here)
and lean on conftest's autouse fixtures: `_reset_events_service` clears the
queue between tests, `_bypass_session_auth` stubs the auth guard (the real
functions stay reachable via the `auth_guard._real_*` stash), and the
hermetic Supabase/LLM guards keep everything offline.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from main import app
from services import events_service

client = TestClient(app)


# ── Sink plumbing (mirrors tests/test_events_service.py) ─────────────────────


class _FakeTable:
    def __init__(self, name: str, sink: list):
        self.name = name
        self.sink = sink

    def insert(self, rows):
        self.sink.append((self.name, rows))
        return rows if isinstance(rows, list) else [rows]


@pytest.fixture
def sink(monkeypatch):
    rows: list = []
    monkeypatch.setattr(
        events_service, "table", lambda name: _FakeTable(name, rows)
    )
    return rows


def _events(sink) -> list[dict]:
    """Drain the queue synchronously and return the `events`-table rows."""
    events_service.flush_now()
    return [row for name, rows in sink for row in rows if name == "events"]


def _of_type(sink, event_type: str) -> list[dict]:
    return [e for e in _events(sink) if e["event_type"] == event_type]


def _make_request(path: str = "/api/thing", query: str = "") -> Request:
    """Bare starlette Request for calling the real auth-guard functions.

    conftest's `_decode_session` stub resolves the session user from the
    `user_id` query param (default "user_andres")."""
    return Request({
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "headers": [],
        "path_params": {},
    })


# ── Taxonomy pin ─────────────────────────────────────────────────────────────


def test_event_taxonomy_is_pinned_to_twelve_names():
    """Shared constant so a rename breaks loudly — every seam below asserts
    its exact event name, and this pins the full set in one place."""
    assert events_service.EVENT_TAXONOMY == frozenset({
        "error.4xx",
        "error.5xx",
        "auth.login",
        "auth.permission_denied",
        "document.upload",
        "document.processed",
        "quiz.started",
        "quiz.completed",
        "chat.message_sent",
        "note.created",
        "session.started",
        "session.ended",
    })


# ── Middleware: error.4xx / error.5xx ────────────────────────────────────────


def _mini_app() -> FastAPI:
    """Dedicated app so route templates / forced 500s / state propagation can
    be exercised without mutating the shared `main.app` router."""
    from services.request_context import RequestIDMiddleware

    mini = FastAPI()

    @mini.get("/items/{item_id}")
    def _item(item_id: str):
        raise HTTPException(status_code=404, detail="nope")

    @mini.get("/boom")
    def _boom():
        raise HTTPException(status_code=500, detail="boom")

    @mini.get("/authed-then-404")
    def _authed(request: Request):
        # Simulates what the real get_session_user_id does on a successful
        # decode (see test_get_session_user_id_stamps_request_state).
        request.state.user_id = "user-from-state"
        raise HTTPException(status_code=404, detail="nope")

    @mini.get("/ok")
    def _ok():
        return {"ok": True}

    @mini.get("/crash")
    def _crash():
        # A TRULY unhandled exception — no HTTPException, no app-level
        # handler on this mini app — so it propagates THROUGH the
        # middleware's dispatch toward ServerErrorMiddleware.
        raise ValueError("unhandled crash")

    mini.add_middleware(RequestIDMiddleware)
    return mini


def test_health_emits_zero_events(sink):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert _events(sink) == []


def test_2xx_and_3xx_emit_zero_events(sink):
    mini_client = TestClient(_mini_app())
    assert mini_client.get("/ok").status_code == 200
    assert _events(sink) == []


def test_unmatched_404_emits_single_error_4xx_with_payload(sink):
    r = client.get("/api/definitely-not-a-route")
    assert r.status_code == 404
    events = _events(sink)
    assert len(events) == 1
    ev = events[0]
    assert ev["event_type"] == "error.4xx"
    assert ev["category"] == "error"
    payload = ev["payload"]
    assert payload["path"] == "/api/definitely-not-a-route"
    assert payload["method"] == "GET"
    assert payload["status_code"] == 404
    assert isinstance(payload["duration_ms"], (int, float))
    # No route matched -> no template to record.
    assert "route" not in payload
    # The contextvar was already reset when the event fires; the middleware
    # must pass the request id explicitly.
    assert ev["request_id"] == r.headers["X-Request-ID"]


def test_error_event_records_path_never_query_string(sink):
    r = client.get("/api/definitely-not-a-route?q=super-secret-search-term")
    assert r.status_code == 404
    events = _events(sink)
    assert len(events) == 1
    assert events[0]["payload"]["path"] == "/api/definitely-not-a-route"
    assert "super-secret-search-term" not in str(events[0])


def test_matched_route_404_carries_route_template(sink):
    mini_client = TestClient(_mini_app())
    r = mini_client.get("/items/abc-123")
    assert r.status_code == 404
    events = _events(sink)
    assert len(events) == 1
    assert events[0]["event_type"] == "error.4xx"
    assert events[0]["payload"]["route"] == "/items/{item_id}"
    # The raw path is still recorded alongside the bounded-cardinality template.
    assert events[0]["payload"]["path"] == "/items/abc-123"


def test_500_emits_single_error_5xx(sink):
    mini_client = TestClient(_mini_app())
    r = mini_client.get("/boom")
    assert r.status_code == 500
    events = _events(sink)
    assert len(events) == 1
    ev = events[0]
    assert ev["event_type"] == "error.5xx"
    assert ev["category"] == "error"
    assert ev["payload"]["status_code"] == 500
    assert ev["payload"]["path"] == "/boom"
    assert ev["payload"]["method"] == "GET"
    assert isinstance(ev["payload"]["duration_ms"], (int, float))


def test_error_event_carries_user_id_from_request_state(sink):
    mini_client = TestClient(_mini_app())
    r = mini_client.get("/authed-then-404")
    assert r.status_code == 404
    events = _events(sink)
    assert len(events) == 1
    assert events[0]["user_id"] == "user-from-state"


# ── Seam 1b: get_session_user_id stamps request.state.user_id ────────────────


def test_get_session_user_id_stamps_request_state(sink):
    from services import auth_guard

    req = _make_request("/api/whatever", query="user_id=user_xyz")
    uid = auth_guard._real_get_session_user_id(req)
    assert uid == "user_xyz"
    # request.state is backed by the ASGI scope, which is the only thing
    # shared with BaseHTTPMiddleware's dispatch — a contextvar set here
    # would not propagate back out of the downstream anyio task.
    assert req.state.user_id == "user_xyz"
    # A successful decode is not an event (auth.login fires at mint sites).
    assert _events(sink) == []


# ── Auth denials: auth.permission_denied ─────────────────────────────────────


def test_require_self_mismatch_emits_permission_denied(sink):
    from services import auth_guard

    req = _make_request("/api/notes")  # stub session -> "user_andres"
    with pytest.raises(HTTPException) as exc:
        auth_guard._real_require_self("someone_else", req)
    assert exc.value.status_code == 403
    events = _events(sink)
    assert len(events) == 1
    ev = events[0]
    assert ev["event_type"] == "auth.permission_denied"
    assert ev["category"] == "audit"
    assert ev["user_id"] == "user_andres"
    assert ev["payload"] == {"reason": "not_self", "route": "/api/notes"}


def test_require_self_match_emits_nothing(sink):
    from services import auth_guard

    req = _make_request("/api/notes")
    auth_guard._real_require_self("user_andres", req)
    assert _events(sink) == []


def test_require_admin_denial_emits_permission_denied(sink):
    from services import auth_guard

    # Hermetic Supabase client returns no user_roles rows -> not admin.
    req = _make_request("/api/admin/analytics/usage/summary")
    with pytest.raises(HTTPException) as exc:
        auth_guard._real_require_admin(req)
    assert exc.value.status_code == 403
    events = _events(sink)
    assert len(events) == 1
    ev = events[0]
    assert ev["event_type"] == "auth.permission_denied"
    assert ev["category"] == "audit"
    assert ev["user_id"] == "user_andres"
    assert ev["payload"] == {
        "reason": "not_admin",
        "route": "/api/admin/analytics/usage/summary",
    }


def test_require_role_denial_emits_permission_denied_with_slug(sink):
    from services import auth_guard

    req = _make_request("/api/librarian-things")
    checker = auth_guard._real_require_role("librarian")
    with pytest.raises(HTTPException) as exc:
        checker(req)
    assert exc.value.status_code == 403
    events = _events(sink)
    assert len(events) == 1
    assert events[0]["event_type"] == "auth.permission_denied"
    assert events[0]["payload"] == {
        "reason": "missing_role:librarian",
        "route": "/api/librarian-things",
    }


def test_401_decode_failure_emits_nothing(sink, monkeypatch):
    """The 401 paths are deliberately NOT instrumented — the middleware's
    error.4xx already covers them; a second emission would double-count in
    /usage/summary."""
    from services import auth_guard

    monkeypatch.setattr(
        auth_guard, "_decode_session", auth_guard._real_decode_session
    )
    req = _make_request("/api/thing")  # no cookie, no auth_token
    with pytest.raises(HTTPException) as exc:
        auth_guard._real_get_session_user_id(req)
    assert exc.value.status_code == 401
    assert _events(sink) == []


# ── auth.login ───────────────────────────────────────────────────────────────


def test_test_login_emits_auth_login(sink, monkeypatch):
    import config
    from services import auth_guard

    secret = "event-seam-session-secret-at-least-32-bytes"
    monkeypatch.setattr(config, "SESSION_SECRET", secret)
    monkeypatch.setattr(config, "SECURE_COOKIES", False)
    monkeypatch.setattr(auth_guard, "SESSION_SECRET", secret)

    r = client.post("/api/auth/test-login", json={"user_id": "rich-user-1"})
    assert r.status_code == 200
    events = _of_type(sink, "auth.login")
    assert len(events) == 1
    ev = events[0]
    assert ev["category"] == "audit"
    assert ev["user_id"] == "rich-user-1"
    assert ev["payload"] == {"method": "test_login"}


def test_google_callback_source_emits_auth_login():
    """google_callback cannot be driven hermetically (real OAuth exchange +
    signed state cookie), so pin the emission's presence in the source as a
    loud tripwire instead of leaving the seam untested."""
    import inspect

    import routes.auth as auth_routes

    src = inspect.getsource(auth_routes.google_callback)
    assert "auth.login" in src
    assert '"method": "google"' in src


# ── Documents: document.upload + document.processed ──────────────────────────


def _doc_result(category="lecture_notes"):
    from agents.classifier import DocumentClassification
    from agents.concept_extraction import Concept, ConceptList
    from agents.document import DocumentProcessingResult
    from agents.summary import Summary

    return DocumentProcessingResult(
        classification=DocumentClassification(
            category=category, is_syllabus=False, confidence=0.9, rationale="t",
        ),
        summary=Summary(
            headline="h", abstract="SECRET-SUMMARY-ABSTRACT",
            key_points=["k1", "k2", "k3"],
        ),
        concepts=ConceptList(
            concepts=[Concept(name="C", description="d", importance=0.5)],
        ),
        syllabus=None,
        graph_updated=True,  # skip the graph backstop
    )


_DOC_TEXT = (
    "document body. This sample gives the upload fixture enough extracted "
    "text to look like a document that was actually read successfully."
)


def _upload_sync():
    import io

    return client.post(
        "/api/documents/upload/sync",
        files={"file": ("notes.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")},
        data={"course_id": "c1", "user_id": "user_andres"},
    )


def test_upload_sync_emits_upload_and_processed(sink):
    with (
        patch("routes.documents._validate_user", return_value=None),
        patch("routes.documents.resolve_offering", return_value="off-1"),
        patch("routes.documents.extract_text_from_file", return_value=_DOC_TEXT),
        patch("routes.documents.process_document", return_value=_doc_result()),
        patch("routes.documents.table") as t,
    ):
        t.return_value.select.return_value = []  # no idempotent replay hit
        t.return_value.insert.return_value = [{"id": "doc-1"}]
        r = _upload_sync()
    assert r.status_code == 200

    uploads = _of_type(sink, "document.upload")
    assert len(uploads) == 1
    up = uploads[0]
    assert up["category"] == "usage"
    assert up["user_id"] == "user_andres"
    assert up["payload"] == {
        "course_id": "c1",
        "offering_id": "off-1",
        "char_count": len(_DOC_TEXT),
    }

    processed = _of_type(sink, "document.processed")
    assert len(processed) == 1
    pr = processed[0]
    assert pr["category"] == "usage"
    assert pr["user_id"] == "user_andres"
    assert pr["payload"] == {
        "document_id": "doc-1",
        "category": "lecture_notes",
        "course_id": "c1",
        "char_count": len(_DOC_TEXT),
    }
    # Never text / summary / concept_notes in the payload.
    assert "SECRET-SUMMARY-ABSTRACT" not in str(uploads + processed)
    assert _DOC_TEXT[:40] not in str(uploads + processed)


def test_legacy_upload_pipeline_emits_processed(sink):
    """ADR-0001 fallback uploads must emit document.processed too (D6)."""
    legacy_ai = {
        "category": "lecture_notes",
        "summary": "legacy summary",
        "concept_notes": [],
        "concepts": [],
        "assignments": [],
        "categories": [],
    }
    with (
        patch("routes.documents._validate_user", return_value=None),
        patch("routes.documents.resolve_offering", return_value="off-1"),
        patch("routes.documents.extract_text_from_file", return_value=_DOC_TEXT),
        patch(
            "routes.documents.process_document",
            side_effect=RuntimeError("force legacy fallback"),
        ),
        patch("routes.documents._process_document", return_value=legacy_ai),
        patch("routes.documents.table") as t,
    ):
        t.return_value.select.return_value = []
        t.return_value.insert.return_value = [{"id": "doc-legacy-1"}]
        r = _upload_sync()
    assert r.status_code == 200

    processed = _of_type(sink, "document.processed")
    assert len(processed) == 1
    assert processed[0]["payload"] == {
        "document_id": "doc-legacy-1",
        "category": "lecture_notes",
        "course_id": "c1",
        "char_count": len(_DOC_TEXT),
    }
    assert "legacy summary" not in str(processed)


# ── Quiz: quiz.started + quiz.completed ──────────────────────────────────────


def _quiz_node_row():
    return {
        "id": "node1",
        "user_id": "user_andres",
        "course_id": "course1",
        "concept_name": "Loops",
        "mastery_score": 0.5,
        "times_studied": 2,
    }


def test_quiz_generate_emits_quiz_started(sink):
    from agents.quiz import Quiz, QuizQuestion

    fake_quiz = Quiz(questions=[
        QuizQuestion(
            question="Q?", type="multiple_choice", difficulty="hard",
            options=["a", "b", "c", "d"], correct_answer="a",
            explanation="x", concept="X",
        ),
    ])

    def factory(name):
        mock = MagicMock()
        if name == "graph_nodes":
            mock.select.return_value = [_quiz_node_row()]
        else:
            mock.select.return_value = []
        mock.insert.return_value = []
        return mock

    with (
        patch("routes.quiz.table", side_effect=factory),
        patch(
            "routes.quiz.quiz_agent.run",
            new=AsyncMock(return_value=SimpleNamespace(output=fake_quiz)),
        ),
    ):
        r = client.post("/api/quiz/generate", json={
            "user_id": "user_andres",
            "concept_node_id": "node1",
            "num_questions": 1,
            "difficulty": "hard",
            "use_shared_context": False,
        })
    assert r.status_code == 200
    quiz_id = r.json()["quiz_id"]

    events = _of_type(sink, "quiz.started")
    assert len(events) == 1
    ev = events[0]
    assert ev["category"] == "usage"
    assert ev["user_id"] == "user_andres"
    assert ev["request_id"] is not None
    assert ev["payload"] == {
        "quiz_id": quiz_id,
        "concept_node_id": "node1",
        "num_questions": 1,
        "difficulty": "hard",
    }


SAMPLE_QUESTIONS = [
    {
        "id": 1,
        "text": "What does a for-loop do?",
        "options": [
            {"label": "A", "correct": True},
            {"label": "B", "correct": False},
        ],
        "explanation": "A is correct.",
    },
    {
        "id": 2,
        "text": "What is a function?",
        "options": [
            {"label": "C", "correct": False},
            {"label": "D", "correct": True},
        ],
        "explanation": "D is correct.",
    },
]


def test_quiz_submit_emits_quiz_completed_on_success(sink):
    def factory(name):
        mock = MagicMock()
        if name == "quiz_attempts":
            mock.select.return_value = [{
                "id": "quiz1",
                "user_id": "user_andres",
                "concept_node_id": "node1",
                "difficulty": "medium",
                "questions_json": SAMPLE_QUESTIONS,
            }]
        elif name == "graph_nodes":
            mock.select.return_value = [_quiz_node_row()]
        else:
            mock.select.return_value = []
        mock.update.return_value = [{"id": "updated"}]
        return mock

    noop_ctx = AsyncMock(
        return_value=SimpleNamespace(output=SimpleNamespace(model_dump=lambda: {}))
    )
    with (
        patch("routes.quiz.table", side_effect=factory),
        patch("routes.quiz.apply_graph_update"),
        patch("routes.quiz.get_quiz_context", return_value={}),
        patch("routes.quiz.quiz_context_agent.run", new=noop_ctx),
        patch("routes.quiz.save_quiz_context"),
        patch("routes.quiz.get_display_name", return_value="Andres"),
    ):
        r = client.post("/api/quiz/submit", json={
            "quiz_id": "quiz1",
            "user_id": "user_andres",
            "answers": [
                {"question_id": "1", "selected_label": "A"},
                {"question_id": "2", "selected_label": "D"},
            ],
        })
    assert r.status_code == 200

    events = _of_type(sink, "quiz.completed")
    assert len(events) == 1
    ev = events[0]
    assert ev["category"] == "usage"
    assert ev["user_id"] == "user_andres"
    payload = ev["payload"]
    assert payload["quiz_id"] == "quiz1"
    assert payload["concept_node_id"] == "node1"
    assert payload["score"] == 2
    assert payload["total"] == 2
    # mastery 0.5 -> 0.5 + 2*0.03 = 0.56
    assert payload["mastery_delta"] == pytest.approx(0.06)


# ── Chat: chat.message_sent ──────────────────────────────────────────────────


def _learn_table_factory(offering_id="off1"):
    def factory(name):
        mock = MagicMock()
        if name == "sessions":
            mock.select.return_value = [{"offering_id": offering_id}]
        else:
            mock.select.return_value = []
        mock.update.return_value = []
        mock.insert.return_value = []
        return mock

    return factory


SECRET_MESSAGE = "my very private question about recursion and my grades"


def test_chat_json_emits_message_sent_with_fingerprint(sink):
    agent = MagicMock()
    agent.run = AsyncMock(return_value=SimpleNamespace(output="A reply."))
    with (
        patch("routes.learn.table", side_effect=_learn_table_factory()),
        patch("routes.learn.agent_for_mode", return_value=agent),
        patch("routes.learn.apply_graph_update"),
    ):
        r = client.post("/api/learn/chat", json={
            "session_id": "s1",
            "user_id": "user_andres",
            "message": SECRET_MESSAGE,
            "mode": "socratic",
            "use_shared_context": False,
        })
    assert r.status_code == 200

    events = _of_type(sink, "chat.message_sent")
    assert len(events) == 1
    ev = events[0]
    assert ev["category"] == "usage"
    assert ev["user_id"] == "user_andres"
    assert ev["payload"] == {"mode": "socratic", "session_id": "s1"}
    assert ev["request_id"] == r.headers["X-Request-ID"]
    # Content is fingerprinted; the raw message never lands anywhere.
    assert ev["content_fp"] is not None
    assert len(ev["content_fp"]) == 16
    assert SECRET_MESSAGE not in str(ev)


def test_chat_stream_emits_message_sent_with_explicit_request_id(sink):
    async def fake_stream(**kwargs):
        from services.agent_events import SaplingEvent

        yield SaplingEvent(type="status", step="start", message="Starting.")
        kwargs["on_complete"]("Hi", {}, [])
        yield SaplingEvent(
            type="done", step="reply", message="Complete.",
            data={"reply": "Hi", "graph_update": {}, "mastery_changes": []},
        )

    with (
        patch("routes.learn.stream_agent_turn", fake_stream),
        patch(
            "routes.learn._prepare_chat_run",
            return_value=(MagicMock(), "msg", {}, MagicMock()),
        ),
        patch("routes.learn._consume_pending"),
        patch("routes.learn._get_session_offering_id", return_value="off-1"),
        patch("routes.learn.offering_course_id", return_value="c1"),
        patch("routes.learn._load_message_history", return_value=[]),
        patch("routes.learn.save_message"),
    ):
        r = client.post("/api/learn/chat/stream", json={
            "session_id": "s1",
            "user_id": "user_andres",
            "message": SECRET_MESSAGE,
            "mode": "socratic",
        })
    assert r.status_code == 200

    events = _of_type(sink, "chat.message_sent")
    assert len(events) == 1
    ev = events[0]
    assert ev["category"] == "usage"
    assert ev["payload"] == {"mode": "socratic", "session_id": "s1"}
    # The on_complete hook runs outside the request contextvar scope; the
    # route must thread its request_id through explicitly.
    assert ev["request_id"] == r.headers["X-Request-ID"]
    assert ev["content_fp"] is not None
    assert SECRET_MESSAGE not in str(ev)


# ── Sessions: session.started + session.ended ────────────────────────────────


def test_consume_pending_emits_session_started(sink):
    import routes.learn as learn

    learn.PENDING_SESSIONS["sess-p1"] = {
        "user_id": "u1",
        "mode": "socratic",
        "topic": "Extremely Private Topic",
        "offering_id": "off-9",
        "assistant_reply": "hello",
        "graph_update": {},
    }
    with patch("routes.learn.table"):
        learn._consume_pending("sess-p1", "u1")

    events = _of_type(sink, "session.started")
    assert len(events) == 1
    ev = events[0]
    assert ev["category"] == "usage"
    assert ev["user_id"] == "u1"
    assert ev["payload"] == {
        "session_id": "sess-p1",
        "mode": "socratic",
        "offering_id": "off-9",
    }
    # Topic is fingerprinted (content=), never stored in the payload.
    assert ev["content_fp"] is not None
    assert "Extremely Private Topic" not in str(ev)


def test_end_session_pending_early_return_emits_nothing(sink):
    import routes.learn as learn

    learn.PENDING_SESSIONS["sess-p2"] = {
        "user_id": "user_andres",
        "mode": "socratic",
        "topic": "T",
        "offering_id": None,
        "assistant_reply": "hi",
        "graph_update": {},
    }
    r = client.post("/api/learn/end-session", json={
        "session_id": "sess-p2", "user_id": "user_andres",
    })
    assert r.status_code == 200
    assert _events(sink) == []


def test_end_session_emits_session_ended(sink):
    # Naive-UTC isoformat, matching what the route stores (it subtracts this
    # from a naive utcnow); datetime.utcnow() itself is deprecated — don't copy it.
    started_at = (
        datetime.now(timezone.utc).replace(tzinfo=None)
        - timedelta(minutes=30, seconds=5)
    ).isoformat()

    def factory(name):
        mock = MagicMock()
        if name == "sessions":
            mock.select.return_value = [
                {"user_id": "user_andres", "started_at": started_at},
            ]
        elif name == "messages":
            mock.select.return_value = [
                {"graph_update_json": {
                    "updated_nodes": [{"concept_name": "A"}],
                    "new_nodes": [{"concept_name": "B"}],
                }},
                {"graph_update_json": None},
            ]
        else:
            mock.select.return_value = []
        mock.update.return_value = []
        return mock

    with patch("routes.learn.table", side_effect=factory):
        r = client.post("/api/learn/end-session", json={
            "session_id": "s-ended", "user_id": "user_andres",
        })
    assert r.status_code == 200

    events = _of_type(sink, "session.ended")
    assert len(events) == 1
    ev = events[0]
    assert ev["category"] == "usage"
    assert ev["user_id"] == "user_andres"
    assert ev["payload"] == {
        "session_id": "s-ended",
        "time_spent_minutes": 30,
        "concepts_covered": 2,
    }


# ── Notes: note.created ──────────────────────────────────────────────────────


def test_create_note_emits_note_created(sink):
    async def fake_create(user_id, offering_id, title, body, tags):
        return {
            "id": "n1", "user_id": user_id, "offering_id": offering_id,
            "title": title, "body": body, "tags": tags,
            "last_summary": None, "last_summary_at": None,
            "created_at": "", "updated_at": "",
        }

    with (
        patch("routes.notes.resolve_offering", return_value="off1"),
        patch("routes.notes.create_note", side_effect=fake_create),
    ):
        r = client.post("/api/notes", json={
            "user_id": "user_andres",
            "course_id": "c1",
            "title": "Secret Note Title",
            "body": "Secret note body text",
        })
    assert r.status_code == 200

    events = _of_type(sink, "note.created")
    assert len(events) == 1
    ev = events[0]
    assert ev["category"] == "usage"
    assert ev["user_id"] == "user_andres"
    assert ev["payload"] == {
        "note_id": "n1",
        "course_id": "c1",
        "offering_id": "off1",
        "has_body": True,
    }
    assert "Secret Note Title" not in str(ev)
    assert "Secret note body" not in str(ev)


# ── Failure isolation ────────────────────────────────────────────────────────


def test_route_survives_events_pipeline_internal_failure(monkeypatch):
    """D4: call sites are NOT wrapped in try/except because log_event itself
    cannot raise. Prove that end-to-end: blow up log_event's internals
    (_enqueue) and the instrumented route must still answer 200."""

    def _boom(*_a, **_k):
        raise RuntimeError("observability pipeline down")

    monkeypatch.setattr(events_service, "_enqueue", _boom)

    async def fake_create(user_id, offering_id, title, body, tags):
        return {"id": "n1", "user_id": user_id, "offering_id": offering_id,
                "title": title, "body": body, "tags": tags,
                "last_summary": None, "last_summary_at": None,
                "created_at": "", "updated_at": ""}

    with (
        patch("routes.notes.resolve_offering", return_value="off1"),
        patch("routes.notes.create_note", side_effect=fake_create),
    ):
        r = client.post("/api/notes", json={
            "user_id": "user_andres", "course_id": "c1",
            "title": "t", "body": "b",
        })
    assert r.status_code == 200
    assert r.json()["id"] == "n1"


def test_unhandled_exception_emits_exactly_one_error_5xx(sink):
    """A crash that never becomes a response object must STILL land in the
    errors rollup — the exception propagates through dispatch (no response
    reaches the >=400 seam), so the except-path emission is the only shot.
    Empirically verified gap from the #117 implementation pass."""
    import pytest as _pytest

    mini_client = TestClient(_mini_app())
    with _pytest.raises(ValueError):
        # TestClient re-raises server exceptions by default — exactly what a
        # truly unhandled crash does; the middleware must have emitted first.
        mini_client.get("/crash")

    events = _events(sink)
    assert len(events) == 1
    ev = events[0]
    assert ev["event_type"] == "error.5xx"
    assert ev["payload"]["path"] == "/crash"
    assert ev["payload"]["method"] == "GET"
    assert ev["payload"]["status_code"] == 500
    assert isinstance(ev["payload"]["duration_ms"], (int, float))
    assert ev["payload"]["route"] == "/crash"
    assert ev["request_id"]
