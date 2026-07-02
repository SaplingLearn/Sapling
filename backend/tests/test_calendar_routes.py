"""
Unit tests for routes/calendar.py

Helper functions are tested directly; route endpoints are tested via
FastAPI's TestClient with the DB layer mocked out.
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _tbl(**rows_by_verb):
    """Build a MagicMock table handle with canned per-verb return values."""
    m = MagicMock()
    for verb, val in rows_by_verb.items():
        getattr(m, verb).return_value = val
    return m


# ── GET /api/calendar/status/{user_id} ───────────────────────────────────────

class TestCalendarStatus:
    def test_not_connected_when_no_token_row(self):
        with patch("routes.calendar.table") as t:
            t.return_value.select.return_value = []
            r = client.get("/api/calendar/status/user_andres")
        assert r.status_code == 200
        assert r.json() == {"connected": False}

    def test_not_connected_when_access_token_is_empty(self):
        with patch("routes.calendar.table") as t:
            t.return_value.select.return_value = [{"access_token": "", "expires_at": ""}]
            r = client.get("/api/calendar/status/user_andres")
        assert r.status_code == 200
        assert r.json()["connected"] is False

    def test_connected_when_valid_token_exists(self):
        with patch("routes.calendar.table") as t:
            t.return_value.select.return_value = [
                {"access_token": "valid_token_xyz", "expires_at": "2030-01-01T00:00:00"}
            ]
            r = client.get("/api/calendar/status/user_andres")
        assert r.status_code == 200
        assert r.json()["connected"] is True
        assert r.json()["expires_at"] == "2030-01-01T00:00:00"


# ── POST /api/calendar/save ───────────────────────────────────────────────────

class TestSaveAssignments:
    def test_saves_multiple_assignments(self):
        with patch("services.calendar_service.table") as t, \
             patch("services.academics.user_enrollment_ids", return_value=[{"id": "e1", "offering_id": "o1"}]), \
             patch("services.academics.enrollment_id_for", return_value="e1"):
            t.return_value.select.return_value = []
            t.return_value.insert.return_value = []
            body = {
                "user_id": "user_andres",
                "assignments": [
                    {"title": "HW1",    "due_date": "2026-03-01", "assignment_type": "homework", "course_id": "CS101"},
                    {"title": "Quiz 1", "due_date": "2026-03-10", "assignment_type": "quiz",     "course_id": "CS101"},
                ],
            }
            r = client.post("/api/calendar/save", json=body)

        assert r.status_code == 200
        assert r.json()["saved_count"] == 2

    def test_save_empty_list_returns_zero(self):
        with patch("services.calendar_service.table") as t:
            t.return_value.select.return_value = []
            r = client.post("/api/calendar/save", json={"user_id": "user_andres", "assignments": []})
        assert r.status_code == 200
        assert r.json()["saved_count"] == 0

    def test_save_with_optional_fields_omitted(self):
        with patch("services.calendar_service.table") as t, \
             patch("services.academics.user_enrollment_ids", return_value=[{"id": "e1", "offering_id": "o1"}]), \
             patch("services.academics.enrollment_id_for", return_value="e1"):
            t.return_value.select.return_value = []
            t.return_value.insert.return_value = []
            body = {
                "user_id": "user_andres",
                "assignments": [{"title": "Midterm", "due_date": "2026-04-01", "course_id": "CS101"}],
            }
            r = client.post("/api/calendar/save", json=body)
        assert r.status_code == 200
        assert r.json()["saved_count"] == 1

    def test_save_skips_duplicate_title_and_date(self):
        with patch("services.calendar_service.table") as t, \
             patch("services.academics.user_enrollment_ids", return_value=[{"id": "e1", "offering_id": "o1"}]), \
             patch("services.academics.enrollment_id_for", return_value="e1"):
            t.return_value.select.return_value = [
                {"title": "HW1", "due_date": "2026-03-01"},
            ]
            t.return_value.insert.return_value = []
            body = {
                "user_id": "user_andres",
                "assignments": [
                    {"title": "HW1", "due_date": "2026-03-01", "assignment_type": "homework", "course_id": "CS101"},
                    {"title": "HW2", "due_date": "2026-03-02", "assignment_type": "homework", "course_id": "CS101"},
                ],
            }
            r = client.post("/api/calendar/save", json=body)
        assert r.status_code == 200
        assert r.json()["saved_count"] == 1

    def test_save_skips_when_iso_datetime_matches_existing_date(self):
        """#16: same title + same calendar day (ISO date vs datetime) → one row."""
        with patch("services.calendar_service.table") as t, \
             patch("services.academics.user_enrollment_ids", return_value=[{"id": "e1", "offering_id": "o1"}]), \
             patch("services.academics.enrollment_id_for", return_value="e1"):
            t.return_value.select.return_value = [
                {"title": "Final Exam", "due_date": "2026-05-01"},
            ]
            t.return_value.insert.return_value = []
            body = {
                "user_id": "user_andres",
                "assignments": [
                    {"title": "Final Exam", "due_date": "2026-05-01T09:00:00", "assignment_type": "exam", "course_id": "CS101"},
                ],
            }
            r = client.post("/api/calendar/save", json=body)
        assert r.status_code == 200
        assert r.json()["saved_count"] == 0


