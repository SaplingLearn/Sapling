"""
Unit tests for routes/learn.py

Tests pure helper functions directly (no HTTP layer needed).
Route-level tests use FastAPI's TestClient with Gemini and DB mocked.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
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


# ── _resolve_legacy_model ─────────────────────────────────────────────────────

class TestResolveLegacyModel:
    def test_none_returns_smart(self):
        # PR #78 review: symmetry with agent default. The agent path defaults
        # to gemini-2.5-pro (MODEL_SMART) per agents/_providers.py:_DEFAULTS,
        # so the legacy fallback must too.
        from routes.learn import _resolve_legacy_model
        from services.gemini_service import MODEL_SMART
        assert _resolve_legacy_model(None) == MODEL_SMART

    def test_empty_string_returns_smart(self):
        # PR #78 review: symmetry with agent default.
        from routes.learn import _resolve_legacy_model
        from services.gemini_service import MODEL_SMART
        assert _resolve_legacy_model("") == MODEL_SMART

    def test_fast_returns_lite(self):
        from routes.learn import _resolve_legacy_model
        from services.gemini_service import MODEL_LITE
        assert _resolve_legacy_model("fast") == MODEL_LITE

    def test_smart_returns_smart(self):
        from routes.learn import _resolve_legacy_model
        from services.gemini_service import MODEL_SMART
        assert _resolve_legacy_model("smart") == MODEL_SMART

    def test_uppercase_fast_returns_smart(self):
        # Lookup is case-sensitive: only lowercase keys hit the map. Anything
        # unrecognized (incl. wrong case) falls back to the Pro tier to match
        # the agent default — PR #78 review: symmetry with agent default.
        from routes.learn import _resolve_legacy_model
        from services.gemini_service import MODEL_SMART
        assert _resolve_legacy_model("FAST") == MODEL_SMART

    def test_garbage_returns_smart(self):
        # PR #78 review: symmetry with agent default.
        from routes.learn import _resolve_legacy_model
        from services.gemini_service import MODEL_SMART
        assert _resolve_legacy_model("garbage") == MODEL_SMART

    def test_default_matches_agent_default_for_no_pref(self):
        """When body.model_pref is None, the legacy fallback must hit the
        same model tier the agent path defaults to (gemini-2.5-pro per
        agents/_providers.py:_DEFAULTS["chat_tutor"]). PR #71's commit
        a2fd5cd established this contract for quiz; chat must match.
        """
        from routes.learn import _resolve_legacy_model
        from services.gemini_service import MODEL_SMART
        assert _resolve_legacy_model(None) == MODEL_SMART
        assert _resolve_legacy_model("") == MODEL_SMART
        assert _resolve_legacy_model("garbage") == MODEL_SMART


# ── POST /api/learn/chat (agent path + legacy fallback) ──────────────────────


class TestChatViaAgent:
    """Pin the chat-tutor agent path: agent.run is called for happy paths,
    and the legacy `call_gemini_multiturn` pipeline is the fallback when the
    agent trips Pydantic AI guardrails or any unexpected exception.

    Mirror's PR #71's pattern in `tests/test_quiz_routes.py`.
    """

    def _make_table_factory(self, *, history_rows=None, course_id="course1"):
        """Default table factory: messages reads return `history_rows` (or
        empty), sessions reads return a course id, users return a name.
        """
        rows = history_rows or []

        def factory(name):
            mock = MagicMock()
            if name == "messages":
                mock.select.return_value = rows
            elif name == "sessions":
                mock.select.return_value = [{"course_id": course_id}]
            elif name == "users":
                mock.select.return_value = [{"name": "Andres"}]
            elif name == "graph_nodes":
                mock.select.return_value = []
            elif name == "documents":
                mock.select.return_value = []
            else:
                mock.select.return_value = []
            mock.update.return_value = []
            mock.insert.return_value = []
            return mock

        return factory

    def _post(self, **body_extra):
        return client.post("/api/learn/chat", json={
            "session_id": "s1",
            "user_id": "user_andres",
            "message": "What is recursion?",
            "mode": "socratic",
            "use_shared_context": True,
            **body_extra,
        })

    def test_returns_agent_reply(self):
        """Happy path: agent.run returns a string; route shapes it into
        the legacy `{reply, graph_update, mastery_changes}` dict."""
        from types import SimpleNamespace
        agent = MagicMock()
        agent.run = AsyncMock(return_value=SimpleNamespace(output="Recursion is a function calling itself."))
        with (
            patch("routes.learn.table", side_effect=self._make_table_factory()),
            patch("routes.learn.agent_for_mode", return_value=agent),
            patch("routes.learn.apply_graph_update"),
        ):
            r = self._post()
        assert r.status_code == 200
        data = r.json()
        assert data["reply"] == "Recursion is a function calling itself."
        assert data["graph_update"] == {}
        assert data["mastery_changes"] == []
        agent.run.assert_called_once()

    def test_falls_back_to_legacy_on_usage_limit(self):
        """UsageLimitExceeded → legacy path runs and its reply wins."""
        from pydantic_ai.exceptions import UsageLimitExceeded
        agent = MagicMock()
        agent.run = AsyncMock(side_effect=UsageLimitExceeded("token cap"))
        with (
            patch("routes.learn.table", side_effect=self._make_table_factory()),
            patch("routes.learn.agent_for_mode", return_value=agent),
            patch("routes.learn.get_graph", return_value={"nodes": [], "edges": []}),
            patch("routes.learn.apply_graph_update", return_value=[]),
            patch(
                "routes.learn.call_gemini_multiturn",
                return_value="LEGACY REPLY",
            ),
            patch(
                "routes.learn.extract_graph_update",
                return_value=("LEGACY REPLY", {}),
            ),
        ):
            r = self._post()
        assert r.status_code == 200
        assert r.json()["reply"] == "LEGACY REPLY"

    def test_falls_back_to_legacy_on_unexpected_exception(self):
        """A bare Exception trips the catch-all and routes to legacy."""
        agent = MagicMock()
        agent.run = AsyncMock(side_effect=RuntimeError("boom"))
        with (
            patch("routes.learn.table", side_effect=self._make_table_factory()),
            patch("routes.learn.agent_for_mode", return_value=agent),
            patch("routes.learn.get_graph", return_value={"nodes": [], "edges": []}),
            patch("routes.learn.apply_graph_update", return_value=[]),
            patch("routes.learn.call_gemini_multiturn", return_value="LEGACY"),
            patch("routes.learn.extract_graph_update", return_value=("LEGACY", {})),
        ):
            r = self._post()
        assert r.status_code == 200
        assert r.json()["reply"] == "LEGACY"

    def test_falls_back_to_legacy_on_unexpected_model_behavior(self):
        """UnexpectedModelBehavior is also caught explicitly."""
        from pydantic_ai.exceptions import UnexpectedModelBehavior
        agent = MagicMock()
        agent.run = AsyncMock(side_effect=UnexpectedModelBehavior("bad output"))
        with (
            patch("routes.learn.table", side_effect=self._make_table_factory()),
            patch("routes.learn.agent_for_mode", return_value=agent),
            patch("routes.learn.get_graph", return_value={"nodes": [], "edges": []}),
            patch("routes.learn.apply_graph_update", return_value=[]),
            patch("routes.learn.call_gemini_multiturn", return_value="L"),
            patch("routes.learn.extract_graph_update", return_value=("L", {})),
        ):
            r = self._post()
        assert r.status_code == 200
        assert r.json()["reply"] == "L"

    def test_message_history_loaded_with_decryption(self):
        """`_load_message_history` calls `decrypt_if_present` on each row's
        `content` so the agent never receives ciphertext."""
        from routes.learn import _load_message_history

        history_rows = [
            {"role": "user", "content": "ENC:hello"},
            {"role": "assistant", "content": "ENC:hi back"},
        ]

        def factory(name):
            mock = MagicMock()
            if name == "messages":
                mock.select.return_value = history_rows
            else:
                mock.select.return_value = []
            return mock

        with (
            patch("routes.learn.table", side_effect=factory),
            patch(
                "routes.learn.decrypt_if_present",
                side_effect=lambda v: (v or "").replace("ENC:", "") if v else v,
            ) as decrypt_mock,
        ):
            history = _load_message_history("s1")

        # Once per row.
        assert decrypt_mock.call_count == 2
        # Two converted Pydantic AI messages: one ModelRequest, one ModelResponse.
        from pydantic_ai.messages import ModelRequest, ModelResponse
        assert len(history) == 2
        assert isinstance(history[0], ModelRequest)
        assert isinstance(history[1], ModelResponse)
        assert history[0].parts[0].content == "hello"
        assert history[1].parts[0].content == "hi back"

    def test_user_and_model_messages_persisted_with_encryption(self):
        """Both the user turn and the model turn are encrypted at the
        boundary via `encrypt_if_present` before being inserted into
        the messages table."""
        from types import SimpleNamespace

        agent = MagicMock()
        agent.run = AsyncMock(return_value=SimpleNamespace(output="MODEL_REPLY"))

        # Capture every messages.insert payload so we can assert on encrypted values.
        inserts: list[dict] = []

        def factory(name):
            mock = MagicMock()
            if name == "messages":
                mock.select.return_value = []

                def _capture(payload):
                    inserts.append(payload)
                    return [payload]

                mock.insert.side_effect = _capture
            elif name == "sessions":
                mock.select.return_value = [{"course_id": "course1"}]
            elif name == "users":
                mock.select.return_value = [{"name": "Andres"}]
            else:
                mock.select.return_value = []
                mock.insert.return_value = []
            mock.update.return_value = []
            return mock

        with (
            patch("routes.learn.table", side_effect=factory),
            patch("routes.learn.agent_for_mode", return_value=agent),
            patch("routes.learn.apply_graph_update"),
            patch(
                "routes.learn.encrypt_if_present",
                side_effect=lambda v: f"ENC:{v}" if v else v,
            ) as encrypt_mock,
        ):
            r = self._post(message="USER_PROMPT")

        assert r.status_code == 200
        # Two inserts: user row + assistant row.
        assert len(inserts) == 2
        roles = [row["role"] for row in inserts]
        assert roles == ["user", "assistant"]
        # encrypt_if_present was invoked on both contents.
        encrypted_values = [c.args[0] for c in encrypt_mock.call_args_list]
        assert "USER_PROMPT" in encrypted_values
        assert "MODEL_REPLY" in encrypted_values
        # And the persisted ciphertext shows the wrap.
        assert inserts[0]["content"] == "ENC:USER_PROMPT"
        assert inserts[1]["content"] == "ENC:MODEL_REPLY"

    def test_smart_pref_overrides_agent_model(self):
        """body.model_pref='smart' → agent.run gets `model=GoogleModel('gemini-2.5-pro')`."""
        from types import SimpleNamespace
        agent = MagicMock()
        agent.run = AsyncMock(return_value=SimpleNamespace(output="ok"))
        with (
            patch("routes.learn.table", side_effect=self._make_table_factory()),
            patch("routes.learn.agent_for_mode", return_value=agent),
            patch("routes.learn.apply_graph_update"),
        ):
            r = self._post(model_pref="smart")
        assert r.status_code == 200
        kwargs = agent.run.call_args.kwargs
        assert "model" in kwargs, "smart pref must pass an explicit model override"
        assert kwargs["model"].model_name == "gemini-2.5-pro"

    def test_fast_pref_overrides_agent_model(self):
        """body.model_pref='fast' → agent.run gets `model=GoogleModel('gemini-2.5-flash-lite')`."""
        from types import SimpleNamespace
        agent = MagicMock()
        agent.run = AsyncMock(return_value=SimpleNamespace(output="ok"))
        with (
            patch("routes.learn.table", side_effect=self._make_table_factory()),
            patch("routes.learn.agent_for_mode", return_value=agent),
            patch("routes.learn.apply_graph_update"),
        ):
            r = self._post(model_pref="fast")
        assert r.status_code == 200
        kwargs = agent.run.call_args.kwargs
        assert "model" in kwargs
        assert kwargs["model"].model_name == "gemini-2.5-flash-lite"

    def test_no_pref_falls_through_to_agent_default(self):
        """No model_pref → agent.run gets NO `model` kwarg; agent default wins."""
        from types import SimpleNamespace
        agent = MagicMock()
        agent.run = AsyncMock(return_value=SimpleNamespace(output="ok"))
        with (
            patch("routes.learn.table", side_effect=self._make_table_factory()),
            patch("routes.learn.agent_for_mode", return_value=agent),
            patch("routes.learn.apply_graph_update"),
        ):
            r = self._post()
        assert r.status_code == 200
        kwargs = agent.run.call_args.kwargs
        assert "model" not in kwargs

    def test_use_shared_context_false_appends_constraint(self):
        """`use_shared_context=False` augments the user message with a
        constraint instructing the agent not to call class-aggregate tools."""
        from types import SimpleNamespace
        agent = MagicMock()
        agent.run = AsyncMock(return_value=SimpleNamespace(output="ok"))
        with (
            patch("routes.learn.table", side_effect=self._make_table_factory()),
            patch("routes.learn.agent_for_mode", return_value=agent),
            patch("routes.learn.apply_graph_update"),
        ):
            r = self._post(message="What is X?", use_shared_context=False)
        assert r.status_code == 200
        sent_message = agent.run.call_args.args[0]
        assert "What is X?" in sent_message
        assert "shared context" in sent_message.lower()
