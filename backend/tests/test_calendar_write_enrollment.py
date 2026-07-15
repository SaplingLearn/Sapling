# tests/test_calendar_write_enrollment.py
from unittest.mock import MagicMock, patch
import services.calendar_service as cs

def _tbl(**rows_by_verb):
    m = MagicMock()
    for verb, val in rows_by_verb.items():
        getattr(m, verb).return_value = val
    return m

class TestInsertNewAssignments:
    def test_resolves_enrollment_and_inserts(self):
        assignments_tbl = _tbl(select=[], insert=[])
        with patch("services.calendar_service.table", return_value=assignments_tbl), \
             patch("services.academics.user_enrollment_ids", return_value=[{"id": "e1", "offering_id": "o1"}]), \
             patch("services.academics.enrollment_id_for", return_value="e1") as eif:
            n = cs.insert_new_assignments("user_andres", [
                {"title": "HW1", "due_date": "2026-03-01", "course_id": "CS101", "assignment_type": "homework"},
            ], source="manual")
        assert n == 1
        eif.assert_called_with("user_andres", "CS101", create=True)
        inserted = assignments_tbl.insert.call_args[0][0]
        assert inserted[0]["enrollment_id"] == "e1"
        assert inserted[0]["source"] == "manual"
        assert "user_id" not in inserted[0] and "course_id" not in inserted[0]

    def test_skips_when_no_course(self):
        with patch("services.calendar_service.table", return_value=_tbl(select=[], insert=[])), \
             patch("services.academics.user_enrollment_ids", return_value=[]):
            n = cs.insert_new_assignments("user_andres", [
                {"title": "HW1", "due_date": "2026-03-01"},  # no course_id
            ])
        assert n == 0

    def test_dedup_against_enrollment_set(self):
        # existing row in the user's enrollment has same title+day -> skip
        existing = _tbl(select=[{"title": "HW1", "due_date": "2026-03-01"}], insert=[])
        with patch("services.calendar_service.table", return_value=existing), \
             patch("services.academics.user_enrollment_ids", return_value=[{"id": "e1", "offering_id": "o1"}]), \
             patch("services.academics.enrollment_id_for", return_value="e1"):
            n = cs.insert_new_assignments("user_andres", [
                {"title": "HW1", "due_date": "2026-03-01", "course_id": "CS101"},
            ])
        assert n == 0
