# tests/test_calendar_read_enrollment.py
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def _tbl(**rows_by_verb):
    m = MagicMock()
    for verb, val in rows_by_verb.items():
        getattr(m, verb).return_value = val
    return m

def _dispatch(tables):
    def _table(name):
        return tables.get(name) or _tbl(select=[], insert=[], update=[], delete=[])
    return _table

class TestUpcomingEnrollmentKeyed:
    def test_empty_when_no_enrollments(self):
        with patch("routes.calendar.table", side_effect=_dispatch({"enrollments": _tbl(select=[])})), \
             patch("services.academics.table", side_effect=_dispatch({"enrollments": _tbl(select=[])})):
            r = client.get("/api/calendar/upcoming/user_andres")
        assert r.status_code == 200
        assert r.json() == {"assignments": []}

    def test_decorates_with_course_meta(self):
        tables = {
            "enrollments": _tbl(select=[{"id": "e1", "offering_id": "o1"}]),
            "assignments": _tbl(select=[{
                "id": "a1", "enrollment_id": "e1", "title": "HW1",
                "due_date": "2999-01-01", "assignment_type": "homework",
                "notes": None, "google_event_id": None, "source": "manual",
            }]),
            "courses": _tbl(select=[{"id": "CS101", "course_code": "CS101", "course_name": "Intro"}]),
        }
        with patch("routes.calendar.table", side_effect=_dispatch(tables)), \
             patch("routes.calendar.academics") as ac:
            ac.user_enrollment_ids.return_value = [{"id": "e1", "offering_id": "o1"}]
            ac.offering_course_id.return_value = "CS101"
            r = client.get("/api/calendar/upcoming/user_andres")
        assert r.status_code == 200
        items = r.json()["assignments"]
        assert len(items) == 1
        assert items[0]["course_code"] == "CS101"
        assert items[0]["course_id"] == "CS101"
        assert items[0]["user_id"] == "user_andres"
