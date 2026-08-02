"""The TutorRetrieval seam (ADR 0023, #149).

Every chat-tutor read tool must:
  - use a deps-injected TutorRetrieval when one is present (the eval path);
  - fall back to the Supabase-backed pure function when deps.retrieval is
    None (production — byte-identical to the pre-seam behavior).

Also pins that SupabaseRetrieval delegates verbatim and that the read-only
tools never touch the deps write accumulators.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from agents.deps import SaplingDeps
from agents.tools.chat_context import (
    CourseMaterial,
    CourseProgress,
    SessionMessage,
    read_session_history_tool,
    read_user_progress_tool,
    search_course_materials_tool,
)
from agents.tools.graph_read import (
    ConceptMastery,
    GraphNeighborhood,
    read_concepts_for_user_tool,
    read_graph_neighborhood_tool,
)
from agents.tools.retrieval import SupabaseRetrieval, TutorRetrieval, resolve_retrieval


def _run(coro):
    return asyncio.run(coro)


class _Ctx:
    def __init__(self, deps):
        self.deps = deps


class FakeRetrieval:
    """In-memory TutorRetrieval recording every call."""

    def __init__(self):
        self.calls: list[tuple] = []

    async def course_materials(self, course_id, query, limit, *, user_id):
        self.calls.append(("course_materials", course_id, query, limit, user_id))
        return [CourseMaterial(document_id="d1", file_name="f.pdf", summary="s")]

    async def graph_neighborhood(self, user_id, course_id, concepts, *, limit=20):
        self.calls.append(("graph_neighborhood", user_id, course_id, tuple(concepts), limit))
        return GraphNeighborhood(concepts=[], edges=[], truncated=False)

    async def concept_mastery(self, user_id, course_id):
        self.calls.append(("concept_mastery", user_id, course_id))
        return [
            ConceptMastery(concept_name=f"C{i}", mastery=i / 10) for i in range(5)
        ]

    async def progress(self, user_id, course_id):
        self.calls.append(("progress", user_id, course_id))
        return CourseProgress(
            total_concepts=1, mastered_count=0, weak_count=1,
            in_progress_count=0, avg_mastery=0.2,
        )

    async def session_history(self, session_id, last_n):
        self.calls.append(("session_history", session_id, last_n))
        return [SessionMessage(role="user", content="hi", created_at="t")]


def _deps(retrieval=None) -> SaplingDeps:
    return SaplingDeps(
        user_id="u1", course_id="c1", supabase=None, request_id="r1",
        session_id="s1", retrieval=retrieval,
    )


def test_fake_retrieval_satisfies_protocol():
    assert isinstance(FakeRetrieval(), TutorRetrieval)
    assert isinstance(SupabaseRetrieval(), TutorRetrieval)


def test_resolve_retrieval_defaults_to_supabase_impl():
    assert isinstance(resolve_retrieval(_deps()), SupabaseRetrieval)
    fake = FakeRetrieval()
    assert resolve_retrieval(_deps(fake)) is fake
    # Robust to test doubles without the field at all.
    class Bare:
        pass
    assert isinstance(resolve_retrieval(Bare()), SupabaseRetrieval)


def test_every_tool_honors_injected_retrieval():
    fake = FakeRetrieval()
    deps = _deps(fake)
    ctx = _Ctx(deps)

    with patch("agents.tools.chat_context.table") as t_cc, patch(
        "agents.tools.graph_read.table"
    ) as t_gr:
        mats = _run(search_course_materials_tool(ctx, "gradients", 3))
        hist = _run(read_session_history_tool(ctx, last_n=4))
        prog = _run(read_user_progress_tool(ctx))
        conc = _run(read_concepts_for_user_tool(ctx, limit=3))
        hood = _run(read_graph_neighborhood_tool(ctx, ["C1"], limit=7))

    t_cc.assert_not_called()
    t_gr.assert_not_called()
    assert [c[0] for c in fake.calls] == [
        "course_materials",
        "session_history",
        "progress",
        "concept_mastery",
        "graph_neighborhood",
    ]
    # Deps-injected scoping reached the impl.
    assert fake.calls[0] == ("course_materials", "c1", "gradients", 3, "u1")
    assert fake.calls[1] == ("session_history", "s1", 4)
    assert fake.calls[2] == ("progress", "u1", "c1")
    assert fake.calls[3] == ("concept_mastery", "u1", "c1")
    assert fake.calls[4] == ("graph_neighborhood", "u1", "c1", ("C1",), 7)
    assert mats[0].document_id == "d1"
    assert hist[0].content == "hi"
    assert prog.total_concepts == 1
    assert len(conc) == 3, "wrapper caps concept_mastery at the LLM-chosen limit"
    assert hood.truncated is False

    # Read-only invariant: none of these touched the write accumulators.
    assert deps.graph_updates == []
    assert deps.mastery_changes == []


def test_none_retrieval_falls_back_to_supabase_functions():
    """With deps.retrieval=None every tool bottoms out in the original pure
    function (patched here at its module) — the production path."""
    ctx = _Ctx(_deps(retrieval=None))

    async def fake_search(course_id, query, limit=5, *, user_id):
        return []

    async def fake_history(session_id, last_n=10):
        return []

    async def fake_progress(user_id, course_id):
        return CourseProgress(
            total_concepts=0, mastered_count=0, weak_count=0,
            in_progress_count=0, avg_mastery=0.0,
        )

    async def fake_concepts(user_id, course_id):
        return []

    async def fake_hood(user_id, course_id, concepts, *, limit=20):
        return GraphNeighborhood(concepts=[], edges=[], truncated=False)

    with (
        patch("agents.tools.chat_context.search_course_materials", fake_search),
        patch("agents.tools.chat_context.read_session_history", fake_history),
        patch("agents.tools.chat_context.read_user_progress", fake_progress),
        patch("agents.tools.graph_read.read_concepts_for_user", fake_concepts),
        patch("agents.tools.graph_read.read_graph_neighborhood", fake_hood),
    ):
        assert _run(search_course_materials_tool(ctx, "q")) == []
        assert _run(read_session_history_tool(ctx)) == []
        assert _run(read_user_progress_tool(ctx)).total_concepts == 0
        assert _run(read_concepts_for_user_tool(ctx)) == []
        assert _run(read_graph_neighborhood_tool(ctx, ["X"])).concepts == []


def test_supabase_retrieval_delegates_verbatim():
    """SupabaseRetrieval is a router, not a reshaper: each method awaits the
    matching pure function with identical args."""
    seen: dict[str, tuple] = {}

    async def fake_search(course_id, query, limit=5, *, user_id):
        seen["course_materials"] = (course_id, query, limit, user_id)
        return []

    async def fake_hood(user_id, course_id, concepts, *, limit=20):
        seen["graph_neighborhood"] = (user_id, course_id, tuple(concepts), limit)
        return GraphNeighborhood(concepts=[], edges=[], truncated=False)

    async def fake_concepts(user_id, course_id):
        seen["concept_mastery"] = (user_id, course_id)
        return []

    async def fake_progress(user_id, course_id):
        seen["progress"] = (user_id, course_id)
        return CourseProgress(
            total_concepts=0, mastered_count=0, weak_count=0,
            in_progress_count=0, avg_mastery=0.0,
        )

    async def fake_history(session_id, last_n=10):
        seen["session_history"] = (session_id, last_n)
        return []

    imp = SupabaseRetrieval()
    with (
        patch("agents.tools.chat_context.search_course_materials", fake_search),
        patch("agents.tools.graph_read.read_graph_neighborhood", fake_hood),
        patch("agents.tools.graph_read.read_concepts_for_user", fake_concepts),
        patch("agents.tools.chat_context.read_user_progress", fake_progress),
        patch("agents.tools.chat_context.read_session_history", fake_history),
    ):
        _run(imp.course_materials("c1", "q", 4, user_id="u1"))
        _run(imp.graph_neighborhood("u1", "c1", ["A"], limit=9))
        _run(imp.concept_mastery("u1", "c1"))
        _run(imp.progress("u1", "c1"))
        _run(imp.session_history("s1", 6))

    assert seen == {
        "course_materials": ("c1", "q", 4, "u1"),
        "graph_neighborhood": ("u1", "c1", ("A",), 9),
        "concept_mastery": ("u1", "c1"),
        "progress": ("u1", "c1"),
        "session_history": ("s1", 6),
    }
