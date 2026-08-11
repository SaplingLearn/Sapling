"""
Unit tests for backend/agents/tools/chat_context.py

Covers:
  - search_course_materials: keyword scoring + top-N + drops empty rows
  - search_course_materials: decryption boundary on summary + concept_notes
  - search_course_materials: None course_id short-circuits to []
  - read_session_history: most-recent-first ordering, decrypts content
  - read_session_history: drops empty content + maps assistant->model
  - read_user_progress: aggregates mastered/weak/in_progress counts + avg
  - read_user_progress: empty graph returns zeros
  - tool wrappers: extract user_id / course_id / session_id from ctx.deps

Mocks `db.connection.table` and `services.encryption.*` via patch on the
imported references inside `agents.tools.chat_context`, mirroring the
pattern used in `tests/test_graph_read_tools.py` and the `_make_table`
factory shape from `tests/test_quiz_routes.py`.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.tools.chat_context import (
    CourseProgress,
    read_session_history,
    read_session_history_tool,
    read_user_progress,
    read_user_progress_tool,
    search_course_materials,
    search_course_materials_tool,
)


def _run(coro):
    """Drive an async coroutine to completion in a sync test."""
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _stub_offering_lookup():
    """`documents` keys on offering_id, so search_course_materials resolves
    the abstract course to the user's offerings before querying.

    That resolution is incidental to what most tests here assert (ranking,
    user scoping, decryption), so stub it to one offering. The test that
    pins the query shape asserts on it directly.
    """
    with patch(
        "agents.tools.chat_context.user_offering_ids_for_course",
        return_value=["off-1"],
    ):
        yield


# ── search_course_materials ───────────────────────────────────────────────


class TestSearchCourseMaterialsUserScope:
    """#125: documents are user-scoped within a shared course. The query must
    filter on user_id, or another enrolled student's private summary/concept
    notes get decrypted into this user's LLM context."""

    def test_does_not_return_other_users_documents(self):
        doc_mine = {
            "id": "doc_mine",
            "file_name": "my_notes.pdf",
            "summary": "my private summary about recursion",
            "concept_notes": [],
        }
        doc_other = {
            "id": "doc_other",
            "file_name": "their_notes.pdf",
            "summary": "another student's private summary about recursion",
            "concept_notes": [],
        }

        def _row_scoped_select(*_args, **kwargs):
            # Faithful row-scoped store: both docs sit in the same course, owned
            # by different users. A query scoped to me returns only mine; an
            # UNSCOPED query (pre-fix — no user_id filter) leaks the whole class.
            f = kwargs.get("filters", {})
            uid = f.get("user_id")
            if uid == "eq.user_mine":
                return [doc_mine]
            if "user_id" not in f:
                return [doc_mine, doc_other]
            return []

        with patch("agents.tools.chat_context.table") as t, patch(
            "agents.tools.chat_context.decrypt_if_present", side_effect=lambda v: v
        ):
            t.return_value.select.side_effect = _row_scoped_select
            result = _run(
                search_course_materials("course_cs101", "recursion", user_id="user_mine")
            )

        ids = {m.document_id for m in result}
        assert "doc_mine" in ids
        # Pre-fix this leaked the other student's doc into the result (and thus
        # the LLM context); the user_id scope keeps it out.
        assert "doc_other" not in ids
        # And the mechanism that keeps it out: the DB query is scoped to the
        # caller's user_id, not course_id alone.
        filters = t.return_value.select.call_args.kwargs["filters"]
        assert filters.get("user_id") == "eq.user_mine"


class TestEmptyLookupCarriesItsOwnInstruction:
    """An empty materials lookup must not become a statement about the course.

    Before this, the tool returned a bare `[]` and the model narrated it:
    "I couldn't find any information about Markov chains in the course
    materials. Let's focus on the main topics of this course." Emptiness
    means only that nothing is indexed -- most courses have no uploads --
    and course scope is never something the tutor volunteers.
    """

    def _call(self, materials):
        from agents.tools.chat_context import search_course_materials_tool

        class _Stub:
            async def course_materials(self, *_a, **_k):
                return materials

        ctx = SimpleNamespace(
            deps=SimpleNamespace(
                user_id="u1", course_id="c1", session_id="s1", retrieval=_Stub()
            )
        )
        return _run(search_course_materials_tool(ctx, "markov chains"))

    def test_empty_result_tells_the_model_not_to_mention_it(self):
        out = self._call([])
        assert out.materials == []
        g = out.guidance.lower()
        assert "says nothing about" in g
        assert "do not mention this lookup" in g
        assert "teach the topic from your own knowledge" in g

    def test_populated_result_still_forbids_scope_commentary(self):
        from agents.tools.chat_context import CourseMaterial

        out = self._call([CourseMaterial(document_id="d1", file_name="a.pdf", summary="s")])
        assert len(out.materials) == 1
        assert "never remark on what the course" in out.guidance.lower()


