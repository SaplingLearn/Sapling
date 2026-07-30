"""Tests for the #149 deterministic graph seed block + legacy de-dump.

Covers:
  - services/graph_context.py selection (token overlap first, weakest-fill,
    deterministic ordering), serialization (no ids), char budget, and the
    empty-course / DB-error degradations;
  - compact_graph_context course scoping over a get_graph payload (other
    courses' concepts and subject-root hubs excluded — the old
    json.dumps(get_graph(...)) leaked both);
  - routes.learn._prepare_chat_run: the GRAPH CONTEXT block is present and
    ordered after catalog/RAG, before [STUDENT QUESTION]; TUTOR_LIMITS wired;
  - the /chat route persists the RAW body.message (the assembled prefix is
    never persisted);
  - all three legacy call sites hand build_system_prompt the compact
    serialization, not a JSON dump.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app
from services.graph_context import (
    GRAPH_CONTEXT_CHAR_BUDGET,
    build_graph_context_block,
    compact_graph_context,
    graph_context_from_rows,
)

client = TestClient(app)


def _node(nid, name, mastery, tier="learning", course="c1"):
    return {
        "id": nid,
        "concept_name": name,
        "mastery_score": mastery,
        "mastery_tier": tier,
        "course_id": course,
    }


NODES = [
    _node("n1", "Derivatives", 0.42),
    _node("n2", "Limits", 0.78, "mastered"),
    _node("n3", "Chain Rule", 0.15, "struggling"),
    _node("n4", "Integrals", 0.30, "struggling"),
    _node("n5", "Taylor Series", 0.05, "unexplored"),
]

EDGES = [
    {"source_node_id": "n1", "target_node_id": "n2", "relationship_type": "related"},
    {"source_node_id": "n1", "target_node_id": "n3", "relationship_type": "related"},
]


# ── graph_context_from_rows: selection + serialization ────────────────────


def test_overlap_selection_puts_message_matched_concepts_first():
    block = graph_context_from_rows(
        NODES, EDGES, "help me with derivatives please", max_concepts=3
    )
    lines = block.splitlines()
    assert lines[0].startswith("GRAPH CONTEXT")
    assert lines[1].startswith("- Derivatives (0.42, learning)")


def test_weak_fill_after_overlap_matches():
    """Remaining slots fill weakest-mastery-first: Taylor Series (0.05)
    before Chain Rule (0.15)."""
    block = graph_context_from_rows(NODES, EDGES, "derivatives", max_concepts=3)
    names_in_order = [
        line.split(" (")[0][2:] for line in block.splitlines()[1:]
    ]
    assert names_in_order == ["Derivatives", "Taylor Series", "Chain Rule"]


def test_deterministic_ordering_no_message_is_mastery_then_name():
    block1 = graph_context_from_rows(NODES, EDGES, "", max_concepts=12)
    block2 = graph_context_from_rows(list(reversed(NODES)), EDGES, "", max_concepts=12)
    assert block1 == block2, "input row order must not change the block"
    names = [line.split(" (")[0][2:] for line in block1.splitlines()[1:]]
    assert names == ["Taylor Series", "Chain Rule", "Integrals", "Derivatives", "Limits"]


def test_edges_render_only_among_selected_and_grouped_by_type():
    block = graph_context_from_rows(NODES, EDGES, "derivatives limits chain rule")
    deriv_line = next(
        line for line in block.splitlines() if line.startswith("- Derivatives")
    )
    assert "related: Limits, Chain Rule" in deriv_line or (
        "related:" in deriv_line and "Limits" in deriv_line and "Chain Rule" in deriv_line
    )


def test_no_ids_in_block():
    block = graph_context_from_rows(NODES, EDGES, "derivatives")
    for nid in ("n1", "n2", "n3", "n4", "n5"):
        assert nid not in block


def test_char_budget_enforced():
    many = [
        _node(f"m{i}", f"Concept Number {i} With A Rather Long Name Indeed", 0.5)
        for i in range(200)
    ]
    block = graph_context_from_rows(many, [], "", max_concepts=200)
    assert len(block) <= GRAPH_CONTEXT_CHAR_BUDGET


# ── build_graph_context_block (DB-backed) ─────────────────────────────────


def test_empty_course_returns_empty_without_reads():
    with patch("services.graph_context.table") as t:
        assert build_graph_context_block("u1", "", "hi") == ""
        assert build_graph_context_block("u1", None, "hi") == ""
    t.assert_not_called()


def test_no_nodes_returns_empty():
    with patch("services.graph_context.table") as t:
        t.return_value.select.return_value = []
        assert build_graph_context_block("u1", "c1", "hi") == ""


def test_db_error_degrades_to_empty():
    with patch("services.graph_context.table") as t:
        t.return_value.select.side_effect = RuntimeError("boom")
        assert build_graph_context_block("u1", "c1", "hi") == ""


def test_db_backed_block_selects_and_renders():
    def factory(name):
        m = MagicMock()
        m.select.return_value = NODES if name == "graph_nodes" else EDGES
        return m

    with patch("services.graph_context.table", side_effect=factory):
        block = build_graph_context_block("u1", "c1", "derivatives")
    assert block.startswith("GRAPH CONTEXT")
    assert "- Derivatives (0.42, learning)" in block


# ── compact_graph_context (legacy de-dump) ────────────────────────────────


def _graph_payload():
    """A get_graph-shaped payload: two courses + a subject-root hub."""
    return {
        "nodes": [
            _node("n1", "Derivatives", 0.42, course="c1"),
            _node("n2", "Limits", 0.78, "mastered", course="c1"),
            _node("x1", "French Revolution", 0.9, "mastered", course="c2"),
            {
                "id": "subject_root__c1",
                "concept_name": "MATH - Calculus",
                "mastery_score": 0.6,
                "mastery_tier": "subject_root",
                "course_id": "c1",
                "is_subject_root": True,
            },
        ],
        "edges": [
            {"source": "n2", "target": "n1", "relationship_type": "prerequisite"},
            {"source": "subject_root__c1", "target": "n1", "relationship_type": "related"},
            {"source": "x1", "target": "n1", "relationship_type": "related"},
        ],
        "stats": {},
    }


def test_compact_graph_context_scopes_to_course_and_drops_roots():
    block = compact_graph_context(_graph_payload(), "c1")
    assert "Derivatives" in block and "Limits" in block
    assert "French Revolution" not in block, "other-course concept leaked"
    assert "subject_root" not in block and "MATH - Calculus" not in block
    assert "prerequisite: Derivatives" in block  # edge among selected renders
    # It is compact text, not a JSON dump.
    assert not block.lstrip().startswith("{")
    assert '"nodes"' not in block and '"mastery_score"' not in block


def test_compact_graph_context_empty_course_or_graph():
    assert compact_graph_context(_graph_payload(), "") == ""
    assert compact_graph_context({"nodes": [], "edges": []}, "c1") == ""
    assert compact_graph_context({}, "c1") == ""


# ── _prepare_chat_run: seed block presence + ordering ─────────────────────


def _prepare(user_message="What is the chain rule?", course_id="c1", **overrides):
    from routes.learn import _prepare_chat_run

    kwargs = dict(
        user_id="u1",
        session_id="s1",
        course_id=course_id,
        mode="socratic",
        user_message=user_message,
        message_history=[],
        use_shared_context=True,
        request_id="r1",
        model_pref="fast",  # skip _build_pro_model_settings
    )
    kwargs.update(overrides)
    return _prepare_chat_run(**kwargs)


def test_prepare_chat_run_orders_catalog_rag_graph_then_question():
    with (
        patch("routes.learn._get_course_info", return_value={"course_code": "CS101"}),
        patch("routes.learn._get_catalog_chunk", return_value="CATALOG-TEXT"),
        patch("services.rag_service.retrieve_chunks", return_value=[{"c": 1}]),
        patch("services.rag_service.format_rag_context", return_value="RAG-BLOCK"),
        patch(
            "services.graph_context.build_graph_context_block",
            return_value="GRAPH CONTEXT (x):\n- Chain Rule (0.15, struggling)",
        ) as gb,
        patch("routes.learn._resolve_model_pref", return_value=None),
    ):
        agent, assembled, run_kwargs, deps = _prepare()

    gb.assert_called_once_with("u1", "c1", "What is the chain rule?")
    i_cat = assembled.index("CATALOG-TEXT")
    i_rag = assembled.index("RAG-BLOCK")
    i_graph = assembled.index("GRAPH CONTEXT")
    i_q = assembled.index("[STUDENT QUESTION]")
    assert i_cat < i_rag < i_graph < i_q
    assert assembled.endswith("What is the chain rule?")


def test_prepare_chat_run_omits_graph_block_when_empty():
    with (
        patch("routes.learn._get_course_info", return_value={"course_code": None}),
        patch("services.graph_context.build_graph_context_block", return_value=""),
        patch("routes.learn._resolve_model_pref", return_value=None),
    ):
        agent, assembled, run_kwargs, deps = _prepare()
    assert "GRAPH CONTEXT" not in assembled
    assert assembled == "What is the chain rule?"


def test_prepare_chat_run_no_course_never_builds_graph_block():
    with (
        patch("services.graph_context.build_graph_context_block") as gb,
        patch("routes.learn._resolve_model_pref", return_value=None),
    ):
        _prepare(course_id="")
    gb.assert_not_called()


def test_prepare_chat_run_uses_tutor_limits():
    from agents import TUTOR_LIMITS

    with (
        patch("services.graph_context.build_graph_context_block", return_value=""),
        patch("routes.learn._resolve_model_pref", return_value=None),
    ):
        _agent, _assembled, run_kwargs, _deps = _prepare(course_id="")
    assert run_kwargs["usage_limits"] is TUTOR_LIMITS


# ── /chat persists the RAW message, never the assembled prefix ────────────


def test_chat_route_saves_raw_body_message():
    saved: list[tuple] = []

    async def fake_chat_via_agent(**kwargs):
        return {"reply": "ok!", "graph_update": {}, "mastery_changes": []}

    with (
        patch("routes.learn._chat_via_agent", side_effect=fake_chat_via_agent),
        patch("routes.learn.save_message", side_effect=lambda *a, **k: saved.append(a)),
        patch("routes.learn._get_session_offering_id", return_value=""),
        patch("routes.learn._load_message_history", return_value=[]),
        patch("routes.learn.events_service"),
    ):
        resp = client.post(
            "/api/learn/chat",
            json={
                "user_id": "u1",
                "session_id": "s-raw",
                "message": "What is the chain rule?",
                "mode": "socratic",
            },
        )
    assert resp.status_code == 200
    user_rows = [s for s in saved if s[1] == "user"]
    assert user_rows == [("s-raw", "user", "What is the chain rule?")], (
        "the persisted user row must be the raw body.message — "
        "never the assembled catalog/RAG/graph prefix"
    )


# ── legacy call sites hand build_system_prompt the compact block ──────────


def test_build_system_prompt_graph_section_is_the_compact_serialization():
    """The real template: the compact block lands under 'Current Knowledge
    Graph:' verbatim, and no raw graph-JSON shape appears anywhere."""
    from routes.learn import build_system_prompt

    compact = compact_graph_context(_graph_payload(), "c1")
    with patch("routes.learn._get_course_info", return_value={"course_code": "", "course_name": ""}):
        prompt = build_system_prompt("socratic", "Student", compact)
    assert compact in prompt
    assert "Current Knowledge Graph:" in prompt
    for json_shape in ('"nodes"', '"mastery_score"', '"mastery_events"', '"subject_root__'):
        assert json_shape not in prompt


