"""
Unit tests for routes/learn.py

Tests pure helper functions directly (no HTTP layer needed).
Route-level tests use FastAPI's TestClient with Gemini and DB mocked.
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


# ── _get_course_id_for_topic ──────────────────────────────────────────────────

class TestGetCourseIdForTopic:
    def test_empty_topic_returns_empty(self):
        from routes.learn import _get_course_id_for_topic
        with patch("routes.learn.table"):
            assert _get_course_id_for_topic("", "u1") == ""

    def test_matches_enrolled_course_code(self):
        from routes.learn import _get_course_id_for_topic
        uc = MagicMock()
        uc.select.return_value = [
            {"course_id": "cid-math", "courses": {"course_code": "MATH", "course_name": "Calculus"}},
        ]

        def factory(name):
            if name == "user_courses":
                return uc
            m = MagicMock()
            m.select.return_value = []
            return m

        with patch("routes.learn.table", side_effect=factory):
            assert _get_course_id_for_topic("math", "u1") == "cid-math"

    def test_matches_enrolled_course_name(self):
        from routes.learn import _get_course_id_for_topic
        uc = MagicMock()
        uc.select.return_value = [
            {"course_id": "cid-bio", "courses": {"course_code": "", "course_name": "Biology 101"}},
        ]

        def factory(name):
            if name == "user_courses":
                return uc
            m = MagicMock()
            m.select.return_value = []
            return m

        with patch("routes.learn.table", side_effect=factory):
            assert _get_course_id_for_topic("biology 101", "u1") == "cid-bio"

    def test_matches_graph_subject_label(self):
        from routes.learn import _get_course_id_for_topic
        uc = MagicMock()
        uc.select.return_value = [
            {
                "course_id": "cid-x",
                "courses": {"course_code": "CS", "course_name": "Intro"},
            },
        ]

        def factory(name):
            if name == "user_courses":
                return uc
            if name == "graph_nodes":
                m = MagicMock()
                m.select.return_value = []
                return m
            m = MagicMock()
            m.select.return_value = []
            return m

        with patch("routes.learn.table", side_effect=factory):
            assert _get_course_id_for_topic("CS - Intro", "u1") == "cid-x"

    def test_concept_node_with_course_id(self):
        from routes.learn import _get_course_id_for_topic
        uc = MagicMock()
        uc.select.return_value = []

        gn = MagicMock()
        gn.select.return_value = [{"course_id": "cid-from-node"}]

        def factory(name):
            if name == "user_courses":
                return uc
            if name == "graph_nodes":
                return gn
            m = MagicMock()
            m.select.return_value = []
            return m

        with patch("routes.learn.table", side_effect=factory):
            assert _get_course_id_for_topic("Recursion", "u1") == "cid-from-node"

    def test_unknown_topic_returns_empty(self):
        from routes.learn import _get_course_id_for_topic
        mock = MagicMock()
        mock.select.return_value = []
        with patch("routes.learn.table", return_value=mock):
            assert _get_course_id_for_topic("UnknownXyzzy", "u1") == ""


# ── GET /api/learn/sessions/{user_id} ────────────────────────────────────────

class TestListSessions:
    def test_returns_sessions_with_message_count(self):
        sessions = [
            {"id": "s1", "topic": "Loops", "mode": "socratic", "started_at": "2026-01-01T10:00:00", "ended_at": None},
        ]

        def factory(name):
            mock = MagicMock()
            if name == "sessions":
                mock.select.return_value = sessions
            elif name == "messages":
                mock.select.return_value = [{"id": "m1"}, {"id": "m2"}]
            else:
                mock.select.return_value = []
            return mock

        with patch("routes.learn.table", side_effect=factory):
            r = client.get("/api/learn/sessions/user_andres")

        assert r.status_code == 200
        data = r.json()["sessions"]
        assert len(data) == 1
        assert data[0]["topic"] == "Loops"
        assert data[0]["message_count"] == 2
        assert data[0]["is_active"] is True

    def test_ended_session_is_not_active(self):
        sessions = [{"id": "s1", "topic": "X", "mode": "socratic", "started_at": "2026-01-01T00:00:00", "ended_at": "2026-01-01T01:00:00"}]

        def factory(name):
            mock = MagicMock()
            mock.select.return_value = sessions if name == "sessions" else []
            return mock

        with patch("routes.learn.table", side_effect=factory):
            r = client.get("/api/learn/sessions/user_andres")

        assert r.json()["sessions"][0]["is_active"] is False

    def test_empty_sessions(self):
        with patch("routes.learn.table") as t:
            t.return_value.select.return_value = []
            r = client.get("/api/learn/sessions/user_andres")
        assert r.status_code == 200
        assert r.json()["sessions"] == []


# ── GET /api/learn/sessions/{session_id}/resume ───────────────────────────────

class TestResumeSession:
    def test_returns_404_when_session_not_found(self):
        with patch("routes.learn.table") as t:
            t.return_value.select.return_value = []
            r = client.get("/api/learn/sessions/nonexistent-id/resume")
        assert r.status_code == 404

    def test_returns_session_and_messages(self):
        session_data = [{"id": "s1", "user_id": "u1", "topic": "Loops", "mode": "socratic", "started_at": "2026-01-01T00:00:00", "ended_at": None}]
        messages = [{"id": "m1", "role": "assistant", "content": "Hello!", "created_at": "2026-01-01T00:00:01"}]

        call_count = {"n": 0}

        def factory(name):
            mock = MagicMock()
            call_count["n"] += 1
            if name == "sessions":
                mock.select.return_value = session_data
            else:
                mock.select.return_value = messages
            return mock

        with patch("routes.learn.table", side_effect=factory):
            r = client.get("/api/learn/sessions/s1/resume?user_id=u1")

        assert r.status_code == 200
        assert r.json()["session"]["topic"] == "Loops"
        assert len(r.json()["messages"]) == 1


# ── POST /api/learn/mode-switch ───────────────────────────────────────────────

class TestModeSwitch:
    def _make_table_factory(self, user_name: str, topic: str):
        """Return a table() side-effect that answers users and sessions queries."""
        def factory(name):
            mock = MagicMock()
            if name == "users":
                mock.select.return_value = [{"name": user_name}]
            elif name == "sessions":
                mock.select.return_value = [{"topic": topic}]
            else:
                mock.select.return_value = []
            return mock
        return factory

    def test_returns_200_with_reply(self):
        factory = self._make_table_factory("Andres Garcia", "Recursion")
        with patch("routes.learn.table", side_effect=factory):
            r = client.post(
                "/api/learn/mode-switch",
                json={"session_id": "s1", "user_id": "u1", "new_mode": "expository"},
            )
        assert r.status_code == 200
        assert "reply" in r.json()

    def test_reply_uses_first_name_only(self):
        """Message must greet with first name only, not full name."""
        factory = self._make_table_factory("Andres Garcia", "Recursion")
        with patch("routes.learn.table", side_effect=factory):
            r = client.post(
                "/api/learn/mode-switch",
                json={"session_id": "s1", "user_id": "u1", "new_mode": "socratic"},
            )
        reply = r.json()["reply"]
        assert "Andres" in reply
        assert "Garcia" not in reply

    def test_reply_contains_mode_display_name(self):
        factory = self._make_table_factory("Maria", "Sorting algorithms")
        with patch("routes.learn.table", side_effect=factory):
            r = client.post(
                "/api/learn/mode-switch",
                json={"session_id": "s1", "user_id": "u1", "new_mode": "expository"},
            )
        reply = r.json()["reply"]
        assert "Expository" in reply

    def test_reply_contains_current_topic(self):
        factory = self._make_table_factory("Jake", "Binary Search Trees")
        with patch("routes.learn.table", side_effect=factory):
            r = client.post(
                "/api/learn/mode-switch",
                json={"session_id": "s1", "user_id": "u1", "new_mode": "teachback"},
            )
        reply = r.json()["reply"]
        assert "Binary Search Trees" in reply

    def test_reply_has_no_em_dash(self):
        factory = self._make_table_factory("Sam", "Graphs")
        with patch("routes.learn.table", side_effect=factory):
            r = client.post(
                "/api/learn/mode-switch",
                json={"session_id": "s1", "user_id": "u1", "new_mode": "socratic"},
            )
        reply = r.json()["reply"]
        assert "\u2014" not in reply  # em-dash
        assert "\u2013" not in reply  # en-dash (extra guard)

    def test_reply_has_no_markdown_bold(self):
        factory = self._make_table_factory("Sam", "Graphs")
        with patch("routes.learn.table", side_effect=factory):
            r = client.post(
                "/api/learn/mode-switch",
                json={"session_id": "s1", "user_id": "u1", "new_mode": "socratic"},
            )
        reply = r.json()["reply"]
        assert "**" not in reply

    def test_message_is_saved_to_db(self):
        factory = self._make_table_factory("Lea", "Linked Lists")
        with patch("routes.learn.table", side_effect=factory) as t:
            client.post(
                "/api/learn/mode-switch",
                json={"session_id": "s1", "user_id": "u1", "new_mode": "teachback"},
            )
            # save_message calls table("messages").insert(...)
            insert_calls = [
                call for call in t.call_args_list if call.args and call.args[0] == "messages"
            ]
        assert len(insert_calls) >= 1
