"""
Unit tests for routes/study_guide.py

Covers:
  - GET  /api/study-guide/{user_id}/exams           → get_exams
  - GET  /api/study-guide/{user_id}/cached          → get_cached_guides
  - GET  /api/study-guide/{user_id}/guide           → get_guide (cached + fresh)
  - POST /api/study-guide/regenerate                → regenerate_guide
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

USER_ID = "user_test"
COURSE_ID = "course_1"
EXAM_ID = "exam_1"


def _agent_run_returning(content):
    """AsyncMock standing in for study_guide_agent.run; its .output.model_dump()
    yields the given legacy-dict content."""
    return AsyncMock(
        return_value=SimpleNamespace(
            output=SimpleNamespace(model_dump=lambda: content)
        )
    )


# ── GET /api/study-guide/{user_id}/exams ─────────────────────────────────────

class TestGetExams:
    @staticmethod
    def _exam_stack(all_assignments, captured):
        """A table() side_effect (shared by routes.study_guide + services.academics)
        that resolves course_1 → offering off1 → enrollment enr1, and records the
        filters the assignments query is issued with in ``captured``."""

        def table_side_effect(name):
            m = MagicMock()
            if name == "course_offerings":
                m.select.return_value = [{"id": "off1"}]
            elif name == "enrollments":
                m.select.return_value = [{"id": "enr1", "offering_id": "off1"}]
            elif name == "assignments":
                def _select(cols, filters=None, order=None, limit=None):
                    captured["filters"] = filters or {}
                    return all_assignments
                m.select.side_effect = _select
            else:
                m.select.return_value = []
            return m

        return table_side_effect

    def test_filters_by_type_and_keywords(self):
        all_assignments = [
            {"id": "a1", "title": "Midterm Exam", "due_date": "2026-04-01", "assignment_type": "exam"},
            {"id": "a2", "title": "Homework 3",  "due_date": "2026-04-02", "assignment_type": "homework"},
            {"id": "a3", "title": "Reading quiz", "due_date": "2026-04-03", "assignment_type": "other"},
            {"id": "a4", "title": "Project B",   "due_date": "2026-04-04", "assignment_type": "project"},
        ]
        captured = {}
        side_effect = self._exam_stack(all_assignments, captured)
        with patch("routes.study_guide.table", side_effect=side_effect), \
             patch("services.academics.table", side_effect=side_effect):
            r = client.get(f"/api/study-guide/{USER_ID}/exams?course_id={COURSE_ID}")
        assert r.status_code == 200
        slugs = {e["title"] for e in r.json()["exams"]}
        assert "Midterm Exam" in slugs
        assert "Reading quiz" in slugs  # title contains "quiz"
        assert "Homework 3" not in slugs
        assert "Project B" not in slugs

    def test_scopes_assignments_by_enrollment_id_not_user_id(self):
        """Regression (F6): the assignments table is enrollment-keyed (no user_id/
        course_id column). Filtering by user_id makes PostgREST 500 the request, so
        study guides were bricked for every course. The query must scope by
        enrollment_id resolved from the abstract course_id."""
        all_assignments = [
            {"id": "a1", "title": "Final Exam", "due_date": "2026-05-01", "assignment_type": "exam"},
        ]
        captured = {}
        side_effect = self._exam_stack(all_assignments, captured)
        with patch("routes.study_guide.table", side_effect=side_effect), \
             patch("services.academics.table", side_effect=side_effect):
            r = client.get(f"/api/study-guide/{USER_ID}/exams?course_id={COURSE_ID}")
        assert r.status_code == 200
        # The assignments read filters by enrollment_id (the user's enrollment in
        # an offering of course_1), never by the non-existent user_id column.
        assert captured["filters"] == {"enrollment_id": "in.(enr1)"}
        assert "user_id" not in captured["filters"]
        assert [e["title"] for e in r.json()["exams"]] == ["Final Exam"]

    def test_returns_empty_when_not_enrolled(self):
        """No enrollment in the course → no assignments query, empty list, 200."""
        def side_effect(name):
            m = MagicMock()
            m.select.return_value = []  # no offerings/enrollments for the course
            return m

        with patch("routes.study_guide.table", side_effect=side_effect), \
             patch("services.academics.table", side_effect=side_effect):
            r = client.get(f"/api/study-guide/{USER_ID}/exams?course_id={COURSE_ID}")
        assert r.status_code == 200
        assert r.json() == {"exams": []}


# ── GET /api/study-guide/{user_id}/courses ───────────────────────────────────

class TestGetCourses:
    def test_delegates_to_enrollment_helper(self):
        """The route is UI-dead (the frontend uses /api/graph/.../courses) but must
        not 500 on the old courses.user_id filter — it delegates to the shared
        enrollment-resolving helper instead."""
        courses = [{"course_id": "c1", "course_name": "Calc II", "color": "#abc"}]
        with patch("routes.study_guide.graph_get_courses", return_value=courses) as g:
            r = client.get(f"/api/study-guide/{USER_ID}/courses")
        assert r.status_code == 200
        assert r.json() == {"courses": courses}
        g.assert_called_once_with(USER_ID)


# ── GET /api/study-guide/{user_id}/cached ────────────────────────────────────

class TestGetCachedGuides:
    def test_enriches_with_course_name_and_term(self):
        # Guides key on the offering (0025); the response exposes the abstract
        # course id (resolved via offering_course_id), its course name, and —
        # #475 F1 — the entry's OWN term label, so the client can open a recent
        # guide as its own term instead of the active selector's.
        guides = [
            {"id": "g1", "offering_id": "off1", "exam_id": "e1",
             "generated_at": "2026-04-01T00:00:00Z",
             "content": {"exam": "Midterm", "overview": "Covers ch1-5"}},
            {"id": "g2", "offering_id": "off-untermed", "exam_id": "e2",
             "generated_at": "2026-03-01T00:00:00Z",
             "content": {"exam": "Final", "overview": ""}},
        ]

        def table_side_effect(name):
            m = MagicMock()
            if name == "study_guides":
                m.select.return_value = guides
            elif name == "courses":
                m.select.return_value = [{"id": "c1", "course_name": "Calc II"}]
            else:
                m.select.return_value = []
            return m

        terms = {"off1": {"id": "term-f25", "label": "Fall 2025"}}
        with patch("routes.study_guide.table", side_effect=table_side_effect), \
             patch("routes.study_guide.offering_course_id", return_value="c1"), \
             patch("routes.study_guide.term_for_offering",
                   side_effect=lambda o: terms.get(o)):
            r = client.get(f"/api/study-guide/{USER_ID}/cached")

        assert r.status_code == 200
        out = r.json()["guides"][0]
        assert out["course_id"] == "c1"
        assert out["course_name"] == "Calc II"
        assert out["exam_title"] == "Midterm"
        assert out["overview"] == "Covers ch1-5"
        assert out["semester"] == "Fall 2025"
        # An offering with no term joined degrades to null, never a KeyError.
        assert r.json()["guides"][1]["semester"] is None

    def test_empty_when_no_guides(self):
        with patch("routes.study_guide.table") as t:
            t.return_value.select.return_value = []
            r = client.get(f"/api/study-guide/{USER_ID}/cached")
        assert r.status_code == 200
        assert r.json() == {"guides": []}


# ── GET /api/study-guide/{user_id}/guide ─────────────────────────────────────

class TestGetGuide:
    def test_returns_cached_guide_without_calling_gemini(self):
        cached_row = {
            "id": "g1", "user_id": USER_ID,
            "course_id": COURSE_ID, "exam_id": EXAM_ID,
            "generated_at": "2026-04-01T00:00:00Z",
            "content": {"exam": "Midterm", "topics": []},
        }
        agent_run = _agent_run_returning({"exam": "Midterm", "topics": []})
        with patch("routes.study_guide.table") as t, \
             patch("routes.study_guide.study_guide_agent.run", new=agent_run):
            t.return_value.select.return_value = [cached_row]
            r = client.get(f"/api/study-guide/{USER_ID}/guide?course_id={COURSE_ID}&exam_id={EXAM_ID}")
        assert r.status_code == 200
        body = r.json()
        assert body["cached"] is True
        assert body["guide"]["exam"] == "Midterm"
        agent_run.assert_not_called()

    def test_generates_and_inserts_when_not_cached(self):
        fresh_content = {"exam": "Final", "topics": [{"name": "Topic 1"}]}
        captured = {}

        def table_side_effect(name):
            m = MagicMock()
            if name == "study_guides":
                m.select.return_value = []  # nothing cached
                def _insert(row):
                    captured["row"] = row
                    return [{}]
                m.insert.side_effect = _insert
            elif name == "assignments":
                m.select.return_value = [{"title": "Final", "due_date": "2026-05-01"}]
            elif name == "enrollments":
                # Assignments key on enrollment_id — the exam lookup scopes to the
                # user's enrollments.
                m.select.return_value = [{"id": "enr1", "offering_id": "off1"}]
            elif name == "documents":
                m.select.return_value = []
            else:
                m.select.return_value = []
            return m

        agent_run = _agent_run_returning(fresh_content)
        with patch("routes.study_guide.table", side_effect=table_side_effect), \
             patch("routes.study_guide.user_enrollment_ids", return_value=[{"id": "enr1", "offering_id": "off1"}]), \
             patch("routes.study_guide.resolve_offering", return_value="off1") as ro, \
             patch("routes.study_guide.study_guide_agent.run", new=agent_run):
            r = client.get(f"/api/study-guide/{USER_ID}/guide?course_id={COURSE_ID}&exam_id={EXAM_ID}")
        assert r.status_code == 200
        body = r.json()
        assert body["cached"] is False
        assert body["guide"]["exam"] == "Final"
        agent_run.assert_called_once()
        # Abstract course id resolved to the offering, and the row keys on it.
        ro.assert_called_once_with(COURSE_ID)
        assert captured["row"]["offering_id"] == "off1"
        assert "course_id" not in captured["row"]

    def test_exam_must_belong_to_the_resolved_offering(self):
        """#475 F3 (the #462 CodeRabbit fix): the exam lookup is scoped to the
        RESOLVED offering's enrollment, not all of the user's enrollments — a
        two-term user generating against offering A with an exam that belongs
        to offering B gets a 404, and nothing is persisted."""
        inserted = {"n": 0}

        def table_side_effect(name):
            m = MagicMock()
            if name == "study_guides":
                m.select.return_value = []  # no cache → would generate

                def _insert(row):
                    inserted["n"] += 1
                    return [{}]
                m.insert.side_effect = _insert
            elif name == "assignments":
                def _select(cols, filters=None, order=None, limit=None):
                    # The exam belongs to enr-b; it is only visible when enr-b
                    # is inside the enrollment_id filter.
                    if "enr-b" in (filters or {}).get("enrollment_id", ""):
                        return [{"id": EXAM_ID, "enrollment_id": "enr-b",
                                 "title": "Final", "due_date": "2026-05-01"}]
                    return []
                m.select.side_effect = _select
            else:
                m.select.return_value = []
            return m

        agent_run = _agent_run_returning({"exam": "Final", "topics": []})
        with patch("routes.study_guide.table", side_effect=table_side_effect), \
             patch("routes.study_guide.user_enrollment_ids", return_value=[
                 {"id": "enr-a", "offering_id": "off-a"},
                 {"id": "enr-b", "offering_id": "off-b"},
             ]), \
             patch("routes.study_guide.resolve_offering", return_value="off-a"), \
             patch("routes.study_guide.study_guide_agent.run", new=agent_run):
            r = client.get(
                f"/api/study-guide/{USER_ID}/guide?course_id={COURSE_ID}&exam_id={EXAM_ID}"
            )
        assert r.status_code == 404
        agent_run.assert_not_called()
        assert inserted["n"] == 0

    def test_unknown_exam_returns_404(self):
        def table_side_effect(name):
            m = MagicMock()
            if name == "study_guides":
                m.select.return_value = []
            elif name == "assignments":
                m.select.return_value = []  # exam not found
            else:
                m.select.return_value = []
            return m

        with patch("routes.study_guide.table", side_effect=table_side_effect):
            r = client.get(f"/api/study-guide/{USER_ID}/guide?course_id={COURSE_ID}&exam_id=nope")
        assert r.status_code == 404
        # The frontend surfaces this detail verbatim (#361), so it must stay a
        # plain, actionable sentence — no payload, markup or identifiers.
        detail = r.json()["detail"]
        assert detail.startswith("Exam not found.")
        assert "pick another exam" in detail.lower()
        assert len(detail) <= 160
        assert not any(ch in detail for ch in "{}[]<>\n")


# ── POST /api/study-guide/regenerate ─────────────────────────────────────────

class TestRegenerateGuide:
    def test_deletes_cached_and_regenerates(self):
        fresh_content = {"exam": "Midterm", "topics": []}
        delete_called = {"n": 0}

        def table_side_effect(name):
            m = MagicMock()
            if name == "study_guides":
                m.select.return_value = []
                m.insert.return_value = [{}]
                def _delete(filters=None):
                    delete_called["n"] += 1
                    return []
                m.delete.side_effect = _delete
            elif name == "assignments":
                m.select.return_value = [{"title": "Midterm", "due_date": "2026-04-01"}]
            elif name == "documents":
                m.select.return_value = []
            else:
                m.select.return_value = []
            return m

        with patch("routes.study_guide.table", side_effect=table_side_effect), \
             patch("routes.study_guide.user_enrollment_ids", return_value=[{"id": "enr1", "offering_id": "off1"}]), \
             patch("routes.study_guide.resolve_offering", return_value="off1"), \
             patch("routes.study_guide.study_guide_agent.run", new=_agent_run_returning(fresh_content)):
            r = client.post(
                "/api/study-guide/regenerate",
                json={"user_id": USER_ID, "course_id": COURSE_ID, "exam_id": EXAM_ID},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["guide"]["exam"] == "Midterm"
        assert delete_called["n"] == 1

    @staticmethod
    def _guarded_stack(calls, assignments):
        """table() side_effect recording study_guides insert/delete order."""
        def table_side_effect(name):
            m = MagicMock()
            if name == "study_guides":
                m.select.return_value = []
                def _insert(row):
                    calls.append(("insert", row["id"]))
                    return [row]
                m.insert.side_effect = _insert
                def _delete(filters=None):
                    calls.append(("delete", dict(filters or {})))
                    return []
                m.delete.side_effect = _delete
            elif name == "assignments":
                m.select.return_value = assignments
            else:
                m.select.return_value = []
            return m
        return table_side_effect

    def test_foreign_or_missing_exam_leaves_cached_guide_untouched(self):
        """Regression: regenerate used to delete the cached guide BEFORE the
        exam was validated, so a bad/foreign exam_id 404'd AND wiped the
        student's guide. The exam lookup (scoped to the caller's enrollment)
        finds nothing here → 404, and nothing is deleted or generated."""
        calls = []
        agent_run = _agent_run_returning({"exam": "X", "topics": []})
        with patch("routes.study_guide.table", side_effect=self._guarded_stack(calls, [])), \
             patch("routes.study_guide.user_enrollment_ids", return_value=[{"id": "enr1", "offering_id": "off1"}]), \
             patch("routes.study_guide.resolve_offering", return_value="off1"), \
             patch("routes.study_guide.study_guide_agent.run", new=agent_run):
            r = client.post(
                "/api/study-guide/regenerate",
                json={"user_id": USER_ID, "course_id": COURSE_ID, "exam_id": "someone-elses-exam"},
            )
        assert r.status_code == 404
        assert calls == []
        agent_run.assert_not_called()

    def test_not_enrolled_leaves_cached_guide_untouched(self):
        calls = []
        with patch("routes.study_guide.table", side_effect=self._guarded_stack(calls, [{"title": "M"}])), \
             patch("routes.study_guide.user_enrollment_ids", return_value=[]), \
             patch("routes.study_guide.resolve_offering", return_value="off1"):
            r = client.post(
                "/api/study-guide/regenerate",
                json={"user_id": USER_ID, "course_id": COURSE_ID, "exam_id": EXAM_ID},
            )
        assert r.status_code == 404
        assert calls == []

    def test_generation_failure_leaves_cached_guide_untouched(self):
        calls = []
        failing = AsyncMock(side_effect=RuntimeError("provider down"))
        with patch("routes.study_guide.table",
                   side_effect=self._guarded_stack(calls, [{"title": "Midterm", "due_date": "2026-04-01"}])), \
             patch("routes.study_guide.user_enrollment_ids", return_value=[{"id": "enr1", "offering_id": "off1"}]), \
             patch("routes.study_guide.resolve_offering", return_value="off1"), \
             patch("routes.study_guide.study_guide_agent.run", new=failing):
            r = client.post(
                "/api/study-guide/regenerate",
                json={"user_id": USER_ID, "course_id": COURSE_ID, "exam_id": EXAM_ID},
            )
        assert r.status_code == 502
        assert calls == []

    def test_old_guides_replaced_only_after_new_one_inserted(self):
        calls = []
        with patch("routes.study_guide.table",
                   side_effect=self._guarded_stack(calls, [{"title": "Midterm", "due_date": "2026-04-01"}])), \
             patch("routes.study_guide.user_enrollment_ids", return_value=[{"id": "enr1", "offering_id": "off1"}]), \
             patch("routes.study_guide.resolve_offering", return_value="off1"), \
             patch("routes.study_guide.study_guide_agent.run",
                   new=_agent_run_returning({"exam": "Midterm", "topics": []})):
            r = client.post(
                "/api/study-guide/regenerate",
                json={"user_id": USER_ID, "course_id": COURSE_ID, "exam_id": EXAM_ID},
            )
        assert r.status_code == 200
        assert [c[0] for c in calls] == ["insert", "delete"]
        new_id = calls[0][1]
        assert calls[1][1] == {
            "user_id": f"eq.{USER_ID}",
            "offering_id": "eq.off1",
            "exam_id": f"eq.{EXAM_ID}",
            "id": f"neq.{new_id}",
        }

    def test_missing_fields_returns_400(self):
        r = client.post("/api/study-guide/regenerate", json={"user_id": USER_ID})
        assert r.status_code == 400


# ── semester scoping (#141) ──────────────────────────────────────────────────
#
# The Study screen's semester selector scopes the course-scoped reads. An
# explicit `semester` (term LABEL) resolves STRICTLY — an unknown label or a
# term with no offering of the course degrades to the route's empty/404
# behavior, never a silent fall-back to the current (or any other) term.

class TestSemesterScoping:
    def test_guide_resolves_the_requested_term_strictly(self):
        cached_row = {
            "id": "g1", "user_id": USER_ID, "offering_id": "off-f25",
            "exam_id": EXAM_ID, "generated_at": "2026-04-01T00:00:00Z",
            "content": {"exam": "Midterm", "topics": []},
        }
        captured = {}

        def table_side_effect(name):
            m = MagicMock()
            if name == "study_guides":
                def _select(cols, filters=None, order=None, limit=None):
                    captured["filters"] = filters or {}
                    return [cached_row]
                m.select.side_effect = _select
            else:
                m.select.return_value = []
            return m

        with patch("routes.study_guide.table", side_effect=table_side_effect), \
             patch("routes.study_guide.term_id_for_label", return_value="term-f25") as tl, \
             patch("routes.study_guide.resolve_offering", return_value="off-f25") as ro:
            r = client.get(
                f"/api/study-guide/{USER_ID}/guide"
                f"?course_id={COURSE_ID}&exam_id={EXAM_ID}&semester=Fall+2025"
            )
        assert r.status_code == 200
        assert r.json()["cached"] is True
        tl.assert_called_once_with("Fall 2025")
        ro.assert_called_once_with(COURSE_ID, "term-f25", fallback=False)
        assert captured["filters"]["offering_id"] == "eq.off-f25"

    def test_guide_404s_when_the_term_has_no_offering(self):
        agent_run = _agent_run_returning({"exam": "X", "topics": []})
        with patch("routes.study_guide.table"), \
             patch("routes.study_guide.term_id_for_label", return_value="term-su26"), \
             patch("routes.study_guide.resolve_offering", return_value=None), \
             patch("routes.study_guide.study_guide_agent.run", new=agent_run):
            r = client.get(
                f"/api/study-guide/{USER_ID}/guide"
                f"?course_id={COURSE_ID}&exam_id={EXAM_ID}&semester=Summer+2026"
            )
        assert r.status_code == 404
        # Never generate a guide for an offering that doesn't exist.
        agent_run.assert_not_called()

    def test_guide_404s_on_an_unknown_semester_label(self):
        with patch("routes.study_guide.term_id_for_label", return_value=None), \
             patch("routes.study_guide.resolve_offering") as ro:
            r = client.get(
                f"/api/study-guide/{USER_ID}/guide"
                f"?course_id={COURSE_ID}&exam_id={EXAM_ID}&semester=Nonsense"
            )
        assert r.status_code == 404
        ro.assert_not_called()

    def test_regenerate_keys_on_the_requested_terms_offering(self):
        fresh_content = {"exam": "Midterm", "topics": []}
        captured = {}

        def table_side_effect(name):
            m = MagicMock()
            if name == "study_guides":
                m.select.return_value = []
                m.insert.return_value = [{}]
                def _delete(filters=None):
                    captured["delete_filters"] = filters or {}
                    return []
                m.delete.side_effect = _delete
            elif name == "assignments":
                m.select.return_value = [{"title": "Midterm", "due_date": "2026-04-01"}]
            else:
                m.select.return_value = []
            return m

        with patch("routes.study_guide.table", side_effect=table_side_effect), \
             patch("routes.study_guide.user_enrollment_ids", return_value=[{"id": "enr1", "offering_id": "off-f25"}]), \
             patch("routes.study_guide.term_id_for_label", return_value="term-f25"), \
             patch("routes.study_guide.resolve_offering", return_value="off-f25") as ro, \
             patch("routes.study_guide.study_guide_agent.run", new=_agent_run_returning(fresh_content)):
            r = client.post(
                "/api/study-guide/regenerate",
                json={"user_id": USER_ID, "course_id": COURSE_ID,
                      "exam_id": EXAM_ID, "semester": "Fall 2025"},
            )
        assert r.status_code == 200
        ro.assert_called_once_with(COURSE_ID, "term-f25", fallback=False)
        assert captured["delete_filters"]["offering_id"] == "eq.off-f25"

    def test_regenerate_404s_when_the_term_has_no_offering(self):
        deleted = {"n": 0}

        def table_side_effect(name):
            m = MagicMock()
            m.select.return_value = []
            def _delete(filters=None):
                deleted["n"] += 1
                return []
            m.delete.side_effect = _delete
            return m

        with patch("routes.study_guide.table", side_effect=table_side_effect), \
             patch("routes.study_guide.term_id_for_label", return_value="term-su26"), \
             patch("routes.study_guide.resolve_offering", return_value=None):
            r = client.post(
                "/api/study-guide/regenerate",
                json={"user_id": USER_ID, "course_id": COURSE_ID,
                      "exam_id": EXAM_ID, "semester": "Summer 2026"},
            )
        assert r.status_code == 404
        assert deleted["n"] == 0  # nothing torn down for a term that isn't there

    def test_exams_scoped_to_the_semesters_enrollment(self):
        captured = {}

        def table_side_effect(name):
            m = MagicMock()
            if name == "assignments":
                def _select(cols, filters=None, order=None, limit=None):
                    captured["filters"] = filters or {}
                    return [{"id": "a1", "title": "Fall Final Exam",
                             "due_date": "2025-12-10", "assignment_type": "exam"}]
                m.select.side_effect = _select
            else:
                m.select.return_value = []
            return m

        terms = {"off-f25": {"id": "term-f25"}, "off-s26": {"id": "term-s26"}}
        with patch("routes.study_guide.table", side_effect=table_side_effect), \
             patch("routes.study_guide.user_offering_ids_for_course", return_value=["off-f25", "off-s26"]), \
             patch("routes.study_guide.user_enrollment_ids", return_value=[
                 {"id": "enr-f25", "offering_id": "off-f25"},
                 {"id": "enr-s26", "offering_id": "off-s26"},
             ]), \
             patch("routes.study_guide.term_id_for_label", return_value="term-f25"), \
             patch("routes.study_guide.term_for_offering", side_effect=lambda o: terms.get(o)):
            r = client.get(
                f"/api/study-guide/{USER_ID}/exams?course_id={COURSE_ID}&semester=Fall+2025"
            )
        assert r.status_code == 200
        # Only the fall enrollment feeds the assignments query.
        assert captured["filters"] == {"enrollment_id": "in.(enr-f25)"}
        assert [e["title"] for e in r.json()["exams"]] == ["Fall Final Exam"]

    def test_exams_empty_on_an_unknown_semester_label(self):
        with patch("routes.study_guide.table") as t, \
             patch("routes.study_guide.user_offering_ids_for_course", return_value=["off-f25"]), \
             patch("routes.study_guide.term_id_for_label", return_value=None):
            t.return_value.select.return_value = []
            r = client.get(
                f"/api/study-guide/{USER_ID}/exams?course_id={COURSE_ID}&semester=Nope"
            )
        assert r.status_code == 200
        assert r.json() == {"exams": []}


# ── agent-failure handling ───────────────────────────────────────────────────

class TestGenerationFailure:
    def test_agent_failure_returns_502(self):
        """When the study_guide agent raises, the route surfaces a 502, not 500."""
        def table_side_effect(name):
            m = MagicMock()
            if name == "study_guides":
                m.select.return_value = []  # nothing cached → generate
            elif name == "assignments":
                m.select.return_value = [{"title": "Final", "due_date": "2026-05-01"}]
            else:
                m.select.return_value = []
            return m

        boom = AsyncMock(side_effect=RuntimeError("gemini exploded"))
        with patch("routes.study_guide.table", side_effect=table_side_effect), \
             patch("routes.study_guide.user_enrollment_ids", return_value=[{"id": "enr1", "offering_id": "off1"}]), \
             patch("routes.study_guide.resolve_offering", return_value="off1"), \
             patch("routes.study_guide.study_guide_agent.run", new=boom):
            r = client.get(f"/api/study-guide/{USER_ID}/guide?course_id={COURSE_ID}&exam_id={EXAM_ID}")
        assert r.status_code == 502


# ── #771: invalidation-safe + single-flight generation ──────────────────────


class _GuideStore:
    """Stateful study_guides + documents tables for the race tests."""

    def __init__(self, doc_ids_seq):
        import threading

        self.guides: list[dict] = []
        self.deleted: list[dict] = []
        self.doc_ids_seq = list(doc_ids_seq)
        self.lock = threading.Lock()

    def table(self, name):
        m = MagicMock()
        if name == "study_guides":
            def _select(cols, filters=None, order=None, limit=None):
                with self.lock:
                    return list(self.guides)[:1]

            def _insert(row):
                with self.lock:
                    self.guides.append(row)
                return [row]

            def _delete(filters=None):
                with self.lock:
                    self.deleted.append(filters)
                    gid = (filters or {}).get("id", "")[3:]
                    self.guides = [g for g in self.guides if gid and g["id"] != gid]
            m.select.side_effect = _select
            m.insert.side_effect = _insert
            m.delete.side_effect = _delete
        elif name == "assignments":
            m.select.return_value = [{"title": "Final", "due_date": "2026-05-01"}]
        elif name == "documents":
            def _docs(cols, filters=None, **_k):
                if cols == "id":  # the material fingerprint read
                    with self.lock:
                        ids = self.doc_ids_seq.pop(0) if len(self.doc_ids_seq) > 1 else self.doc_ids_seq[0]
                    return [{"id": i} for i in ids]
                return []
            m.select.side_effect = _docs
        else:
            m.select.return_value = []
        return m


def _guide_patches(store, agent_run):
    from contextlib import ExitStack

    stack = ExitStack()
    stack.enter_context(patch("routes.study_guide.table", side_effect=store.table))
    stack.enter_context(patch("routes.study_guide.user_enrollment_ids",
                              return_value=[{"id": "enr1", "offering_id": "off1"}]))
    stack.enter_context(patch("routes.study_guide.resolve_offering", return_value="off1"))
    stack.enter_context(patch("routes.study_guide.study_guide_agent.run", new=agent_run))
    return stack


class TestGuideRaces:
    def test_a_guide_generated_across_an_upload_is_not_cached(self):
        """The generation read the documents before an upload's invalidation
        and inserted after it: the stale guide used to stay cached."""
        store = _GuideStore([["d1"], ["d1", "d2"]])  # d2 uploaded mid-generation
        with _guide_patches(store, _agent_run_returning({"exam": "Final"})):
            r = client.get(f"/api/study-guide/{USER_ID}/guide?course_id={COURSE_ID}&exam_id={EXAM_ID}")
        assert r.status_code == 200
        assert r.json()["guide"]["exam"] == "Final"  # the student still gets it
        assert store.guides == []  # ...but it is not cached
        assert store.deleted and "id" in store.deleted[-1]

    def test_unchanged_material_keeps_the_guide_cached(self):
        store = _GuideStore([["d1"]])
        with _guide_patches(store, _agent_run_returning({"exam": "Final"})):
            client.get(f"/api/study-guide/{USER_ID}/guide?course_id={COURSE_ID}&exam_id={EXAM_ID}")
        assert len(store.guides) == 1
        assert store.deleted == []

    def test_concurrent_misses_generate_once(self):
        import asyncio
        import threading

        store = _GuideStore([["d1"]])
        calls = {"n": 0}
        started = threading.Event()

        async def slow_run(*_a, **_k):
            calls["n"] += 1
            started.set()
            await asyncio.sleep(0.3)
            return SimpleNamespace(output=SimpleNamespace(model_dump=lambda: {"exam": "Final"}))

        results: list = []
        url = f"/api/study-guide/{USER_ID}/guide?course_id={COURSE_ID}&exam_id={EXAM_ID}"
        with _guide_patches(store, slow_run):
            threads = [threading.Thread(target=lambda: results.append(client.get(url).json()))
                       for _ in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(10)
        assert calls["n"] == 1
        assert len(store.guides) == 1
        assert sorted(r["cached"] for r in results) == [False, True, True]
