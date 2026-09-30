"""
Tests for the three regressions fixed in the Pydantic AI graph-tool layer.

Bug #5  (HIGH)   — retired by PKG-14b: update_mastery_tool is gone (only graded
                   evidence moves mastery after the cutover, spec §11.2).
Bug #13 (MEDIUM) — apply_graph_update_tool appends to deps.graph_updates,
                   enabling end_session to derive concepts_covered for
                   agent-path chats.
Bug #14 (MEDIUM) — ORCHESTRATOR_LIMITS is passed as usage_limits to every
                   tool-using agent .run() call in learn.py and quiz.py.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


from agents.deps import SaplingDeps
from tests.agent_run_fakes import run_result
from agents.tools.graph import (
    GraphUpdateInput,
    apply_graph_update_tool,
)


def _run(coro):
    return asyncio.run(coro)


def _make_ctx(user_id="u1", course_id="c1", graph_updates=None):
    """Minimal RunContext stand-in: only .deps is read by the tools."""
    deps = SaplingDeps(
        user_id=user_id,
        course_id=course_id,
        supabase=None,
        request_id="req-test",
        session_id="sess-test",
        graph_updates=graph_updates if graph_updates is not None else [],
    )
    return SimpleNamespace(deps=deps)


# ── Bug #13: tools append to deps.graph_updates ──────────────────────────────


class TestGraphUpdatesAccumulation:
    def test_apply_graph_update_tool_appends_new_nodes(self):
        """After a successful tool call, deps.graph_updates must contain
        the new_nodes payload so the route can persist graph_update_json."""
        ctx = _make_ctx()
        update = GraphUpdateInput(concepts=["Binary Search", "Merge Sort"])

        async def fake_to_thread(fn, *args, **kwargs):
            return []

        with patch("agents.tools.graph.asyncio.to_thread", side_effect=fake_to_thread):
            _run(apply_graph_update_tool(ctx, update))

        assert len(ctx.deps.graph_updates) == 1
        payload = ctx.deps.graph_updates[0]
        assert "new_nodes" in payload
        names = [n["concept_name"] for n in payload["new_nodes"]]
        assert "Binary Search" in names
        assert "Merge Sort" in names

    def test_apply_graph_update_tool_does_not_append_when_empty(self):
        """Empty concepts list → no DB call and no accumulation."""
        ctx = _make_ctx()
        update = GraphUpdateInput(concepts=["", "   "])

        with patch("agents.tools.graph.asyncio.to_thread") as mock_tt:
            _run(apply_graph_update_tool(ctx, update))

        mock_tt.assert_not_called()
        assert ctx.deps.graph_updates == []

    def test_multiple_tool_calls_accumulate_independently(self):
        """Two consecutive tool calls (simulating a multi-turn agent run)
        must each append their own payload — not overwrite. (PKG-14b: the
        second writer, update_mastery_tool, is gone; two concept writes.)"""
        ctx = _make_ctx()

        async def fake_to_thread(fn, *args, **kwargs):
            return []

        with patch("agents.tools.graph.asyncio.to_thread", side_effect=fake_to_thread):
            _run(apply_graph_update_tool(ctx, GraphUpdateInput(concepts=["Heaps"])))
            _run(apply_graph_update_tool(ctx, GraphUpdateInput(concepts=["Tries"])))

        assert len(ctx.deps.graph_updates) == 2
        keys = [list(gu.keys())[0] for gu in ctx.deps.graph_updates]
        assert keys == ["new_nodes", "new_nodes"]

    def test_graph_updates_merge_logic(self):
        """Simulate what learn.py does after agent.run(): merge all accumulated
        payloads into a single dict and verify every concept survives."""
        ctx = _make_ctx()

        async def fake_to_thread(fn, *args, **kwargs):
            return []

        with patch("agents.tools.graph.asyncio.to_thread", side_effect=fake_to_thread):
            _run(apply_graph_update_tool(ctx, GraphUpdateInput(concepts=["A", "B"])))
            _run(apply_graph_update_tool(ctx, GraphUpdateInput(concepts=["C"])))

        # Merge as learn.py does
        merged: dict = {}
        for gu in ctx.deps.graph_updates:
            for key, items in gu.items():
                merged.setdefault(key, []).extend(items)

        new_names = [n["concept_name"] for n in merged["new_nodes"]]
        assert set(new_names) == {"A", "B", "C"}
        assert "updated_nodes" not in merged


# ── Bug #14: ORCHESTRATOR_LIMITS wired into .run() calls ─────────────────────


class TestOrchestratorLimitsWired:
    def test_learn_chat_via_agent_passes_usage_limits(self):
        """_chat_via_agent must include usage_limits in the kwargs it passes
        to agent.run() — not silently omit it. #149: the tutor now runs
        under its own TUTOR_LIMITS (7-tool surface needs more request/tool
        headroom), not the generic ORCHESTRATOR_LIMITS."""
        from agents import TUTOR_LIMITS

        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=run_result("Great question!"))

        with (
            patch("routes.learn.agent_for_mode", return_value=mock_agent),
            patch("routes.learn._resolve_model_pref", return_value=None),
            patch("routes.learn._build_pro_model_settings", return_value={}),
        ):
            from routes.learn import _chat_via_agent
            import asyncio as _asyncio

            _asyncio.run(
                _chat_via_agent(
                    user_id="u1",
                    session_id="s1",
                    course_id=None,
                    mode="socratic",
                    user_message="What is recursion?",
                    message_history=[],
                    use_shared_context=True,
                    request_id="req-1",
                    model_pref=None,
                )
            )

        call_kwargs = mock_agent.run.call_args.kwargs
        assert "usage_limits" in call_kwargs, (
            "usage_limits not passed to agent.run() — TUTOR_LIMITS is dead code"
        )
        assert call_kwargs["usage_limits"] is TUTOR_LIMITS

    def test_quiz_via_agent_passes_usage_limits(self):
        """_quiz_via_agent must also pass usage_limits to quiz_agent.run()."""
        from agents import ORCHESTRATOR_LIMITS

        mock_quiz_agent = MagicMock()
        quiz_question = MagicMock()
        quiz_question.question_text = "Q?"
        quiz_question.options = ["A", "B", "C", "D"]
        quiz_question.correct_answer = "A"
        quiz_question.explanation = "Because A."
        quiz_result = MagicMock()
        quiz_result.output = MagicMock(questions=[quiz_question])
        mock_quiz_agent.run = AsyncMock(return_value=quiz_result)

        import asyncio as _asyncio

        with (
            patch("routes.quiz.quiz_agent", mock_quiz_agent),
            patch("routes.quiz._resolve_model_pref", return_value=None),
        ):
            from routes.quiz import _quiz_via_agent

            try:
                _asyncio.run(
                    _quiz_via_agent(
                        user_id="u1",
                        course_id="c1",
                        concept_node_id="nid1",
                        concept_name="Recursion",
                        num_questions=3,
                        difficulty="medium",
                        use_shared_context=False,
                        request_id="req-q",
                        model_pref=None,
                    )
                )
            except Exception:
                pass  # We only care that run() was called with the right kwargs

        assert mock_quiz_agent.run.called, "quiz_agent.run() was never called"
        call_kwargs = mock_quiz_agent.run.call_args.kwargs
        assert "usage_limits" in call_kwargs, (
            "usage_limits not passed to quiz_agent.run() — ORCHESTRATOR_LIMITS is dead code"
        )
        assert call_kwargs["usage_limits"] is ORCHESTRATOR_LIMITS

    def test_agent_path_save_message_receives_graph_update(self):
        """After a successful agent run, the assistant message must be saved
        with the merged graph_update so graph_update_json is not NULL and
        end_session can derive concepts_covered."""

        saved_calls = []

        def mock_save_message(session_id, role, content, graph_update=None):
            saved_calls.append({"role": role, "graph_update": graph_update})

        mock_agent = MagicMock()
        result = run_result("Here's the answer.")

        # Simulate the agent having called apply_graph_update_tool once
        def fake_run_side_effect(msg, **kwargs):
            deps = kwargs["deps"]
            deps.graph_updates.append({"new_nodes": [{"concept_name": "Recursion", "initial_mastery": 0.0}]})
            return result

        mock_agent.run = AsyncMock(side_effect=fake_run_side_effect)

        with (
            patch("routes.learn.agent_for_mode", return_value=mock_agent),
            patch("routes.learn._get_session_offering_id", return_value=None),
            patch("routes.learn._resolve_model_pref", return_value=None),
            patch("routes.learn._build_pro_model_settings", return_value={}),
            patch("routes.learn.save_message", side_effect=mock_save_message),
            patch("routes.learn._consume_pending"),
            patch("routes.learn._load_message_history", return_value=[]),
            patch("routes.learn.table") as mock_table,
            patch("routes.learn.require_self"),
        ):
            mock_table.return_value.select.return_value = []

            from main import app
            from fastapi.testclient import TestClient
            _client = TestClient(app)

            _client.post("/api/learn/chat", json={
                "session_id": "s1",
                "user_id": "u1",
                "message": "Explain recursion",
                "mode": "socratic",
                "use_shared_context": True,
                "model_pref": None,
            })

        # The assistant save_message call must carry graph_update
        assistant_calls = [c for c in saved_calls if c["role"] == "assistant"]
        assert assistant_calls, "No assistant message saved"
        graph_update = assistant_calls[0]["graph_update"]
        assert graph_update is not None, (
            "graph_update was None — concepts_covered will always be empty in end_session"
        )
        assert "new_nodes" in graph_update


class TestEndSessionConceptsCovered:
    def test_concepts_covered_populated_from_graph_update_json(self):
        """end_session must return non-empty concepts_covered when messages
        have graph_update_json set — this is the fix for bug #13."""
        from routes.learn import end_session

        graph_update_payload = {
            "new_nodes": [{"concept_name": "BFS"}],
            "updated_nodes": [{"concept_name": "DFS"}],
        }

        session_row = {"user_id": "u1", "started_at": "2026-01-01T10:00:00"}
        msg_rows = [{"graph_update_json": graph_update_payload}]

        def table_factory(name):
            m = MagicMock()
            if name == "sessions":
                m.select.return_value = [session_row]
                m.update.return_value = None
            elif name == "messages":
                m.select.return_value = msg_rows
            else:
                m.select.return_value = []
                m.update.return_value = None
            return m

        mock_request = MagicMock()

        with (
            patch("routes.learn.table", side_effect=table_factory),
            patch("routes.learn.require_self"),
            patch("routes.learn.get_session_user_id", return_value="u1"),
            patch("routes.learn.encrypt_json", return_value="{}"),
        ):
            from models import EndSessionBody
            body = EndSessionBody(session_id="s1", user_id="u1")
            result = end_session(body, mock_request)

        covered = result["summary"]["concepts_covered"]
        assert set(covered) == {"BFS", "DFS"}, (
            f"Expected {{'BFS', 'DFS'}}, got {covered!r} — "
            "end_session is not reading graph_update_json correctly"
        )
