"""XP is awarded from the routes that earn it, and never breaks them.

The route-level tests below close a gap the plain unit tests above don't
cover: tests/conftest.py's autouse `_hermetic_supabase_client` makes every
unmocked `db.connection` call return `[]`, so `services.xp_service.table`
(a *separate* name binding from each route module's own
`from db.connection import table`) silently no-ops through `_rule_amount`
returning 0 whenever a route test doesn't explicitly stub it. That means the
190 pre-existing route tests prove the four award call sites don't raise —
not that they pass the *right* rule_key/source_type/source_id. These tests
patch `services.xp_service.table` directly (an enabled xp_rules row + a
capturable xp_events.insert) and assert the exact payload each route sends,
so a typo'd rule_key or a swapped source_id fails loudly.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import io

from fastapi.testclient import TestClient

from main import app
from services.xp_service import idempotency_key

client = TestClient(app)


class TestIdempotencyKeys:
    def test_quiz_key_is_scoped_to_the_attempt(self):
        assert idempotency_key("quiz_completed", "quiz", "attempt-1") == \
               "quiz_completed:quiz:attempt-1"

    def test_document_key_is_scoped_to_the_document(self):
        assert idempotency_key("document_uploaded", "document", "doc-1") == \
               "document_uploaded:document:doc-1"


class TestSafety:
    def test_a_broken_ledger_does_not_raise(self):
        with patch("services.xp_service.table", side_effect=RuntimeError("db down")):
            from services.xp_service import award_xp_safe
            assert award_xp_safe("u1", "quiz_completed",
                                 source_type="quiz", source_id="q1") is None


# ── shared xp_service.table stub ─────────────────────────────────────────────

def _xp_tables(rule_key: str, amount: int = 10):
    """A `services.xp_service.table` stub with one enabled xp_rules row and a
    capturable xp_events.insert, so a route test can assert the exact award
    payload instead of only that the call didn't raise."""
    handles = {
        "xp_rules": MagicMock(),
        "xp_events": MagicMock(),
        "users": MagicMock(),
    }
    handles["xp_rules"].select.return_value = [
        {"key": rule_key, "amount": amount, "enabled": True}
    ]
    events: list[dict] = []

    def _insert(data):
        events.append({"amount": data["amount"]})
        return [data]

    handles["xp_events"].insert.side_effect = _insert
    # award_xp recomputes users.total_xp by summing the ledger, so xp_events
    # needs a real select_with_count. Leaving it a bare MagicMock would make
    # the unpack raise *after* the insert these tests assert on — invisible
    # here, but it would mean the route tests stopped exercising the tail of
    # award_xp at all.
    handles["xp_events"].select_with_count.side_effect = \
        lambda *a, **k: (list(events), len(events))
    handles["users"].select.return_value = [{"total_xp": 0, "level": 1}]
    handles["users"].update.return_value = []
    return (lambda name: handles[name]), handles


# ── POST /api/quiz/submit → quiz_completed ───────────────────────────────────

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


def _quiz_table_factory(quiz_id: str, user_id: str):
    def factory(name):
        mock = MagicMock()
        if name == "quiz_attempts":
            mock.select.return_value = [{
                "id": quiz_id,
                "user_id": user_id,
                "concept_node_id": "node-xp",
                "difficulty": "medium",
                "questions_json": SAMPLE_QUESTIONS,
            }]
        elif name == "graph_nodes":
            mock.select.return_value = [{
                "concept_name": "Loops", "mastery_score": 0.5, "course_id": "course-xp",
            }]
        elif name == "users":
            mock.select.return_value = [{"name": "Andres"}]
        else:
            mock.select.return_value = []
        mock.update.return_value = [{"id": "updated"}]
        return mock
    return factory