class TestSearchCourseMaterialsQueryShape:
    """The query must go through offering_id, not course_id.

    `documents` has no `course_id` column on any environment — the abstract
    course lives one level up. Filtering on it made PostgREST answer 400 on
    every call, and because failures degrade silently to [], the tool looked
    to the model like "this course has no materials". Students were then told
    their topic wasn't in the course. Nothing caught it: the evals use a
    fixture retrieval seam that never issues this query.
    """

    def test_filters_on_the_users_offerings_not_course_id(self):
        with patch("agents.tools.chat_context.table") as t, patch(
            "agents.tools.chat_context.user_offering_ids_for_course",
            return_value=["off-a", "off-b"],
        ) as resolve:
            t.return_value.select.return_value = []
            _run(search_course_materials("course_cs101", "recursion", user_id="user_a"))

        resolve.assert_called_once_with("user_a", "course_cs101")
        filters = t.return_value.select.call_args.kwargs["filters"]
        assert "course_id" not in filters, "documents has no course_id column"
        assert filters["offering_id"] == "in.(off-a,off-b)"
        assert filters["user_id"] == "eq.user_a"
        # Soft-deleted documents must not resurface in tutor context.
        assert filters["deleted_at"] == "is.null"

    def test_no_enrolled_offerings_short_circuits_without_querying(self):
        with patch("agents.tools.chat_context.table") as t, patch(
            "agents.tools.chat_context.user_offering_ids_for_course",
            return_value=[],
        ):
            result = _run(
                search_course_materials("course_cs101", "recursion", user_id="user_a")
            )

        assert result == []
        t.return_value.select.assert_not_called()


class TestSearchCourseMaterials:
    def test_returns_empty_when_course_id_is_none(self):
        # No table call should happen at all — cross-course search is a
        # data-leak risk we explicitly avoid.
        with patch("agents.tools.chat_context.table") as t:
            result = _run(search_course_materials(None, "recursion", user_id="user_andres"))

        assert result == []
        t.assert_not_called()

    def test_scores_by_keyword_overlap_and_caps_at_limit(self):
        # Three docs, only two have any overlap with the query "recursion
        # base case". Doc with most matches should rank first; limit=2
        # should drop the lowest-scoring entry entirely.
        rows = [
            {
                "id": "doc1",
                "file_name": "lecture1.pdf",
                "summary": "Intro to recursion and base cases in Python",
                "concept_notes": [
                    {"name": "Recursion", "description": "Function calls itself"},
                ],
            },
            {
                "id": "doc2",
                "file_name": "syllabus.pdf",
                "summary": "Course overview and grading policy",
                "concept_notes": [],
            },
            {
                "id": "doc3",
                "file_name": "hw2.pdf",
                "summary": "Recursion practice problems",
                "concept_notes": [],
            },
        ]
        with patch("agents.tools.chat_context.table") as t, patch(
            "agents.tools.chat_context.decrypt_if_present", side_effect=lambda v: v
        ):
            t.return_value.select.return_value = rows
            result = _run(
                search_course_materials(
                    "course_cs101", "recursion base case", limit=2, user_id="user_andres"
                )
            )

        assert len(result) == 2
        # doc1 hits all three of {recursion, base, case}; doc3 only hits
        # {recursion}; doc2 hits nothing and would still be eligible at
        # score 0 — but limit=2 keeps it out.
        assert result[0].document_id == "doc1"
        assert result[1].document_id == "doc3"

    def test_drops_empty_entries(self):
        # A doc with no summary and no concept_notes is useless to the
        # tutor — we drop it rather than fill a tool slot with empty.
        rows = [
            {
                "id": "doc_empty",
                "file_name": "blank.pdf",
                "summary": None,
                "concept_notes": None,
            },
            {
                "id": "doc_good",
                "file_name": "lecture.pdf",
                "summary": "Pointer arithmetic explained",
                "concept_notes": [{"name": "Pointers", "description": "..."}],
            },
        ]
        with patch("agents.tools.chat_context.table") as t, patch(
            "agents.tools.chat_context.decrypt_if_present", side_effect=lambda v: v
        ):
            t.return_value.select.return_value = rows
            result = _run(
                search_course_materials("course_cs101", "pointer", user_id="user_andres")
            )

        assert [m.document_id for m in result] == ["doc_good"]

    def test_decrypts_summary_and_concept_notes_at_boundary(self):
        # Encrypted-at-rest payloads. We verify both decrypt helpers were
        # called (encryption is per CLAUDE.md mandatory at the read
        # boundary before handing data to the LLM).
        rows = [
            {
                "id": "doc1",
                "file_name": "lecture.pdf",
                "summary": "ENC::summary_blob",
                "concept_notes": "ENC::notes_blob",
            },
        ]

        def fake_decrypt(value):
            if value == "ENC::summary_blob":
                return "decrypted summary text"
            return value

        def fake_decrypt_json(value):
            assert value == "ENC::notes_blob"
            return [{"name": "Foo", "description": "decrypted note"}]

        with patch("agents.tools.chat_context.table") as t, patch(
            "agents.tools.chat_context.decrypt_if_present", side_effect=fake_decrypt
        ) as dec_str, patch(
            "agents.tools.chat_context.decrypt_json", side_effect=fake_decrypt_json
        ) as dec_json:
            t.return_value.select.return_value = rows
            result = _run(
                search_course_materials("course_cs101", "foo", user_id="user_andres")
            )

        # Both decrypt helpers were invoked at the boundary.
        assert dec_str.called, "decrypt_if_present must run on summary"
        assert dec_json.called, "decrypt_json must run on encrypted concept_notes"
        # Plaintext is what the tool returns to the agent.
        assert result[0].summary == "decrypted summary text"
        assert result[0].concept_notes == [
            {"name": "Foo", "description": "decrypted note"}
        ]