# ── GET /api/calendar/upcoming/{user_id} ─────────────────────────────────────

class TestGetUpcoming:
    def test_returns_assignments_from_db(self):
        # New enrollment-keyed schema: rows carry enrollment_id, not user_id/course_id.
        mock_rows = [
            {"id": "a1", "enrollment_id": "e1", "title": "HW1",
             "due_date": "2026-03-01", "assignment_type": "homework",
             "notes": None, "google_event_id": None, "source": None},
            {"id": "a2", "enrollment_id": "e1", "title": "Quiz",
             "due_date": "2026-03-10", "assignment_type": "quiz",
             "notes": None, "google_event_id": None, "source": None},
        ]
        with patch("routes.calendar.table") as t, \
             patch("routes.calendar.academics") as ac:
            t.return_value.select.return_value = mock_rows
            ac.user_enrollment_ids.return_value = [{"id": "e1", "offering_id": "o1"}]
            ac.offering_course_id.return_value = None  # no course → empty strings
            r = client.get("/api/calendar/upcoming/user_andres")

        assert r.status_code == 200
        assignments = r.json()["assignments"]
        assert len(assignments) == 2
        assert assignments[0]["title"] == "HW1"
        assert assignments[0]["user_id"] == "user_andres"
        assert assignments[0]["course_code"] == ""
        assert assignments[0]["course_name"] == ""

    def test_returns_empty_list_when_none(self):
        with patch("routes.calendar.table") as t, \
             patch("routes.calendar.academics") as ac:
            ac.user_enrollment_ids.return_value = []
            t.return_value.select.return_value = []
            r = client.get("/api/calendar/upcoming/user_andres")
        assert r.status_code == 200
        assert r.json()["assignments"] == []


# ── POST /api/calendar/suggest-study-blocks ───────────────────────────────────

class TestSuggestStudyBlocks:
    def test_returns_at_most_5_blocks(self):
        many_assignments = [
            {"id": f"a{i}", "enrollment_id": "e1", "title": f"Task {i}",
             "due_date": f"2026-03-{i:02d}", "assignment_type": None,
             "notes": None, "google_event_id": None, "source": None}
            for i in range(1, 9)
        ]
        with patch("routes.calendar.table") as t, \
             patch("routes.calendar.academics") as ac:
            ac.user_enrollment_ids.return_value = [{"id": "e1", "offering_id": "o1"}]
            ac.offering_course_id.return_value = None
            t.return_value.select.return_value = many_assignments
            r = client.post("/api/calendar/suggest-study-blocks", json={"user_id": "user_andres"})

        assert r.status_code == 200
        assert len(r.json()["study_blocks"]) <= 5

    def test_block_shape_is_correct(self):
        assignments = [{"id": "a1", "enrollment_id": "e1", "title": "HW1",
                        "due_date": "2026-03-01", "assignment_type": None,
                        "notes": None, "google_event_id": None, "source": None}]
        with patch("routes.calendar.table") as t, \
             patch("routes.calendar.academics") as ac:
            ac.user_enrollment_ids.return_value = [{"id": "e1", "offering_id": "o1"}]
            ac.offering_course_id.return_value = None
            t.return_value.select.return_value = assignments
            r = client.post("/api/calendar/suggest-study-blocks", json={"user_id": "user_andres"})

        block = r.json()["study_blocks"][0]
        assert "topic" in block
        assert "suggested_date" in block
        assert "duration_minutes" in block
        assert block["duration_minutes"] == 60

    def test_empty_assignments_returns_empty_blocks(self):
        with patch("routes.calendar.table") as t, \
             patch("routes.calendar.academics") as ac:
            ac.user_enrollment_ids.return_value = [{"id": "e1", "offering_id": "o1"}]
            t.return_value.select.return_value = []
            r = client.post("/api/calendar/suggest-study-blocks", json={"user_id": "user_andres"})
        assert r.json()["study_blocks"] == []