class TestQuizCompletedAward:
    def test_submit_awards_xp_keyed_on_the_attempt_id(self):
        quiz_id = "attempt-xp-1"
        submit_user_id = "user-xp-quiz"
        xp_table, xp_handles = _xp_tables("quiz_completed")
        ctx_run = AsyncMock(
            return_value=SimpleNamespace(output=SimpleNamespace(model_dump=lambda: {}))
        )
        with (
            patch("routes.quiz.table", side_effect=_quiz_table_factory(quiz_id, submit_user_id)),
            patch("routes.quiz.apply_graph_update"),
            patch("routes.quiz.get_quiz_context", return_value={}),
            patch("routes.quiz.quiz_context_agent.run", new=ctx_run),
            patch("routes.quiz.save_quiz_context"),
            patch("services.xp_service.table", side_effect=xp_table),
        ):
            r = client.post("/api/quiz/submit", json={
                "quiz_id": quiz_id,
                "answers": [
                    {"question_id": 1, "selected_label": "A"},
                    {"question_id": 2, "selected_label": "D"},
                ],
            })
        assert r.status_code == 200
        xp_handles["xp_events"].insert.assert_called_once()
        payload = xp_handles["xp_events"].insert.call_args[0][0]
        assert payload["user_id"] == submit_user_id
        assert payload["rule_key"] == "quiz_completed"
        assert payload["source_type"] == "quiz"
        # The real earning id is the attempt id the request submitted against
        # (quiz_id in the request body / "id" on the mocked quiz_attempts
        # row) — known independently of anything the mock echoes back.
        assert payload["source_id"] == quiz_id


# ── POST /api/documents/upload/sync → document_uploaded ──────────────────────

def _upload_document_result():
    from agents.classifier import DocumentClassification
    from agents.summary import Summary
    from agents.concept_extraction import Concept, ConceptList
    from agents.document import DocumentProcessingResult

    return DocumentProcessingResult(
        classification=DocumentClassification(
            category="lecture_notes", is_syllabus=False,
            confidence=0.9, rationale="test",
        ),
        summary=Summary(headline="Test doc", abstract="A concise overview.",
                        key_points=["a", "b", "c"]),
        concepts=ConceptList(concepts=[
            Concept(name="Concept A", description="d", importance=0.5),
        ]),
        syllabus=None,
        graph_updated=False,
    )


def _doc_table_factory(doc_row: dict):
    def factory(name):
        mock = MagicMock()
        if name == "documents":
            mock.select.return_value = []  # no existing request_id match
            mock.insert.return_value = [doc_row]
        else:
            mock.select.return_value = []
            mock.insert.return_value = []
        mock.update.return_value = []
        return mock
    return factory


class TestDocumentUploadedAward:
    def test_upload_sync_awards_xp_keyed_on_the_document_id(self):
        document_id = "doc-xp-1"
        upload_user_id = "user-xp-doc"
        xp_table, xp_handles = _xp_tables("document_uploaded")
        text = ("Sample document body. This gives the upload fixture enough "
                "extracted text to look like a document that was actually read.")
        with (
            patch("routes.documents._validate_user", return_value=None),
            patch("routes.documents.extract_text_from_file", return_value=text),
            patch("routes.documents.process_document", return_value=_upload_document_result()),
            patch("routes.documents.table", side_effect=_doc_table_factory({"id": document_id})),
            patch("services.xp_service.table", side_effect=xp_table),
        ):
            r = client.post(
                "/api/documents/upload/sync",
                files={"file": ("notes.pdf", io.BytesIO(b"%PDF-1.4 sample"), "application/pdf")},
                data={"course_id": "course-1", "user_id": upload_user_id},
            )
        assert r.status_code == 200
        xp_handles["xp_events"].insert.assert_called_once()
        payload = xp_handles["xp_events"].insert.call_args[0][0]
        assert payload["user_id"] == upload_user_id
        assert payload["rule_key"] == "document_uploaded"
        assert payload["source_type"] == "document"
        # The real earning id is the id the (mocked) documents insert
        # returned — the id _persist_document's full_row actually carries,
        # known independently here rather than trusted from the call site.
        assert payload["source_id"] == document_id


