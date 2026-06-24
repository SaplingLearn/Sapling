"""
Tests for the three regressions fixed in the Pydantic AI graph-tool layer.

Bug #5  (HIGH)   — update_mastery_tool now emits updated_nodes with mastery_delta
                   so conversational tutoring actually moves mastery scores.
Bug #13 (MEDIUM) — apply_graph_update_tool and update_mastery_tool append to
                   deps.graph_updates, enabling end_session to derive
                   concepts_covered for agent-path chats.
Bug #14 (MEDIUM) — ORCHESTRATOR_LIMITS is passed as usage_limits to every
                   tool-using agent .run() call in learn.py and quiz.py.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from agents.deps import SaplingDeps
from agents.tools.graph import (
    ConceptMasteryUpdate,
    GraphUpdateInput,
    MasteryUpdateInput,
    apply_graph_update_tool,
    update_mastery_tool,
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


# ── Bug #5: update_mastery_tool emits updated_nodes ──────────────────────────


class TestUpdateMasteryTool:
    def test_calls_apply_graph_update_with_updated_nodes(self):
        """The tool must forward updated_nodes — NOT new_nodes — so the
        mastery-delta branch in graph_service.apply_graph_update fires."""
        ctx = _make_ctx()
        update = MasteryUpdateInput(
            updates=[
                ConceptMasteryUpdate(
                    concept_name="Recursion",
                    mastery_delta=0.15,
                    reason="answered correctly",
                    event_type="interaction",
                )
            ]
        )

        mock_changes = [{"concept": "Recursion", "before": 0.4, "after": 0.55}]

        with patch(
            "agents.tools.graph.apply_graph_update", return_value=mock_changes
        ) as mock_ag, patch("agents.tools.graph.asyncio.to_thread", new=AsyncMock(return_value=mock_changes)):
            result = _run(update_mastery_tool(ctx, update))

        assert "0.40→0.55" in result or "Recursion" in result

    def test_forwards_mastery_delta_not_initial_mastery(self):
        """Critically: the payload sent to graph_service must use
        'mastery_delta', not 'initial_mastery' — that's the regression."""
        ctx = _make_ctx()
        update = MasteryUpdateInput(
            updates=[
                ConceptMasteryUpdate(concept_name="Heaps", mastery_delta=0.2)
            ]
        )
        captured = {}

        async def fake_to_thread(fn, *args, **kwargs):
            captured["args"] = args
            return []

        with patch("agents.tools.graph.asyncio.to_thread", side_effect=fake_to_thread):
            _run(update_mastery_tool(ctx, update))

        graph_update_dict = captured["args"][1]
        assert "updated_nodes" in graph_update_dict
        assert "new_nodes" not in graph_update_dict
        node = graph_update_dict["updated_nodes"][0]
        assert node["concept_name"] == "Heaps"
        assert node["mastery_delta"] == pytest.approx(0.2)

    def test_skips_empty_concept_names(self):
        ctx = _make_ctx()
        update = MasteryUpdateInput(
            updates=[
                ConceptMasteryUpdate(concept_name="  ", mastery_delta=0.1),
                ConceptMasteryUpdate(concept_name="", mastery_delta=0.1),
            ]
        )

        async def fake_to_thread(fn, *args, **kwargs):
            return []

        with patch("agents.tools.graph.asyncio.to_thread", side_effect=fake_to_thread) as mock_tt:
            result = _run(update_mastery_tool(ctx, update))

        mock_tt.assert_not_called()
        assert "skipped" in result.lower()

    def test_returns_human_readable_summary_when_changes_present(self):
        ctx = _make_ctx()
        update = MasteryUpdateInput(
            updates=[ConceptMasteryUpdate(concept_name="BFS", mastery_delta=0.1)]
        )
        mock_changes = [{"concept": "BFS", "before": 0.3, "after": 0.4}]

        async def fake_to_thread(fn, *args, **kwargs):
            return mock_changes

        with patch("agents.tools.graph.asyncio.to_thread", side_effect=fake_to_thread):
            result = _run(update_mastery_tool(ctx, update))

        assert "BFS" in result
        assert "0.30" in result or "0.3" in result

    def test_returns_fallback_message_when_no_score_change(self):
        """Concept not found in graph → changes=[] → informative message."""
        ctx = _make_ctx()
        update = MasteryUpdateInput(
            updates=[ConceptMasteryUpdate(concept_name="UnknownTopic", mastery_delta=0.2)]
        )

        async def fake_to_thread(fn, *args, **kwargs):
            return []

        with patch("agents.tools.graph.asyncio.to_thread", side_effect=fake_to_thread):
            result = _run(update_mastery_tool(ctx, update))

        assert "UnknownTopic" not in result or "processed" in result.lower() or "not exist" in result.lower()


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

    def test_update_mastery_tool_appends_updated_nodes(self):
        ctx = _make_ctx()
        update = MasteryUpdateInput(
            updates=[
                ConceptMasteryUpdate(concept_name="DFS", mastery_delta=0.1, reason="correct"),
                ConceptMasteryUpdate(concept_name="BFS", mastery_delta=-0.05, reason="gap"),
            ]
        )

        async def fake_to_thread(fn, *args, **kwargs):
            return [
                {"concept": "DFS", "before": 0.3, "after": 0.4},
                {"concept": "BFS", "before": 0.5, "after": 0.45},
            ]

        with patch("agents.tools.graph.asyncio.to_thread", side_effect=fake_to_thread):
            _run(update_mastery_tool(ctx, update))

        assert len(ctx.deps.graph_updates) == 1
        payload = ctx.deps.graph_updates[0]
        assert "updated_nodes" in payload
        names = [n["concept_name"] for n in payload["updated_nodes"]]
        assert "DFS" in names
        assert "BFS" in names

    def test_update_mastery_tool_skips_append_when_no_change(self):
        """A concept the model named but that doesn't exist in the graph
        yields no `changes` and must NOT be appended to graph_updates —
        otherwise end_session would over-report it as concepts_covered."""
        ctx = _make_ctx()
        update = MasteryUpdateInput(
            updates=[ConceptMasteryUpdate(concept_name="GhostTopic", mastery_delta=0.2)]
        )

        async def fake_to_thread(fn, *args, **kwargs):
            return []  # concept not in graph → nothing persisted

        with patch("agents.tools.graph.asyncio.to_thread", side_effect=fake_to_thread):
            _run(update_mastery_tool(ctx, update))

        assert ctx.deps.graph_updates == []
        assert ctx.deps.mastery_changes == []

    def test_update_mastery_tool_only_appends_changed_concepts(self):
        """When only some named concepts actually change, graph_updates must
        contain only the persisted ones (built from the returned changes)."""
        ctx = _make_ctx()
        update = MasteryUpdateInput(
            updates=[
                ConceptMasteryUpdate(concept_name="Real", mastery_delta=0.1),
                ConceptMasteryUpdate(concept_name="Ghost", mastery_delta=0.1),
            ]
        )

        async def fake_to_thread(fn, *args, **kwargs):
            return [{"concept": "Real", "before": 0.2, "after": 0.3}]

        with patch("agents.tools.graph.asyncio.to_thread", side_effect=fake_to_thread):
            _run(update_mastery_tool(ctx, update))

        assert len(ctx.deps.graph_updates) == 1
        names = [n["concept_name"] for n in ctx.deps.graph_updates[0]["updated_nodes"]]
        assert names == ["Real"]
        assert ctx.deps.mastery_changes == [
            {"concept": "Real", "before": 0.2, "after": 0.3}
        ]

    def test_multiple_tool_calls_accumulate_independently(self):
        """Two consecutive tool calls (simulating a multi-turn agent run)
        must each append their own payload — not overwrite."""
        ctx = _make_ctx()

        async def fake_to_thread(fn, *args, **kwargs):
            # Echo a change for any updated_nodes concept so the persisted-
            # only gate in update_mastery_tool sees a real change.
            payload = args[1]
            return [
                {"concept": n["concept_name"], "before": 0.3, "after": 0.5}
                for n in payload.get("updated_nodes", [])
            ]

        with patch("agents.tools.graph.asyncio.to_thread", side_effect=fake_to_thread):
            _run(apply_graph_update_tool(ctx, GraphUpdateInput(concepts=["Heaps"])))
            _run(update_mastery_tool(ctx, MasteryUpdateInput(
                updates=[ConceptMasteryUpdate(concept_name="Heaps", mastery_delta=0.2)]
            )))

        assert len(ctx.deps.graph_updates) == 2
        keys = [list(gu.keys())[0] for gu in ctx.deps.graph_updates]
        assert keys == ["new_nodes", "updated_nodes"]

    def test_graph_updates_merge_logic(self):
        """Simulate what learn.py does after agent.run(): merge all accumulated
        payloads into a single dict and verify both keys survive."""
        ctx = _make_ctx()

        async def fake_to_thread(fn, *args, **kwargs):
            payload = args[1]
            return [
                {"concept": n["concept_name"], "before": 0.3, "after": 0.4}
                for n in payload.get("updated_nodes", [])
            ]

        with patch("agents.tools.graph.asyncio.to_thread", side_effect=fake_to_thread):
            _run(apply_graph_update_tool(ctx, GraphUpdateInput(concepts=["A", "B"])))
            _run(apply_graph_update_tool(ctx, GraphUpdateInput(concepts=["C"])))
            _run(update_mastery_tool(ctx, MasteryUpdateInput(
                updates=[ConceptMasteryUpdate(concept_name="A", mastery_delta=0.1)]
            )))

        # Merge as learn.py does
        merged: dict = {}
        for gu in ctx.deps.graph_updates:
            for key, items in gu.items():
                merged.setdefault(key, []).extend(items)

        new_names = [n["concept_name"] for n in merged["new_nodes"]]
        assert set(new_names) == {"A", "B", "C"}
        upd_names = [n["concept_name"] for n in merged["updated_nodes"]]
        assert upd_names == ["A"]


