"""Tests for the #149 deterministic graph seed block.

Covers:
  - services/graph_context.py selection (token overlap first, weakest-fill,
    deterministic ordering), serialization (no ids), char budget, and the
    empty-course / DB-error degradations;
  - routes.learn._prepare_chat_run: the GRAPH CONTEXT block is present and
    ordered after catalog/RAG, before [STUDENT QUESTION]; TUTOR_LIMITS wired;
  - both /chat routes persist the RAW body.message (the assembled prefix is
    never persisted).

(The compact_graph_context legacy de-dump and its three call-site tests
were deleted with the legacy prompt pipeline in #151a.)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app
from services.graph_context import (
    GRAPH_CONTEXT_CHAR_BUDGET,
    build_graph_context_block,
    graph_context_from_rows,
)
from services.prompt_safety import (
    UNTRUSTED_BEGIN_PREFIX,
    UNTRUSTED_END,
    untrusted_envelope_overhead,
)

client = TestClient(app)


def _concept_lines(block: str) -> list[str]:
    """The `- Concept (mastery, tier)` lines, skipping the #150 untrusted
    envelope (header, BEGIN line, notice, END line)."""
    return [line for line in block.splitlines() if line.startswith("- ")]


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
    # #150: concept lines ride inside the untrusted envelope.
    assert lines[1].startswith(UNTRUSTED_BEGIN_PREFIX)
    assert block.rstrip().endswith(UNTRUSTED_END)
    assert _concept_lines(block)[0].startswith("- Derivatives (0.42, learning)")


def test_weak_fill_after_overlap_matches():
    """Remaining slots fill weakest-mastery-first: Taylor Series (0.05)
    before Chain Rule (0.15)."""
    block = graph_context_from_rows(NODES, EDGES, "derivatives", max_concepts=3)
    names_in_order = [line.split(" (")[0][2:] for line in _concept_lines(block)]
    assert names_in_order == ["Derivatives", "Taylor Series", "Chain Rule"]


def test_deterministic_ordering_no_message_is_mastery_then_name():
    block1 = graph_context_from_rows(NODES, EDGES, "", max_concepts=12)
    block2 = graph_context_from_rows(list(reversed(NODES)), EDGES, "", max_concepts=12)
    assert block1 == block2, "input row order must not change the block"
    names = [line.split(" (")[0][2:] for line in _concept_lines(block1)]
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
    # The budget bounds the raw serialization; the #150 untrusted envelope
    # is fixed overhead on top of it.
    assert len(block) <= GRAPH_CONTEXT_CHAR_BUDGET + untrusted_envelope_overhead(
        "student graph concepts"
    )


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


def test_stream_route_saves_raw_body_message():
    """PR #469 review: the STREAMING route's _persist closure must also save
    the raw body.message — never the assembled catalog/RAG/graph prefix. The
    JSON-route twin is test_chat_route_saves_raw_body_message above; this one
    drives /chat/stream with the REAL _prepare_chat_run (so the assembled
    message genuinely differs from body.message) and a fake stream that
    invokes on_complete the way stream_agent_turn does on success."""
    saved: list[tuple] = []

    async def fake_stream(**kwargs):
        from services.agent_events import SaplingEvent
        kwargs["on_complete"]("a reply", {}, [])
        yield SaplingEvent(type="done", step="reply", message="Complete.",
                           data={"reply": "a reply", "graph_update": {}, "mastery_changes": []})

    with (
        patch("routes.learn.stream_agent_turn", fake_stream),
        patch("routes.learn.save_message", side_effect=lambda *a, **k: saved.append(a)),
        patch("routes.learn._consume_pending"),
        patch("routes.learn._get_session_offering_id", return_value=""),
        patch("routes.learn._load_message_history", return_value=[]),
        patch("routes.learn.events_service"),
    ):
        resp = client.post(
            "/api/learn/chat/stream",
            json={
                "user_id": "u1",
                "session_id": "s-raw-stream",
                "message": "What is the chain rule?",
                "mode": "socratic",
            },
        )
    assert resp.status_code == 200
    user_rows = [s for s in saved if s[1] == "user"]
    assert user_rows == [("s-raw-stream", "user", "What is the chain rule?")], (
        "the persisted user row must be the raw body.message — "
        "never the assembled catalog/RAG/graph prefix"
    )