# ── POST /api/notes → note_created ───────────────────────────────────────────

class TestNoteCreatedAward:
    def test_create_awards_xp_keyed_on_the_note_id(self):
        note_id = "note-xp-1"
        note_user_id = "user-xp-note"
        xp_table, xp_handles = _xp_tables("note_created")

        async def fake_create(user_id, offering_id, title, body, tags):
            return {
                "id": note_id, "user_id": user_id, "offering_id": offering_id,
                "title": title, "body": body, "tags": tags,
                "last_summary": None, "last_summary_at": None,
                "created_at": "2026-07-31T00:00:00Z",
                "updated_at": "2026-07-31T00:00:00Z",
            }

        with (
            patch("routes.notes.resolve_offering", return_value="off-xp"),
            patch("routes.notes.create_note", side_effect=fake_create),
            patch("services.xp_service.table", side_effect=xp_table),
        ):
            r = client.post(
                "/api/notes",
                json={"user_id": note_user_id, "course_id": "c1",
                      "title": "T", "body": "B", "tags": []},
            )
        assert r.status_code == 200
        xp_handles["xp_events"].insert.assert_called_once()
        payload = xp_handles["xp_events"].insert.call_args[0][0]
        assert payload["user_id"] == note_user_id
        assert payload["rule_key"] == "note_created"
        assert payload["source_type"] == "note"
        # The real earning id is the note id create_note returned — the
        # route's `note["id"]` — known independently here, not echoed from
        # the mock we're asserting against.
        assert payload["source_id"] == note_id


# ── POST /api/learn/end-session → session_completed ──────────────────────────

def _session_table_factory(user_id: str):
    def factory(name):
        mock = MagicMock()
        if name == "sessions":
            mock.select.return_value = [{
                "user_id": user_id,
                "started_at": "2026-07-31T00:00:00",
            }]
        else:
            mock.select.return_value = []
        mock.update.return_value = []
        return mock
    return factory


class TestSessionCompletedAward:
    def test_end_session_awards_xp_keyed_on_the_session_id(self):
        session_id = "sess-xp-1"
        session_user_id = "user-xp-session"
        xp_table, xp_handles = _xp_tables("session_completed")
        with (
            patch("routes.learn.table", side_effect=_session_table_factory(session_user_id)),
            patch("services.xp_service.table", side_effect=xp_table),
        ):
            r = client.post("/api/learn/end-session", json={
                "session_id": session_id, "user_id": session_user_id,
            })
        assert r.status_code == 200
        xp_handles["xp_events"].insert.assert_called_once()
        payload = xp_handles["xp_events"].insert.call_args[0][0]
        assert payload["user_id"] == session_user_id
        assert payload["rule_key"] == "session_completed"
        assert payload["source_type"] == "session"
        # The real earning id is the session id the request ended — known
        # independently here, not whatever the table mock happens to echo.
        assert payload["source_id"] == session_id

    def test_pending_session_early_return_does_not_award(self):
        """A PENDING (never-materialized) session ended before any `sessions`
        row exists returns the empty summary immediately (routes/learn.py,
        the `if body.session_id in PENDING_SESSIONS` branch) — no row is
        ever persisted, so no XP should be awarded. Cleanest failed-action
        case to drive: no table mocking is needed at all, since the early
        return happens before the route touches the database."""
        import routes.learn as learn

        learn.PENDING_SESSIONS["sess-xp-pending"] = {
            "user_id": "user-xp-pending",
            "mode": "socratic",
            "topic": "T",
            "offering_id": None,
            "assistant_reply": "hi",
            "graph_update": {},
        }
        with patch("routes.learn.award_xp_safe") as award_mock:
            r = client.post("/api/learn/end-session", json={
                "session_id": "sess-xp-pending", "user_id": "user-xp-pending",
            })
        assert r.status_code == 200
        award_mock.assert_not_called()
