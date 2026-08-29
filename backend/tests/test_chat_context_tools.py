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


# ── search_course_materials ───────────────────────────────────────────────


class TestSearchCourseMaterialsUserScope:
    """#125: documents are user-scoped within a shared course. The query must
    filter on user_id, or another enrolled student's private summary/concept
    notes get decrypted into this user's LLM context."""

    @pytest.fixture(autouse=True)
    def _stub_offering_resolution(self):
        """These tests exercise scoring/decryption, not course→offering
        resolution. `documents` keys on offering_id, so the lookup is a real
        dependency now; stub it so the fake `table` above stays the only
        store these cases have to model. The resolution itself is covered by
        TestSearchCourseMaterialsOfferingScope."""
        with patch(
            "agents.tools.chat_context.user_offering_ids_for_course",
            return_value=["off_1"],
        ):
            yield

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


class TestSearchCourseMaterials:
    @pytest.fixture(autouse=True)
    def _stub_offering_resolution(self):
        """See TestSearchCourseMaterialsUserScope._stub_offering_resolution."""
        with patch(
            "agents.tools.chat_context.user_offering_ids_for_course",
            return_value=["off_1"],
        ):
            yield

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
        # Thresholds come from config.get_mastery_tier (#557): mastered
        # >= 0.75, learning >= 0.45, below that is weak (struggling or
        # unexplored). This tool used to carry its own 0.7/0.4, which is why
        # 0.4 counts as WEAK here and used to count as in-progress — the
        # divergence a student saw as "Struggling on the Tree, in-progress to
        # the tutor".
        rows = [
            {"mastery_score": 0.9},   # mastered
            {"mastery_score": 0.75},  # mastered (boundary)
            {"mastery_score": 0.5},   # learning
            {"mastery_score": 0.4},   # weak — below the 0.45 learning floor
            {"mastery_score": 0.2},   # struggling -> weak
            {"mastery_score": 0.0},   # unexplored -> weak
        ]
        with patch("agents.tools.chat_context.table") as t:
            t.return_value.select.return_value = rows
            result = _run(read_user_progress("user_andres", "course_cs101"))

        assert isinstance(result, CourseProgress)
        assert result.total_concepts == 6
        assert result.mastered_count == 2
        assert result.weak_count == 3
        assert result.in_progress_count == 1
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


class _FakeAcademicsDb:
    """A schema-faithful `table()` stand-in for the course → offering →
    documents read path.

    Schema-faithful on purpose. The older mocks in this file accept ANY
    filter and return a canned list, which is exactly how a query against a
    non-existent `documents.course_id` column survived review: the mock said
    yes, PostgREST said 400. So `documents` here rejects any filter column it
    does not actually have, and honours the ones it does.
    """

    # Every column `documents` can legitimately be filtered on by this tool.
    _DOCUMENT_COLUMNS = {"offering_id", "user_id", "deleted_at"}

    def __init__(self, *, documents, offerings, enrollments, current_term_id):
        self._documents = documents
        self._offerings = offerings
        self._enrollments = enrollments
        self._current_term_id = current_term_id
        # What the tool actually asked `documents` for — the assertions read
        # these rather than trusting the returned rows.
        self.document_filters: dict = {}
        self.document_limit: int | None = None

    def patched(self):
        """Patch both `table` references the read path goes through: the tool's
        own and `services.academics`' (offering resolution lives there)."""
        return _patch_both_tables(self._table)

    def _table(self, name):
        store = MagicMock()
        store.select.side_effect = lambda *a, **kw: self._select(name, *a, **kw)
        return store

    def _select(self, name, *_args, **kwargs):
        filters = kwargs.get("filters") or {}
        if name == "documents":
            unknown = set(filters) - self._DOCUMENT_COLUMNS
            if unknown:
                # What PostgREST really answers for a column that isn't there.
                raise RuntimeError(
                    f"column documents.{sorted(unknown)[0]} does not exist"
                )
            self.document_filters = dict(filters)
            self.document_limit = kwargs.get("limit")
            return self._select_documents(filters)
        if name == "course_offerings":
            return self._select_offerings(filters, kwargs.get("limit"))
        if name == "enrollments":
            return list(self._enrollments)
        if name == "terms":
            return [{"id": self._current_term_id}] if self._current_term_id else []
        return []

    def _select_documents(self, filters):
        allowed = None
        raw = filters.get("offering_id") or ""
        if raw.startswith("in.("):
            allowed = set(raw[4:-1].split(","))
        rows = []
        for d in self._documents:
            if filters.get("deleted_at") == "is.null" and d.get("deleted_at"):
                continue
            # A document with no explicit offering belongs to whatever the
            # query asked for (keeps the simpler cases terse).
            offering = d.get("offering_id")
            if allowed is not None and offering is not None and offering not in allowed:
                continue
            rows.append(d)
        return rows

    def _select_offerings(self, filters, limit):
        rows = list(self._offerings)
        term = filters.get("term_id")
        if term:
            rows = [o for o in rows if f"eq.{o.get('term_id')}" == term]
        if limit:
            rows = rows[:limit]
        return rows