# ── DELETE /api/calendar/disconnect/{user_id} ─────────────────────────────────

class TestDisconnect:
    def test_deletes_oauth_token_and_returns_disconnected(self):
        with patch("routes.calendar.table") as t:
            t.return_value.delete.return_value = []
            r = client.delete("/api/calendar/disconnect/user_andres")
        assert r.status_code == 200
        assert r.json() == {"disconnected": True}


# ── PATCH /api/calendar/assignments/{id} ─────────────────────────────────────

class TestUpdateAssignment:
    def test_updates_whitelisted_fields(self):
        with patch("routes.calendar.table") as t, \
             patch("routes.calendar.academics") as ac:
            ac.user_enrollment_ids.return_value = [{"id": "e1", "offering_id": "o1"}]
            t.return_value.select.return_value = [{"id": "a1"}]
            t.return_value.update.return_value = [{}]
            r = client.patch(
                "/api/calendar/assignments/a1",
                json={"user_id": "u1", "title": "New title", "due_date": "2026-06-01", "ignored": "x"},
            )
        assert r.status_code == 200
        assert r.json() == {"updated": True}

    def test_missing_user_id_returns_400(self):
        r = client.patch("/api/calendar/assignments/a1", json={"title": "No user"})
        assert r.status_code == 400

    def test_unknown_assignment_returns_404(self):
        with patch("routes.calendar.table") as t, \
             patch("routes.calendar.academics") as ac:
            ac.user_enrollment_ids.return_value = [{"id": "e1", "offering_id": "o1"}]
            t.return_value.select.return_value = []
            r = client.patch(
                "/api/calendar/assignments/missing",
                json={"user_id": "u1", "title": "x"},
            )
        assert r.status_code == 404

    def test_course_id_no_longer_settable(self):
        """course_id is derived from enrollment; patching it via PATCH is intentionally blocked."""
        with patch("routes.calendar.table") as t, \
             patch("routes.calendar.academics") as ac:
            ac.user_enrollment_ids.return_value = [{"id": "e1", "offering_id": "o1"}]
            t.return_value.select.return_value = [{"id": "a1"}]
            r = client.patch(
                "/api/calendar/assignments/a1",
                json={"user_id": "u1", "course_id": "some-course"},
            )
        assert r.status_code == 200
        assert r.json() == {"updated": False}

    def test_no_valid_fields_returns_updated_false(self):
        with patch("routes.calendar.table") as t, \
             patch("routes.calendar.academics") as ac:
            ac.user_enrollment_ids.return_value = [{"id": "e1", "offering_id": "o1"}]
            t.return_value.select.return_value = [{"id": "a1"}]
            r = client.patch(
                "/api/calendar/assignments/a1",
                json={"user_id": "u1", "made_up": "x"},
            )
        assert r.status_code == 200
        assert r.json() == {"updated": False}


# ── DELETE /api/calendar/assignments/{id} ────────────────────────────────────

class TestDeleteAssignment:
    def test_deletes_assignment(self):
        with patch("routes.calendar.table") as t, \
             patch("routes.calendar.academics") as ac:
            ac.user_enrollment_ids.return_value = [{"id": "e1", "offering_id": "o1"}]
            t.return_value.select.return_value = [{"id": "a1"}]
            t.return_value.delete.return_value = []
            r = client.delete("/api/calendar/assignments/a1?user_id=u1")
        assert r.status_code == 200
        assert r.json() == {"deleted": True}

    def test_missing_returns_404(self):
        with patch("routes.calendar.table") as t, \
             patch("routes.calendar.academics") as ac:
            ac.user_enrollment_ids.return_value = [{"id": "e1", "offering_id": "o1"}]
            t.return_value.select.return_value = []
            r = client.delete("/api/calendar/assignments/a1?user_id=u1")
        assert r.status_code == 404


# ── POST /api/calendar/extract ───────────────────────────────────────────────
#
# These tests pin the wire-format contract between
# `services.calendar_service.extract_assignments_from_file` and the
# `/api/calendar/extract` route. Refactor #4 made the extractor
# agent-first with a legacy fallback; the route returns the dict
# verbatim, so ANY shape change to the service's return value is a
# breaking change for the frontend. The agent-path dict carries extra
# keys (`course_title`, `grading_categories`); the legacy fallback
# returns a smaller dict. Both must round-trip cleanly through the
# route.