# ── read_session_history ──────────────────────────────────────────────────


class TestReadSessionHistory:
    def test_most_recent_first_decrypts_and_maps_role(self):
        # PostgREST returns these in created_at DESC order (we ask for
        # it). We verify (1) order is preserved, (2) content is decrypted,
        # (3) legacy "assistant" role is mapped to "model".
        rows = [
            {
                "role": "user",
                "content": "ENC::user_msg",
                "created_at": "2026-05-04T12:02:00Z",
            },
            {
                "role": "assistant",  # legacy role label
                "content": "ENC::asst_msg",
                "created_at": "2026-05-04T12:01:00Z",
            },
        ]

        def fake_decrypt(value):
            return {
                "ENC::user_msg": "what is recursion?",
                "ENC::asst_msg": "It is a function that calls itself.",
            }.get(value, value)

        with patch("agents.tools.chat_context.table") as t, patch(
            "agents.tools.chat_context.decrypt_if_present", side_effect=fake_decrypt
        ) as dec:
            t.return_value.select.return_value = rows
            result = _run(read_session_history("sess_42", last_n=5))

        assert dec.called, "decrypt_if_present must run on each content"
        assert [m.role for m in result] == ["user", "model"]
        assert [m.content for m in result] == [
            "what is recursion?",
            "It is a function that calls itself.",
        ]
        # Verify the underlying read uses the right table + ordering.
        t.assert_called_with("messages")
        select_kwargs = t.return_value.select.call_args
        assert "created_at.desc" in str(select_kwargs)
        assert "sess_42" in str(select_kwargs)

    def test_drops_empty_content_and_unknown_role(self):
        rows = [
            {"role": "user", "content": None, "created_at": "t1"},
            {"role": "tool", "content": "should_drop", "created_at": "t2"},  # unknown role
            {"role": "model", "content": "keeper", "created_at": "t3"},
        ]
        with patch("agents.tools.chat_context.table") as t, patch(
            "agents.tools.chat_context.decrypt_if_present", side_effect=lambda v: v
        ):
            t.return_value.select.return_value = rows
            result = _run(read_session_history("sess_1"))

        assert [m.content for m in result] == ["keeper"]
        assert result[0].role == "model"

    def test_empty_session_id_short_circuits(self):
        # No table call when session_id is falsy.
        with patch("agents.tools.chat_context.table") as t:
            result = _run(read_session_history("", last_n=10))
        assert result == []
        t.assert_not_called()


# ── read_user_progress ────────────────────────────────────────────────────