def _patch_both_tables(factory):
    from contextlib import ExitStack

    stack = ExitStack()
    stack.enter_context(patch("agents.tools.chat_context.table", side_effect=factory))
    stack.enter_context(patch("services.academics.table", side_effect=factory))
    stack.enter_context(
        patch("agents.tools.chat_context.decrypt_if_present", side_effect=lambda v: v)
    )
    return stack


class TestSearchCourseMaterialsOfferingScope:
    """`documents` keys on `offering_id`, never `course_id` (0025 schema).

    Filtering it on `course_id` makes PostgREST 400 ("column
    documents.course_id does not exist"), and this tool's degrade-silently
    contract swallows that into `[]` — so the tutor loses EVERY course
    document with no user-visible error and answers from base knowledge
    alone. The abstract course must be resolved to the user's offerings via
    `academics.user_offering_ids_for_course` first.

    The fake below is schema-faithful on purpose: the existing mocks accept
    any filter, which is exactly how this survived.
    """

    def test_documents_are_fetched_by_offering_not_course_id(self):
        doc = {
            "id": "doc_syllabus",
            "file_name": "cs132-syllabus.pdf",
            "summary": "convex hulls and sweep lines",
            "concept_notes": [],
        }

        def _table(name):
            store = MagicMock()

            def _select(*_args, **kwargs):
                f = kwargs.get("filters", {})
                if name == "documents":
                    if "course_id" in f:
                        # What PostgREST actually does with a missing column.
                        raise RuntimeError("column documents.course_id does not exist")
                    if f.get("offering_id") == "in.(off_cs132_f26)" and \
                            f.get("user_id") == "eq.user_mine":
                        return [doc]
                    return []
                if name == "course_offerings":
                    return [{"id": "off_cs132_f26"}]
                if name == "enrollments":
                    return [{"offering_id": "off_cs132_f26"}]
                return []

            store.select.side_effect = _select
            return store

        with patch("agents.tools.chat_context.table", side_effect=_table), \
                patch("services.academics.table", side_effect=_table), \
                patch("agents.tools.chat_context.decrypt_if_present", side_effect=lambda v: v):
            result = _run(
                search_course_materials("course_cs132", "convex hull", user_id="user_mine")
            )

        assert [m.document_id for m in result] == ["doc_syllabus"], (
            "course materials must be reachable — a course_id filter on "
            "documents 400s and silently yields no materials at all"
        )

    def test_soft_deleted_documents_are_excluded(self):
        """A document the student deleted from their Library must stop
        reaching the tutor.

        `documents` is soft-deleted (routes/documents.py stamps `deleted_at`
        and every other reader filters on it — study_guide.py,
        flashcards.py). Before the offering fix this query 400'd and returned
        [] unconditionally, so the missing `deleted_at` filter was invisible;
        making the query work is exactly what exposes it. Without the filter
        a deleted file's `summary` + `concept_notes` keep getting decrypted
        into LLM context forever.
        """
        live = {
            "id": "doc_live",
            "file_name": "lecture-04.pdf",
            "summary": "convex hulls and sweep lines",
            "concept_notes": [],
            "deleted_at": None,
        }
        deleted = {
            "id": "doc_deleted",
            "file_name": "convex-hull-draft.pdf",
            "summary": "convex hulls and sweep lines, an earlier draft",
            "concept_notes": [],
            "deleted_at": "2026-08-01T00:00:00Z",
        }
        calls = _FakeAcademicsDb(
            documents=[live, deleted],
            offerings=[{"id": "off_cs132_f26", "term_id": "term_f26"}],
            enrollments=[{"offering_id": "off_cs132_f26"}],
            current_term_id="term_f26",
        )

        with calls.patched():
            result = _run(
                search_course_materials("course_cs132", "convex hull", user_id="user_mine")
            )

        assert calls.document_filters["deleted_at"] == "is.null", (
            "the documents query must filter soft-deleted rows out; every "
            "sibling reader does"
        )
        assert [m.document_id for m in result] == ["doc_live"], (
            "a deleted document must never be decrypted into tutor context"
        )

    def test_documents_uploaded_in_a_later_term_are_still_found(self):
        """The offering set must match the WRITER, not just `enrollments`.

        Documents are written with `resolve_offering(course_id, create=True)`
        — current term, enrollments never consulted. A student enrolled in
        Fall-26 who uploads next term gets `documents.offering_id` = the new
        offering and has no enrollment row for it, so an enrollment-only read
        returns [] while the Library still lists the file: the tutor loses
        every document with no visible error. `user_id` is the access
        boundary here (#125), so widening to the union of both resolvers can
        only re-include the student's OWN uploads.
        """
        doc = {
            "id": "doc_new_term",
            "file_name": "cs132-notes.pdf",
            "summary": "convex hulls and sweep lines",
            "concept_notes": [],
            "offering_id": "off_cs132_s27",   # current term — no enrollment row
            "deleted_at": None,
        }
        calls = _FakeAcademicsDb(
            documents=[doc],
            offerings=[
                {"id": "off_cs132_f26", "term_id": "term_f26"},
                {"id": "off_cs132_s27", "term_id": "term_s27"},
            ],
            enrollments=[{"offering_id": "off_cs132_f26"}],
            current_term_id="term_s27",
        )

        with calls.patched():
            result = _run(
                search_course_materials("course_cs132", "convex hull", user_id="user_mine")
            )

        assert calls.document_filters["offering_id"] == (
            "in.(off_cs132_f26,off_cs132_s27)"
        ), (
            "the enrolled offering AND the writer's current-term offering "
            "must both be in scope, in a stable order"
        )
        assert [m.document_id for m in result] == ["doc_new_term"]

    def test_documents_read_is_bounded(self):
        """The select must carry a `limit`.

        This runs on the latency-critical SSE path and EVERY returned row is
        AES-decrypted before the list is truncated to `limit` in Python, so an
        unbounded read makes a student with a large Library pay decrypt cost
        for documents that can never be returned. The bound has to exceed the
        requested count, though — ranking happens after the fetch, so
        limiting to exactly `limit` would silently turn "most relevant" into
        "most recent".
        """
        calls = _FakeAcademicsDb(
            documents=[],
            offerings=[{"id": "off_cs132_f26", "term_id": "term_f26"}],
            enrollments=[{"offering_id": "off_cs132_f26"}],
            current_term_id="term_f26",
        )

        with calls.patched():
            _run(
                search_course_materials(
                    "course_cs132", "convex hull", limit=5, user_id="user_mine"
                )
            )

        assert calls.document_limit is not None, "the documents read is unbounded"
        assert calls.document_limit > 5, (
            "the bound must leave a ranking pool larger than the result count"
        )

    def test_unresolvable_course_is_logged_not_silent(self, caplog):
        """An empty offering set is a RETRIEVAL FAILURE, not an empty course.

        The model can't tell the two apart — it sees `[]` either way and
        narrates it as "your class doesn't cover this". That is the failure
        this tool's offering fix exists to remove, and it went unnoticed
        precisely because nothing was logged. The log line must not contain a
        raw student identifier (Style Guide).
        """
        calls = _FakeAcademicsDb(
            documents=[],
            offerings=[],           # course has no offerings at all
            enrollments=[],
            current_term_id="term_f26",
        )

        with calls.patched(), caplog.at_level("WARNING"):
            result = _run(
                search_course_materials("course_cs132", "convex hull", user_id="user_mine")
            )

        assert result == []
        warnings = [
            r.getMessage() for r in caplog.records
            if r.levelname == "WARNING" and "search_course_materials" in r.getMessage()
        ]
        assert warnings, "a retrieval gap must be visible in the logs"
        assert "course_cs132" in warnings[0]
        assert "user_mine" not in warnings[0], "never log a raw student id"
