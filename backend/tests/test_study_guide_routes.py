"""
Unit tests for routes/study_guide.py

Covers:
  - GET  /api/study-guide/{user_id}/exams           → get_exams
  - GET  /api/study-guide/{user_id}/cached          → get_cached_guides
  - GET  /api/study-guide/{user_id}/guide           → get_guide (cached + fresh)
  - POST /api/study-guide/regenerate                → regenerate_guide
"""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

USER_ID = "user_test"
COURSE_ID = "course_1"
EXAM_ID = "exam_1"


# ── GET /api/study-guide/{user_id}/exams ─────────────────────────────────────

class TestGetExams:
    def test_filters_by_type_and_keywords(self):
        all_assignments = [
            {"id": "a1", "title": "Midterm Exam", "due_date": "2026-04-01", "assignment_type": "exam"},
            {"id": "a2", "title": "Homework 3",  "due_date": "2026-04-02", "assignment_type": "homework"},
            {"id": "a3", "title": "Reading quiz", "due_date": "2026-04-03", "assignment_type": "other"},
            {"id": "a4", "title": "Project B",   "due_date": "2026-04-04", "assignment_type": "project"},
        ]
        with patch("routes.study_guide.table") as t:
            t.return_value.select.return_value = all_assignments
            r = client.get(f"/api/study-guide/{USER_ID}/exams?course_id={COURSE_ID}")
        assert r.status_code == 200
        slugs = {e["title"] for e in r.json()["exams"]}
        assert "Midterm Exam" in slugs
        assert "Reading quiz" in slugs  # title contains "quiz"
        assert "Homework 3" not in slugs
        assert "Project B" not in slugs


# ── GET /api/study-guide/{user_id}/cached ────────────────────────────────────

class TestGetCachedGuides:
    def test_enriches_with_course_name(self):
        guides = [{
            "id": "g1", "course_id": "c1", "exam_id": "e1",
            "generated_at": "2026-04-01T00:00:00Z",
            "content": {"exam": "Midterm", "overview": "Covers ch1-5"},
        }]

        def table_side_effect(name):
            m = MagicMock()
            if name == "study_guides":
                m.select.return_value = guides
            elif name == "courses":
                m.select.return_value = [{"id": "c1", "course_name": "Calc II"}]
            else:
                m.select.return_value = []
            return m

        with patch("routes.study_guide.table", side_effect=table_side_effect):
            r = client.get(f"/api/study-guide/{USER_ID}/cached")

        assert r.status_code == 200
        out = r.json()["guides"][0]
        assert out["course_name"] == "Calc II"
        assert out["exam_title"] == "Midterm"
        assert out["overview"] == "Covers ch1-5"

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
        with patch("routes.study_guide.table") as t, \
             patch("routes.study_guide.call_gemini_json") as gem:
            t.return_value.select.return_value = [cached_row]
            r = client.get(f"/api/study-guide/{USER_ID}/guide?course_id={COURSE_ID}&exam_id={EXAM_ID}")
        assert r.status_code == 200
        body = r.json()
        assert body["cached"] is True
        assert body["guide"]["exam"] == "Midterm"
        gem.assert_not_called()

    def test_generates_and_inserts_when_not_cached(self):
        fresh_content = {"exam": "Final", "topics": [{"name": "Topic 1"}]}

        def table_side_effect(name):
            m = MagicMock()
            if name == "study_guides":
                m.select.return_value = []  # nothing cached
                m.insert.return_value = [{}]
            elif name == "assignments":
                m.select.return_value = [{"title": "Final", "due_date": "2026-05-01"}]
            elif name == "documents":
                m.select.return_value = []
            else:
                m.select.return_value = []
            return m

        with patch("routes.study_guide.table", side_effect=table_side_effect), \
             patch("routes.study_guide.call_gemini_json", return_value=fresh_content) as gem:
            r = client.get(f"/api/study-guide/{USER_ID}/guide?course_id={COURSE_ID}&exam_id={EXAM_ID}")
        assert r.status_code == 200
        body = r.json()
        assert body["cached"] is False
        assert body["guide"]["exam"] == "Final"
        gem.assert_called_once()

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
             patch("routes.study_guide.call_gemini_json", return_value=fresh_content):
            r = client.post(
                "/api/study-guide/regenerate",
                json={"user_id": USER_ID, "course_id": COURSE_ID, "exam_id": EXAM_ID},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["guide"]["exam"] == "Midterm"
        assert delete_called["n"] == 1

    def test_missing_fields_returns_400(self):
        r = client.post("/api/study-guide/regenerate", json={"user_id": USER_ID})
        assert r.status_code == 400