def _legacy_graph_stack(stack, extra=()):
    """Enter the shared legacy-path patches (plus `extra`) on an ExitStack."""
    for p in (
        patch("routes.learn.get_user_name", return_value="Student"),
        patch("routes.learn.get_graph", return_value=_graph_payload()),
        patch("routes.learn._get_course_documents", return_value=[]),
        patch("routes.learn.call_gemini_multiturn", return_value="hi there"),
        patch("routes.learn.apply_graph_update", return_value=[]),
        patch("routes.learn.save_message"),
        patch("routes.learn.events_service"),
        *extra,
    ):
        stack.enter_context(p)


def _assert_compact(graph_json_arg: str):
    assert graph_json_arg.startswith("GRAPH CONTEXT"), graph_json_arg[:80]
    assert "French Revolution" not in graph_json_arg, "other-course leak"
    assert '"nodes"' not in graph_json_arg
    # Never a JSON document.
    try:
        json.loads(graph_json_arg)
        raise AssertionError("legacy prompt still receives raw JSON")
    except (json.JSONDecodeError, ValueError):
        pass


def test_legacy_chat_uses_compact_graph_context():
    import asyncio

    from routes.learn import _legacy_chat
    from models import ChatBody

    captured = {}

    def spy_build(mode, student_name, graph_json, **kwargs):
        captured["graph_json"] = graph_json
        return "SYS"

    body = ChatBody(
        user_id="u1", session_id="s1", message="hi", mode="socratic"
    )
    from contextlib import ExitStack

    with ExitStack() as stack:
        _legacy_graph_stack(stack, extra=(
            patch("routes.learn.get_conversation_history", return_value=[{"role": "user", "content": "hi"}]),
            patch("routes.learn._get_session_offering_id", return_value="off1"),
            patch("routes.learn.offering_course_id", return_value="c1"),
            patch("routes.learn._get_course_info", return_value={"course_code": ""}),
            patch("routes.learn.build_system_prompt", side_effect=spy_build),
        ))
        asyncio.run(_legacy_chat(body, MagicMock()))

    _assert_compact(captured["graph_json"])