class TestImportExtractWireFormat:
    """Pins the wire format of POST /api/calendar/extract."""

    AGENT_RESULT = {
        "assignments": [
            {
                "title": "Lab 7: Recursion",
                "due_date": "2026-03-15",
                "assignment_type": "other",
                "notes": "Hands-on recursion lab.",
                "weight_pct": 10.0,
            }
        ],
        "warnings": [],
        "raw_text": "syllabus body",
        "course_title": "CS 101",
        "grading_categories": [{"name": "Labs", "weight": 0.4}],
    }

    LEGACY_RESULT = {
        "assignments": [
            {
                "title": "HW1",
                "due_date": "2026-03-01",
                "assignment_type": "homework",
                "notes": None,
            }
        ],
        "warnings": [],
        "raw_text": "fallback text",
    }

    def _post_extract(self):
        return client.post(
            "/api/calendar/extract",
            files={"file": ("syllabus.pdf", b"raw-bytes", "application/pdf")},
            data={"user_id": "user_andres"},
        )

    def test_import_extract_returns_assignments_from_agent(self):
        """Agent-path dict (with course_title, grading_categories extras)
        passes through the route verbatim."""
        with patch(
            "routes.calendar.extract_assignments_from_file",
            return_value=dict(self.AGENT_RESULT),
        ) as m:
            r = self._post_extract()

        assert m.call_count == 1
        assert r.status_code == 200
        body = r.json()
        # Required legacy keys are present.
        assert body["assignments"][0]["title"] == "Lab 7: Recursion"
        assert body["assignments"][0]["due_date"] == "2026-03-15"
        assert body["warnings"] == []
        assert body["raw_text"] == "syllabus body"
        # Adapter-added extras flow through to the client.
        assert body["course_title"] == "CS 101"
        assert body["grading_categories"] == [{"name": "Labs", "weight": 0.4}]

    def test_import_extract_handles_legacy_path_dict(self):
        """Legacy fallback dict (no course_title / grading_categories)
        still works through the route — backward compat after refactor #4."""
        with patch(
            "routes.calendar.extract_assignments_from_file",
            return_value=dict(self.LEGACY_RESULT),
        ) as m:
            r = self._post_extract()

        assert m.call_count == 1
        assert r.status_code == 200
        body = r.json()
        assert body["assignments"][0]["title"] == "HW1"
        assert body["raw_text"] == "fallback text"
        assert body["warnings"] == []
        # Agent extras are absent on the fallback path; consumers must
        # tolerate their absence.
        assert "course_title" not in body
        assert "grading_categories" not in body

    def test_import_extract_warnings_passthrough(self):
        """Warnings from either path reach the client untouched."""
        warnings = ["page 3 had no extractable text", "due date heuristic uncertain"]
        result = {
            "assignments": [],
            "warnings": list(warnings),
            "raw_text": "",
        }
        with patch(
            "routes.calendar.extract_assignments_from_file",
            return_value=result,
        ):
            r = self._post_extract()

        assert r.status_code == 200
        assert r.json()["warnings"] == warnings

    def test_import_extract_real_async_chain_works(self):
        """Regression for PR #79 review: the route is `async def` and the
        service helper is now `async def` — calling them through the real
        chain without mocking the helper proves the awaits are wired
        correctly. Catches the old `asyncio.run` inside an event loop bug.

        We only mock at the AGENT layer (syllabus_extraction_agent.run) so
        the full chain — route -> service -> _extract_via_agent ->
        syllabus_to_wire_dict — actually executes.
        """
        from datetime import date
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from agents.syllabus_extraction import SyllabusAssignments, SyllabusAssignment

        fake_output = SyllabusAssignments(
            course_title="MATH 101",
            instructor=None,
            assignments=[
                SyllabusAssignment(
                    title="HW 1", description=None, due_date=date(2026, 6, 1), weight_pct=10.0,
                ),
            ],
            grading_categories=[],
        )

        with (
            patch(
                "services.calendar_service.syllabus_extraction_agent.run",
                new=AsyncMock(return_value=SimpleNamespace(output=fake_output)),
            ),
            patch(
                "services.calendar_service.extract_text_from_file",
                return_value="MATH 101 Syllabus. HW 1 due 2026-06-01.",
            ),
        ):
            # POST to the actual route — no helper mock. If
            # `await extract_assignments_from_file(...)` isn't wired
            # correctly, this raises and the test fails.
            r = client.post(
                "/api/calendar/extract",
                files={"file": ("syl.txt", b"placeholder", "text/plain")},
                data={"user_id": "user_andres"},
            )

        assert r.status_code == 200
        body = r.json()
        assert any(a["title"] == "HW 1" for a in body.get("assignments") or [])
        assert body.get("course_title") == "MATH 101"