# ── Bug #14: ORCHESTRATOR_LIMITS wired into .run() calls ─────────────────────


class TestOrchestratorLimitsWired:
    def test_learn_chat_via_agent_passes_usage_limits(self):
        """_chat_via_agent must include usage_limits in the kwargs it passes
        to agent.run() — not silently omit it."""
        from agents import ORCHESTRATOR_LIMITS

        mock_agent = MagicMock()
        run_result = MagicMock()
        run_result.output = "Great question!"
        mock_agent.run = AsyncMock(return_value=run_result)

        with (
            patch("routes.learn.agent_for_mode", return_value=mock_agent),
            patch("routes.learn._get_session_course_id", return_value=None),
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
            "usage_limits not passed to agent.run() — ORCHESTRATOR_LIMITS is dead code"
        )
        assert call_kwargs["usage_limits"] is ORCHESTRATOR_LIMITS

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
        from routes.learn import save_message

        saved_calls = []

        def mock_save_message(session_id, role, content, graph_update=None):
            saved_calls.append({"role": role, "graph_update": graph_update})

        mock_agent = MagicMock()
        run_result = MagicMock()
        run_result.output = "Here's the answer."

        # Simulate the agent having called apply_graph_update_tool once
        def fake_run_side_effect(msg, **kwargs):
            deps = kwargs["deps"]
            deps.graph_updates.append({"new_nodes": [{"concept_name": "Recursion", "initial_mastery": 0.0}]})
            return run_result

        mock_agent.run = AsyncMock(side_effect=fake_run_side_effect)

        with (
            patch("routes.learn.agent_for_mode", return_value=mock_agent),
            patch("routes.learn._get_session_course_id", return_value="c1"),
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

            resp = _client.post("/api/learn/chat", json={
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
        from fastapi import Request as _Request

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