def test_start_session_legacy_uses_compact_graph_context():
    from routes.learn import _start_session_legacy
    from models import StartSessionBody

    captured = {}

    def spy_build(mode, student_name, graph_json, **kwargs):
        captured["graph_json"] = graph_json
        return "SYS"

    body = StartSessionBody(user_id="u1", topic="Calculus", mode="socratic", course_id="c1")
    from contextlib import ExitStack

    with ExitStack() as stack:
        _legacy_graph_stack(stack, extra=(
            patch("routes.learn.resolve_offering", return_value="off1"),
            patch("routes.learn.build_system_prompt", side_effect=spy_build),
            patch("routes.learn.extract_graph_update", return_value=("hi", {})),
        ))
        _start_session_legacy(body)

    _assert_compact(captured["graph_json"])


def test_action_route_uses_compact_graph_context():
    captured = {}

    def spy_build(mode, student_name, graph_json, **kwargs):
        captured["graph_json"] = graph_json
        return "SYS"

    from contextlib import ExitStack

    with ExitStack() as stack:
        _legacy_graph_stack(stack, extra=(
            patch("routes.learn.get_conversation_history", return_value=[]),
            patch("routes.learn._get_session_offering_id", return_value="off1"),
            patch("routes.learn.offering_course_id", return_value="c1"),
            patch("routes.learn.build_system_prompt", side_effect=spy_build),
            patch("routes.learn.extract_graph_update", return_value=("hi", {})),
        ))
        resp = client.post(
            "/api/learn/action",
            json={
                "user_id": "u1",
                "session_id": "s1",
                "action_type": "hint",
                "mode": "socratic",
            },
        )
    assert resp.status_code == 200
    _assert_compact(captured["graph_json"])
