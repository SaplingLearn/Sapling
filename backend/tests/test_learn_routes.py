"""
Unit tests for routes/learn.py

Tests pure helper functions directly (no HTTP layer needed).
Route-level tests use FastAPI's TestClient with Gemini and DB mocked.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from main import app
from tests.agent_run_fakes import run_result, textless_run_result

client = TestClient(app)


# ── _get_course_id_for_topic ──────────────────────────────────────────────────

class TestGetCourseIdForTopic:
    def test_empty_topic_returns_empty(self):
        from routes.learn import _get_course_id_for_topic
        with patch("routes.learn.table"):
            assert _get_course_id_for_topic("", "u1") == ""

    def test_matches_enrolled_course_code(self):
        from routes.learn import _get_course_id_for_topic
        # Enrollment keys on an offering; the abstract course id (returned to the
        # session + graph) lives at course_offerings.course_id, behind the offering.
        uc = MagicMock()
        uc.select.return_value = [
            {
                "offering_id": "off-math",
                "course_offerings": {
                    "course_id": "cid-math",
                    "courses": {"course_code": "MATH", "course_name": "Calculus"},
                },
            },
        ]

        def factory(name):
            if name == "enrollments":
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
            {
                "offering_id": "off-bio",
                "course_offerings": {
                    "course_id": "cid-bio",
                    "courses": {"course_code": "", "course_name": "Biology 101"},
                },
            },
        ]

        def factory(name):
            if name == "enrollments":
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
                "offering_id": "off-x",
                "course_offerings": {
                    "course_id": "cid-x",
                    "courses": {"course_code": "CS", "course_name": "Intro"},
                },
            },
        ]

        def factory(name):
            if name == "enrollments":
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
            if name == "enrollments":
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
    def _make_table_factory(self, topic: str):
        """Return a table() side-effect that answers sessions queries.

        The display name no longer lives on `users` (migration 0024 moved it to
        user_profiles); get_user_name resolves it via services.profiles, which
        these tests patch through `routes.learn.get_display_name`.
        """
        def factory(name):
            mock = MagicMock()
            if name == "sessions":
                mock.select.return_value = [{"topic": topic}]
            else:
                mock.select.return_value = []
            return mock
        return factory

    def _patches(self, user_name: str, topic: str):
        """table factory + display-name patch for the mode-switch greeting."""
        return (
            patch("routes.learn.table", side_effect=self._make_table_factory(topic)),
            patch("routes.learn.get_display_name", return_value=user_name),
        )

    def test_returns_200_with_reply(self):
        tbl, name = self._patches("Andres Garcia", "Recursion")
        with tbl, name:
            r = client.post(
                "/api/learn/mode-switch",
                json={"session_id": "s1", "user_id": "u1", "new_mode": "expository"},
            )
        assert r.status_code == 200
        assert "reply" in r.json()

    def test_reply_uses_first_name_only(self):
        """Message must greet with first name only, not full name."""
        tbl, name = self._patches("Andres Garcia", "Recursion")
        with tbl, name:
            r = client.post(
                "/api/learn/mode-switch",
                json={"session_id": "s1", "user_id": "u1", "new_mode": "socratic"},
            )
        reply = r.json()["reply"]
        assert "Andres" in reply
        assert "Garcia" not in reply

    def test_reply_contains_mode_display_name(self):
        tbl, name = self._patches("Maria", "Sorting algorithms")
        with tbl, name:
            r = client.post(
                "/api/learn/mode-switch",
                json={"session_id": "s1", "user_id": "u1", "new_mode": "expository"},
            )
        reply = r.json()["reply"]
        assert "Expository" in reply

    def test_reply_contains_current_topic(self):
        tbl, name = self._patches("Jake", "Binary Search Trees")
        with tbl, name:
            r = client.post(
                "/api/learn/mode-switch",
                json={"session_id": "s1", "user_id": "u1", "new_mode": "teachback"},
            )
        reply = r.json()["reply"]
        assert "Binary Search Trees" in reply

    def test_reply_has_no_em_dash(self):
        tbl, name = self._patches("Sam", "Graphs")
        with tbl, name:
            r = client.post(
                "/api/learn/mode-switch",
                json={"session_id": "s1", "user_id": "u1", "new_mode": "socratic"},
            )
        reply = r.json()["reply"]
        assert "\u2014" not in reply  # em-dash
        assert "\u2013" not in reply  # en-dash (extra guard)

    def test_reply_has_no_markdown_bold(self):
        tbl, name = self._patches("Sam", "Graphs")
        with tbl, name:
            r = client.post(
                "/api/learn/mode-switch",
                json={"session_id": "s1", "user_id": "u1", "new_mode": "socratic"},
            )
        reply = r.json()["reply"]
        assert "**" not in reply

    def test_message_is_saved_to_db(self):
        tbl, name = self._patches("Lea", "Linked Lists")
        with tbl as t, name:
            client.post(
                "/api/learn/mode-switch",
                json={"session_id": "s1", "user_id": "u1", "new_mode": "teachback"},
            )
            # save_message calls table("messages").insert(...)
            insert_calls = [
                call for call in t.call_args_list if call.args and call.args[0] == "messages"
            ]
        assert len(insert_calls) >= 1


# ── PATCH /api/learn/sessions/{session_id} ────────────────────────────────────

class TestRenameSession:
    def test_renames_persisted_session(self):
        sessions_mock = MagicMock()
        sessions_mock.select.return_value = [{"user_id": "u1"}]

        def factory(name):
            if name == "sessions":
                return sessions_mock
            m = MagicMock()
            m.select.return_value = []
            return m

        with patch("routes.learn.table", side_effect=factory):
            r = client.patch(
                "/api/learn/sessions/s1",
                json={"user_id": "u1", "topic": "  New Topic  "},
            )

        assert r.status_code == 200
        body = r.json()
        assert body == {"updated": True, "session": {"id": "s1", "topic": "New Topic"}}
        sessions_mock.update.assert_called_once_with(
            {"topic": "New Topic"},
            filters={"id": "eq.s1"},
        )

    def test_renames_pending_session(self):
        from routes.learn import PENDING_SESSIONS
        PENDING_SESSIONS["pending-1"] = {
            "user_id": "u1",
            "topic": "Old",
            "mode": "socratic",
            "assistant_reply": "hi",
        }
        try:
            r = client.patch(
                "/api/learn/sessions/pending-1",
                json={"user_id": "u1", "topic": "Renamed"},
            )
            assert r.status_code == 200
            assert r.json() == {"updated": True, "session": {"id": "pending-1", "topic": "Renamed"}}
            assert PENDING_SESSIONS["pending-1"]["topic"] == "Renamed"
        finally:
            PENDING_SESSIONS.pop("pending-1", None)

    def test_empty_topic_returns_400(self):
        r = client.patch(
            "/api/learn/sessions/s1",
            json={"user_id": "u1", "topic": "   "},
        )
        assert r.status_code == 400

    def test_topic_too_long_returns_400(self):
        r = client.patch(
            "/api/learn/sessions/s1",
            json={"user_id": "u1", "topic": "x" * 121},
        )
        assert r.status_code == 400

    def test_wrong_user_returns_403(self):
        sessions_mock = MagicMock()
        sessions_mock.select.return_value = [{"user_id": "other_user"}]

        def factory(name):
            if name == "sessions":
                return sessions_mock
            m = MagicMock()
            m.select.return_value = []
            return m

        with patch("routes.learn.table", side_effect=factory):
            r = client.patch(
                "/api/learn/sessions/s1",
                json={"user_id": "u1", "topic": "Renamed"},
            )
        assert r.status_code == 403

    def test_missing_session_returns_404(self):
        with patch("routes.learn.table") as t:
            t.return_value.select.return_value = []
            r = client.patch(
                "/api/learn/sessions/nonexistent",
                json={"user_id": "u1", "topic": "Renamed"},
            )
        assert r.status_code == 404


# ── model_pref resolution ─────────────────────────────────────────────────────

class TestModelPref:
    def test_no_pref_matches_agent_default_model(self):
        """Default-parity invariant (PR #78/#71, folded here from the deleted
        TestResolveLegacyModel in #151a): when body.model_pref is None,
        `_resolve_model_pref` returns no override, so the run lands on the
        agent's default model — gemini-2.5-pro per
        agents/_providers.py:_DEFAULTS["chat_tutor"] — which is exactly the
        tier an explicit "smart" pref selects. A drift in either direction
        (a different agent default, or a "smart" map entry pointing
        elsewhere) breaks the "no pref == smart" contract users see."""
        from agents._providers import _DEFAULTS
        from routes.learn import _PREF_MODEL_NAMES, _resolve_model_pref

        assert _resolve_model_pref(None) is None, (
            "no pref must fall through to the agent default, not build an override"
        )
        assert _PREF_MODEL_NAMES["smart"] == _DEFAULTS["chat_tutor"] == "gemini-2.5-pro"


# ── POST /api/learn/chat (agent path + legacy fallback) ──────────────────────


class TestChatViaAgent:
    """Pin the chat-tutor agent path: agent.run is called for happy paths,
    and guardrail failures map to HTTP statuses (#151a, the notes precedent
    from routes/notes.py::_run_note_worker): UsageLimitExceeded → 413,
    UnexpectedModelBehavior / unexpected exceptions → 502. The legacy
    `call_gemini_multiturn` fallback is gone.
    """

    def _make_table_factory(self, *, history_rows=None, offering_id="off1"):
        """Default table factory: messages reads return `history_rows` (or
        empty), sessions reads return an offering id (0025), users a name.
        """
        rows = history_rows or []

        def factory(name):
            mock = MagicMock()
            if name == "messages":
                mock.select.return_value = rows
            elif name == "sessions":
                mock.select.return_value = [{"offering_id": offering_id}]
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
        the `{reply, graph_update, mastery_changes}` wire dict."""
        agent = MagicMock()
        agent.run = AsyncMock(return_value=run_result("Recursion is a function calling itself."))
        with (
            patch("routes.learn.table", side_effect=self._make_table_factory()),
            patch("routes.learn.agent_for_mode", return_value=agent),
        ):
            r = self._post()
        assert r.status_code == 200
        data = r.json()
        assert data["reply"] == "Recursion is a function calling itself."
        assert data["graph_update"] == {}
        assert data["mastery_changes"] == []
        agent.run.assert_called_once()

    def test_usage_limit_returns_413_and_persists_nothing(self):
        """UsageLimitExceeded → 413 with a cause-naming detail (retrying the
        same turn trips the same limit — no "try again" wording), and the
        failed turn writes no message rows."""
        from pydantic_ai.exceptions import UsageLimitExceeded
        agent = MagicMock()
        agent.run = AsyncMock(side_effect=UsageLimitExceeded("token cap"))
        with (
            patch("routes.learn.table", side_effect=self._make_table_factory()),
            patch("routes.learn.agent_for_mode", return_value=agent),
            patch("routes.learn.save_message") as save,
        ):
            r = self._post()
        assert r.status_code == 413
        assert "budget" in r.json()["detail"]
        save.assert_not_called()

    def test_unexpected_exception_returns_502(self):
        """A bare Exception trips the catch-all → 502 with a retry-friendly
        detail (this rung is the pageable bug, logged via logger.exception)."""
        agent = MagicMock()
        agent.run = AsyncMock(side_effect=RuntimeError("boom"))
        with (
            patch("routes.learn.table", side_effect=self._make_table_factory()),
            patch("routes.learn.agent_for_mode", return_value=agent),
            patch("routes.learn.save_message") as save,
        ):
            r = self._post()
        assert r.status_code == 502
        assert "try again" in r.json()["detail"].lower()
        save.assert_not_called()

    def test_unexpected_model_behavior_returns_502(self):
        """UnexpectedModelBehavior → 502, retry-friendly (transient upstream
        trouble, not a deterministic client error)."""
        from pydantic_ai.exceptions import UnexpectedModelBehavior
        agent = MagicMock()
        agent.run = AsyncMock(side_effect=UnexpectedModelBehavior("bad output"))
        with (
            patch("routes.learn.table", side_effect=self._make_table_factory()),
            patch("routes.learn.agent_for_mode", return_value=agent),
        ):
            r = self._post()
        assert r.status_code == 502
        assert "try again" in r.json()["detail"].lower()

    def test_blank_agent_reply_returns_502(self):
        """#153 / ADR-0023 follow-up: a whitespace-only agent reply (the
        bare-newline-after-tool-call quirk on the JSON path) is degenerate
        model output, not a success — it maps to the same retry-friendly 502
        instead of persisting an empty assistant row."""
        agent = MagicMock()
        agent.run = AsyncMock(return_value=run_result("\n"))
        with (
            patch("routes.learn.table", side_effect=self._make_table_factory()),
            patch("routes.learn.agent_for_mode", return_value=agent),
            patch("routes.learn.save_message") as save,
        ):
            r = self._post()
        assert r.status_code == 502
        save.assert_not_called()

    def test_textless_turn_does_not_return_or_persist_the_prior_reply(self):
        """A turn whose model response carries NO text part must not answer
        with the PREVIOUS turn's reply.

        `_prepare_chat_run` puts `message_history` into `run_kwargs`, so
        `result.output` resolves out of a message list that INCLUDES the
        history: when the model ends its turn after tool calls, `.output`
        hands back the last assistant message from an earlier turn — fully
        formed and non-blank, so a bare `if not reply.strip()` guard never
        sees it. The route would then return and persist a byte-identical
        copy of its own last answer against a completely different question.

        This path matters more than the streamed one: `_chat_turn_json` is
        both POST /api/learn/chat AND the streamed route's Rung-1 fallback,
        which is exactly where textless turns now get sent.
        """
        PRIOR = "Recursion is a function that calls itself until a base case."
        history_rows = [
            {"role": "user", "content": "What is recursion?"},
            {"role": "assistant", "content": PRIOR},
        ]
        agent = MagicMock()
        agent.run = AsyncMock(return_value=textless_run_result(PRIOR))
        with (
            patch(
                "routes.learn.table",
                side_effect=self._make_table_factory(history_rows=history_rows),
            ),
            patch("routes.learn.agent_for_mode", return_value=agent),
            patch("routes.learn.save_message") as save,
        ):
            r = self._post(message="And what is memoization?")

        assert r.status_code == 502, (
            "a turn that produced no text is a degenerate turn, not a success"
        )
        assert PRIOR not in r.text, "the prior turn's reply must never be replayed"
        assert not [
            c for c in save.call_args_list if c.args[1] == "assistant"
        ], "no assistant row may be persisted for a turn that said nothing"

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

        agent = MagicMock()
        agent.run = AsyncMock(return_value=run_result("MODEL_REPLY"))

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
                mock.select.return_value = [{"offering_id": "off1"}]
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
        agent = MagicMock()
        agent.run = AsyncMock(return_value=run_result("ok"))
        with (
            patch("routes.learn.table", side_effect=self._make_table_factory()),
            patch("routes.learn.agent_for_mode", return_value=agent),
        ):
            r = self._post(model_pref="smart")
        assert r.status_code == 200
        kwargs = agent.run.call_args.kwargs
        assert "model" in kwargs, "smart pref must pass an explicit model override"
        assert kwargs["model"].model_name == "gemini-2.5-pro"

    def test_fast_pref_overrides_agent_model(self):
        """body.model_pref='fast' → agent.run gets `model=GoogleModel('gemini-2.5-flash-lite')`."""
        agent = MagicMock()
        agent.run = AsyncMock(return_value=run_result("ok"))
        with (
            patch("routes.learn.table", side_effect=self._make_table_factory()),
            patch("routes.learn.agent_for_mode", return_value=agent),
        ):
            r = self._post(model_pref="fast")
        assert r.status_code == 200
        kwargs = agent.run.call_args.kwargs
        assert "model" in kwargs
        assert kwargs["model"].model_name == "gemini-2.5-flash-lite"

    def test_no_pref_falls_through_to_agent_default(self):
        """No model_pref → agent.run gets NO `model` kwarg; agent default wins."""
        agent = MagicMock()
        agent.run = AsyncMock(return_value=run_result("ok"))
        with (
            patch("routes.learn.table", side_effect=self._make_table_factory()),
            patch("routes.learn.agent_for_mode", return_value=agent),
        ):
            r = self._post()
        assert r.status_code == 200
        kwargs = agent.run.call_args.kwargs
        assert "model" not in kwargs

    def test_smart_pref_attaches_thinking_cap(self):
        """smart pref → agent.run gets model_settings with thinking_budget=2048.

        Regression guard: a future refactor that drops the
        `_build_pro_model_settings()` call would silently restore Pro to
        unbounded dynamic thinking — the exact latency regression this PR
        fixed. Pin the budget value, not just the kwarg's presence.
        """
        from routes.learn import _PRO_THINKING_BUDGET
        agent = MagicMock()
        agent.run = AsyncMock(return_value=run_result("ok"))
        with (
            patch("routes.learn.table", side_effect=self._make_table_factory()),
            patch("routes.learn.agent_for_mode", return_value=agent),
        ):
            r = self._post(model_pref="smart")
        assert r.status_code == 200
        kwargs = agent.run.call_args.kwargs
        assert "model_settings" in kwargs
        # GoogleModelSettings is a TypedDict at the type level but a plain
        # dict at runtime; ThinkingConfig is a regular Pydantic-style object.
        budget = kwargs["model_settings"]["google_thinking_config"].thinking_budget
        assert budget == _PRO_THINKING_BUDGET
        assert _PRO_THINKING_BUDGET == 2048  # pin the literal too

    def test_no_pref_attaches_thinking_cap(self):
        """No model_pref → falls through to Pro default → still capped.

        The cap protects every path that lands on Pro, including the
        no-pref agent default — not just explicit "smart" requests.
        """
        agent = MagicMock()
        agent.run = AsyncMock(return_value=run_result("ok"))
        with (
            patch("routes.learn.table", side_effect=self._make_table_factory()),
            patch("routes.learn.agent_for_mode", return_value=agent),
        ):
            r = self._post()
        assert r.status_code == 200
        kwargs = agent.run.call_args.kwargs
        assert "model_settings" in kwargs
        assert kwargs["model_settings"]["google_thinking_config"].thinking_budget == 2048

    def test_build_pro_model_settings_uses_constant(self):
        """Direct unit test on the helper. The integration tests above
        cover the contract end-to-end via a mocked agent; this one pins
        the helper itself so a refactor of `_build_pro_model_settings`
        can't drift from `_PRO_THINKING_BUDGET` silently."""
        from routes.learn import _build_pro_model_settings, _PRO_THINKING_BUDGET
        s = _build_pro_model_settings()
        assert s["google_thinking_config"].thinking_budget == _PRO_THINKING_BUDGET

    def test_fast_pref_does_not_attach_thinking_cap(self):
        """fast pref → Lite model → no model_settings.

        Lite doesn't think, so passing a thinking_config is wasted at
        best and could be rejected by the provider. The route's
        `if model_pref != "fast":` guard is the contract; pin it.
        """
        agent = MagicMock()
        agent.run = AsyncMock(return_value=run_result("ok"))
        with (
            patch("routes.learn.table", side_effect=self._make_table_factory()),
            patch("routes.learn.agent_for_mode", return_value=agent),
        ):
            r = self._post(model_pref="fast")
        assert r.status_code == 200
        kwargs = agent.run.call_args.kwargs
        assert "model_settings" not in kwargs

    def test_use_shared_context_false_appends_constraint(self):
        """`use_shared_context=False` augments the user message with a
        constraint instructing the agent not to call class-aggregate tools."""
        agent = MagicMock()
        agent.run = AsyncMock(return_value=run_result("ok"))
        with (
            patch("routes.learn.table", side_effect=self._make_table_factory()),
            patch("routes.learn.agent_for_mode", return_value=agent),
        ):
            r = self._post(message="What is X?", use_shared_context=False)
        assert r.status_code == 200
        sent_message = agent.run.call_args.args[0]
        assert "What is X?" in sent_message
        assert "shared context" in sent_message.lower()


# ── POST /api/learn/start-session (agent path, #151a) ────────────────────────


class TestStartSessionAgent:
    """The JSON opener now runs `_start_session_agent` (chat_tutor_agent via
    _prepare_chat_run) with the same lazy PENDING_SESSIONS contract the
    legacy pipeline had, and the shared guardrail → status mapping."""

    def _post(self, **body_extra):
        return client.post("/api/learn/start-session", json={
            "user_id": "user_andres",
            "topic": "Eigenvalues",
            "mode": "socratic",
            **body_extra,
        })

    @staticmethod
    def _table_factory(mocks: dict):
        """Empty-read table dispatch that records per-table mocks so the
        lazy-session invariant (no `sessions` insert) stays assertable."""
        def factory(name):
            if name not in mocks:
                m = MagicMock()
                m.select.return_value = []
                mocks[name] = m
            return mocks[name]
        return factory

    def _stack(self, agent, mocks):
        return (
            patch("routes.learn.table", side_effect=self._table_factory(mocks)),
            patch("routes.learn.agent_for_mode", return_value=agent),
            patch("routes.learn._get_course_id_for_topic", return_value="c1"),
            patch("routes.learn.resolve_offering", return_value="off-1"),
            patch("routes.learn.get_graph", return_value={"nodes": [], "edges": []}),
        )

    def test_happy_path_stashes_pending_and_returns_greeting(self):
        from routes.learn import PENDING_SESSIONS
        PENDING_SESSIONS.clear()
        agent = MagicMock()
        agent.run = AsyncMock(return_value=run_result("Welcome! Let's begin."))
        mocks: dict = {}
        tbl, afm, topic, off, graph = self._stack(agent, mocks)
        try:
            with tbl, afm, topic, off, graph:
                r = self._post()
            assert r.status_code == 200
            data = r.json()
            assert data["initial_message"] == "Welcome! Let's begin."
            assert data["session_id"]
            assert data["graph_state"] == {"nodes": [], "edges": []}
            # Lazy contract: stashed, never written to `sessions`/`messages`.
            assert len(PENDING_SESSIONS) == 1
            stashed = PENDING_SESSIONS[data["session_id"]]
            assert stashed["assistant_reply"] == "Welcome! Let's begin."
            assert stashed["offering_id"] == "off-1"
            for name, mock in mocks.items():
                assert not mock.insert.called, f"unexpected insert into {name}"
        finally:
            PENDING_SESSIONS.clear()

    def test_usage_limit_returns_413_and_stashes_nothing(self):
        from pydantic_ai.exceptions import UsageLimitExceeded
        from routes.learn import PENDING_SESSIONS
        PENDING_SESSIONS.clear()
        agent = MagicMock()
        agent.run = AsyncMock(side_effect=UsageLimitExceeded("token cap"))
        tbl, afm, topic, off, graph = self._stack(agent, {})
        with tbl, afm, topic, off, graph:
            r = self._post()
        assert r.status_code == 413
        assert "budget" in r.json()["detail"]
        assert PENDING_SESSIONS == {}

    def test_blank_greeting_returns_502_and_stashes_nothing(self):
        """#153: a whitespace-only greeting must never be stashed as the
        session's opening bubble — it maps to the retry-friendly 502."""
        from routes.learn import PENDING_SESSIONS
        PENDING_SESSIONS.clear()
        agent = MagicMock()
        agent.run = AsyncMock(return_value=run_result("\n"))
        tbl, afm, topic, off, graph = self._stack(agent, {})
        with tbl, afm, topic, off, graph:
            r = self._post()
        assert r.status_code == 502
        assert PENDING_SESSIONS == {}


# ── POST /api/learn/action (agent path, #151a D3-A1) ─────────────────────────


class TestActionAgent:
    """hint/confused/skip now run chat_tutor_agent on the same
    "[ACTION: ...]" message the legacy pipeline sent, persist
    assistant-only, and share the guardrail → status mapping."""

    def _table_factory(self):
        def factory(name):
            mock = MagicMock()
            if name == "sessions":
                mock.select.return_value = [{"offering_id": "off1"}]
            else:
                mock.select.return_value = []
            mock.insert.return_value = []
            mock.update.return_value = []
            return mock
        return factory

    def _post(self, **body_extra):
        return client.post("/api/learn/action", json={
            "session_id": "s1",
            "user_id": "user_andres",
            "action_type": "hint",
            "mode": "socratic",
            **body_extra,
        })

    def test_happy_path_persists_assistant_only(self):
        agent = MagicMock()
        agent.run = AsyncMock(return_value=run_result("Here's a scaffold."))
        saved = []
        with (
            patch("routes.learn.table", side_effect=self._table_factory()),
            patch("routes.learn.agent_for_mode", return_value=agent),
            patch("routes.learn.save_message", side_effect=lambda *a, **k: saved.append(a)),
        ):
            r = self._post()
        assert r.status_code == 200
        assert r.json() == {"reply": "Here's a scaffold.", "graph_update": {}}
        # Today's shape: ONE assistant row, no user row for action turns.
        assert [s[1] for s in saved] == ["assistant"]
        # The agent got the same [ACTION: ...] message the legacy prompt sent.
        sent = agent.run.call_args.args[0]
        assert sent.startswith("[ACTION:")
        assert "hint" in sent

    def test_usage_limit_returns_413_and_persists_nothing(self):
        from pydantic_ai.exceptions import UsageLimitExceeded
        agent = MagicMock()
        agent.run = AsyncMock(side_effect=UsageLimitExceeded("token cap"))
        with (
            patch("routes.learn.table", side_effect=self._table_factory()),
            patch("routes.learn.agent_for_mode", return_value=agent),
            patch("routes.learn.save_message") as save,
        ):
            r = self._post()
        assert r.status_code == 413
        save.assert_not_called()

    def test_unexpected_exception_returns_502(self):
        agent = MagicMock()
        agent.run = AsyncMock(side_effect=RuntimeError("boom"))
        with (
            patch("routes.learn.table", side_effect=self._table_factory()),
            patch("routes.learn.agent_for_mode", return_value=agent),
            patch("routes.learn.save_message") as save,
        ):
            r = self._post()
        assert r.status_code == 502
        save.assert_not_called()

    def test_textless_action_turn_does_not_persist_the_prior_reply(self):
        """The action route is the third history-bearing `result.output`
        reader (`_load_message_history` feeds its run), and it persists with
        `save_message` directly — so a textless turn there would write the
        previous assistant message into the transcript a second time. Same
        narrowing, same degrade: 502, nothing persisted."""
        PRIOR = "Try walking through the base case first."
        agent = MagicMock()
        agent.run = AsyncMock(return_value=textless_run_result(PRIOR))
        with (
            patch("routes.learn.table", side_effect=self._table_factory()),
            patch("routes.learn.agent_for_mode", return_value=agent),
            patch("routes.learn.save_message") as save,
        ):
            r = self._post()
        assert r.status_code == 502
        assert PRIOR not in r.text
        save.assert_not_called()


class TestFallbackWriteStateStamp:
    """PR #472 review: the route helpers stamp `sapling_wrote` on any
    exception raised after the agent run, so the streaming fallback's
    terminal error can set retryable correctly."""

    def test_chat_via_agent_stamps_write_state_on_blank_reply(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from pydantic_ai.exceptions import UnexpectedModelBehavior

        deps = MagicMock()
        deps.graph_updates = [{"updated_nodes": [{"concept_name": "X"}]}]
        deps.mastery_changes = []
        agent = MagicMock()
        # Shape-faithful: a bare MagicMock here would iterate empty on
        # `new_messages()` and pass as a TEXTLESS turn instead of the
        # whitespace-only one this test is about.
        agent.run = AsyncMock(return_value=run_result("\n"))

        with (
            patch("routes.learn._prepare_chat_run",
                  return_value=(agent, "msg", {}, deps)),
            patch("routes.learn.record_agent_usage", side_effect=lambda r, **k: r),
        ):
            import routes.learn as learn_routes

            with pytest.raises(UnexpectedModelBehavior) as excinfo:
                asyncio.run(learn_routes._chat_via_agent(
                    user_id="u1", session_id="s1", course_id="c1",
                    mode="socratic", user_message="m", message_history=[],
                    use_shared_context=True, request_id="r1", model_pref=None,
                ))
        assert getattr(excinfo.value, "sapling_wrote", None) is True

    def test_chat_via_agent_stamp_false_without_writes(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from pydantic_ai.exceptions import UnexpectedModelBehavior

        deps = MagicMock()
        deps.graph_updates = []
        deps.mastery_changes = []
        agent = MagicMock()
        # Shape-faithful: a bare MagicMock here would iterate empty on
        # `new_messages()` and pass as a TEXTLESS turn instead of the
        # whitespace-only one this test is about.
        agent.run = AsyncMock(return_value=run_result("\n"))

        with (
            patch("routes.learn._prepare_chat_run",
                  return_value=(agent, "msg", {}, deps)),
            patch("routes.learn.record_agent_usage", side_effect=lambda r, **k: r),
        ):
            import routes.learn as learn_routes

            with pytest.raises(UnexpectedModelBehavior) as excinfo:
                asyncio.run(learn_routes._chat_via_agent(
                    user_id="u1", session_id="s1", course_id="c1",
                    mode="socratic", user_message="m", message_history=[],
                    use_shared_context=True, request_id="r1", model_pref=None,
                ))
        assert getattr(excinfo.value, "sapling_wrote", None) is False