class TestReadUserProgress:
    def test_aggregates_mastered_weak_in_progress(self):
        # Thresholds: mastered >= 0.7, weak < 0.4, in_progress in [0.4, 0.7).
        rows = [
            {"mastery_score": 0.9},   # mastered
            {"mastery_score": 0.75},  # mastered
            {"mastery_score": 0.5},   # in_progress
            {"mastery_score": 0.4},   # in_progress (boundary)
            {"mastery_score": 0.2},   # weak
            {"mastery_score": 0.0},   # weak
        ]
        with patch("agents.tools.chat_context.table") as t:
            t.return_value.select.return_value = rows
            result = _run(read_user_progress("user_andres", "course_cs101"))

        assert isinstance(result, CourseProgress)
        assert result.total_concepts == 6
        assert result.mastered_count == 2
        assert result.weak_count == 2
        assert result.in_progress_count == 2
        # avg_mastery is rounded to 4dp; sum/6 = 2.75/6 = 0.4583...
        assert abs(result.avg_mastery - round(2.75 / 6, 4)) < 1e-6

    def test_empty_graph_returns_zeros(self):
        with patch("agents.tools.chat_context.table") as t:
            t.return_value.select.return_value = []
            result = _run(read_user_progress("user_andres", "course_cs101"))

        assert result.total_concepts == 0
        assert result.mastered_count == 0
        assert result.weak_count == 0
        assert result.in_progress_count == 0
        assert result.avg_mastery == 0.0

    def test_returns_zeros_on_supabase_error(self):
        with patch("agents.tools.chat_context.table") as t:
            t.return_value.select.side_effect = RuntimeError("boom")
            result = _run(read_user_progress("user_andres", "course_cs101"))

        assert result.total_concepts == 0
        assert result.avg_mastery == 0.0

    def test_omits_course_filter_when_course_id_none(self):
        with patch("agents.tools.chat_context.table") as t:
            t.return_value.select.return_value = []
            _run(read_user_progress("user_andres", None))

        select_kwargs = t.return_value.select.call_args
        assert "course_id" not in str(select_kwargs.kwargs.get("filters") or {})


# ── tool wrappers (RunContext extraction) ─────────────────────────────────


class TestToolWrappers:
    """The wrappers' job is to pull security-sensitive ids off ctx.deps —
    the LLM must never specify user_id / course_id / session_id directly,
    or it could read another student's data."""

    def _ctx(self, **deps_kwargs):
        # Minimal RunContext stand-in: only `.deps` is read by the tools.
        deps = SimpleNamespace(
            user_id="user_andres",
            course_id="course_cs101",
            session_id="sess_42",
            supabase=None,
            request_id="req_1",
            **deps_kwargs,
        )
        return SimpleNamespace(deps=deps)

    def test_search_tool_passes_course_id_from_deps(self):
        # AsyncMock so we can `await` it inside the wrapper without
        # needing a real running event loop to attach a Future to.
        with patch(
            "agents.tools.chat_context.search_course_materials",
            new_callable=AsyncMock,
        ) as inner:
            inner.return_value = []
            _run(search_course_materials_tool(self._ctx(), "recursion", limit=3))

        # course_id AND user_id pulled from deps, not from the LLM (#125).
        inner.assert_awaited_once_with(
            "course_cs101", "recursion", 3, user_id="user_andres"
        )

    def test_history_tool_passes_session_id_from_deps(self):
        with patch(
            "agents.tools.chat_context.read_session_history",
            new_callable=AsyncMock,
        ) as inner:
            inner.return_value = []
            _run(read_session_history_tool(self._ctx(), last_n=7))

        inner.assert_awaited_once_with("sess_42", 7)

    def test_history_tool_returns_empty_when_session_id_missing(self):
        # Eval mode / batch tasks construct SaplingDeps with session_id=None.
        # Don't blow up — return [].
        ctx = SimpleNamespace(
            deps=SimpleNamespace(
                user_id="u",
                course_id="c",
                supabase=None,
                request_id="r",
                session_id=None,
            )
        )
        with patch(
            "agents.tools.chat_context.read_session_history",
            new_callable=AsyncMock,
        ) as inner:
            result = _run(read_session_history_tool(ctx, last_n=5))

        assert result == []
        inner.assert_not_called()

    def test_progress_tool_passes_user_and_course_from_deps(self):
        with patch(
            "agents.tools.chat_context.read_user_progress",
            new_callable=AsyncMock,
        ) as inner:
            inner.return_value = CourseProgress(
                total_concepts=0,
                mastered_count=0,
                weak_count=0,
                in_progress_count=0,
                avg_mastery=0.0,
            )
            _run(read_user_progress_tool(self._ctx()))

        inner.assert_awaited_once_with("user_andres", "course_cs101")
