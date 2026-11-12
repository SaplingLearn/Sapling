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
        # #766: a calendar write never creates an enrollment.
        eif.assert_called_with("user_andres", "CS101", create=False)
        inserted = assignments_tbl.insert.call_args[0][0]
        assert inserted[0]["enrollment_id"] == "e1"
        assert inserted[0]["source"] == "manual"
        assert "user_id" not in inserted[0] and "course_id" not in inserted[0]

    def test_dropped_course_is_skipped_not_re_enrolled(self):
        # #766: saving an assignment for a course the student dropped used to
        # silently re-create the enrollment. Run the REAL resolver against a
        # user with no enrollment: nothing may be inserted anywhere.
        tables: dict = {}

        def factory(name):
            if name not in tables:
                m = MagicMock()
                m.select.return_value = []
                m.insert.return_value = []
                tables[name] = m
            return tables[name]

        with patch("services.calendar_service.table", side_effect=factory), \
             patch("services.academics.table", side_effect=factory), \
             patch("services.academics.current_term", return_value={"id": "spring-2026"}):
            n = cs.insert_new_assignments("user_andres", [
                {"title": "HW1", "due_date": "2026-03-01", "course_id": "CS101"},
            ])
        assert n == 0
        for name in ("enrollments", "course_offerings", "assignments"):
            if name in tables:
                tables[name].insert.assert_not_called()

    def test_skips_when_no_course(self):
        with patch("services.calendar_service.table", return_value=_tbl(select=[], insert=[])), \
             patch("services.academics.user_enrollment_ids", return_value=[]):
            n = cs.insert_new_assignments("user_andres", [
                {"title": "HW1", "due_date": "2026-03-01"},  # no course_id
            ])
        assert n == 0

    def test_dedup_against_enrollment_set(self):
        # existing row in the TARGET enrollment has same title+day -> skip
        existing = _tbl(
            select=[{"enrollment_id": "e1", "title": "HW1", "due_date": "2026-03-01"}], insert=[])
        with patch("services.calendar_service.table", return_value=existing), \
             patch("services.academics.user_enrollment_ids", return_value=[{"id": "e1", "offering_id": "o1"}]), \
             patch("services.academics.enrollment_id_for", return_value="e1"):
            n = cs.insert_new_assignments("user_andres", [
                {"title": "HW1", "due_date": "2026-03-01", "course_id": "CS101"},
            ])
        assert n == 0


_ENROLLMENTS = {"CS101": "e1", "MA242": "e2"}


def _resolver(_user_id, course_id, **_kw):
    return _ENROLLMENTS.get(course_id)


class TestSaveNewAssignments:
    """`save_new_assignments` says what it left out and why, and a duplicate
    is scoped to the enrollment the row would land in."""

    def _save(self, assignments, *, existing=()):
        tbl = _tbl(select=list(existing), insert=[])
        with patch("services.calendar_service.table", return_value=tbl), \
             patch("services.academics.enrollment_id_for", side_effect=_resolver) as eif:
            result = cs.save_new_assignments("user_andres", assignments, source="manual")
        return result, tbl, eif

    def test_reports_each_skip_with_its_reason_in_request_order(self):
        result, tbl, _ = self._save(
            [
                {"title": "Quiz 1", "due_date": "2026-03-05", "course_id": "GONE"},
                {"title": " HW1 ", "due_date": "2026-03-01T23:59:00Z", "course_id": "CS101"},
                {"title": "HW2", "due_date": "2026-03-08", "course_id": "CS101"},
                {"title": "Reading", "due_date": "2026-03-09"},  # no course
            ],
            existing=[{"enrollment_id": "e1", "title": "HW1", "due_date": "2026-03-01"}],
        )
        assert result == {
            "saved_count": 1,
            "skipped_count": 3,
            "skipped": [
                {"title": "Quiz 1", "due_date": "2026-03-05", "reason": "no_enrollment"},
                {"title": "HW1", "due_date": "2026-03-01", "reason": "duplicate"},
                {"title": "Reading", "due_date": "2026-03-09", "reason": "no_enrollment"},
            ],
        }
        assert [r["title"] for r in tbl.insert.call_args[0][0]] == ["HW2"]

    def test_a_reason_is_always_one_of_the_two_fixed_codes(self):
        result, _, _ = self._save(
            [{"title": "A", "due_date": "2026-03-01", "course_id": c} for c in ("GONE", "CS101", "CS101", "")])
        assert {s["reason"] for s in result["skipped"]} == {cs.SKIP_DUPLICATE, cs.SKIP_NO_ENROLLMENT}
        assert {cs.SKIP_DUPLICATE, cs.SKIP_NO_ENROLLMENT} == {"duplicate", "no_enrollment"}
        # A skip carries the caller's own title and day back, nothing else.
        assert all(set(s) == {"title", "due_date", "reason"} for s in result["skipped"])

    def test_same_title_and_day_in_another_course_is_saved(self):
        result, tbl, _ = self._save(
            [{"title": "Final Exam", "due_date": "2026-05-10", "course_id": "MA242",
              "assignment_type": "exam"}],
            existing=[{"enrollment_id": "e1", "title": "Final Exam", "due_date": "2026-05-10"}],
        )
        assert result == {"saved_count": 1, "skipped_count": 0, "skipped": []}
        assert tbl.insert.call_args[0][0][0]["enrollment_id"] == "e2"

    def test_one_batch_can_carry_the_same_exam_for_two_courses(self):
        result, tbl, _ = self._save([
            {"title": "Final Exam", "due_date": "2026-05-10", "course_id": "CS101"},
            {"title": "Final Exam", "due_date": "2026-05-10", "course_id": "MA242"},
            {"title": "Final Exam", "due_date": "2026-05-10", "course_id": "CS101"},  # repeats row 1
        ])
        assert result["saved_count"] == 2
        assert result["skipped"] == [
            {"title": "Final Exam", "due_date": "2026-05-10", "reason": "duplicate"}]
        assert [r["enrollment_id"] for r in tbl.insert.call_args[0][0]] == ["e1", "e2"]

    def test_existing_rows_are_read_for_the_target_enrollments_only(self):
        _, tbl, eif = self._save([
            {"title": "HW1", "due_date": "2026-03-01", "course_id": "CS101"},
            {"title": "HW2", "due_date": "2026-03-02", "course_id": "CS101"},
            {"title": "HW3", "due_date": "2026-03-03", "course_id": "GONE"},
        ])
        assert tbl.select.call_args.kwargs["filters"] == {"enrollment_id": "in.(e1)"}
        # One enrollment lookup per course, never one per row; never a create (#766).
        assert [c.args[1] for c in eif.call_args_list] == ["CS101", "GONE"]
        assert all(c.kwargs == {"create": False} for c in eif.call_args_list)

    def test_nothing_to_look_up_means_no_read_and_no_insert(self):
        result, tbl, _ = self._save([{"title": "HW1", "due_date": "2026-03-01", "course_id": "GONE"}])
        assert result["saved_count"] == 0 and result["skipped_count"] == 1
        tbl.select.assert_not_called()
        tbl.insert.assert_not_called()

    def test_a_row_without_a_title_or_date_is_dropped_uncounted(self):
        result, _, _ = self._save([
            {"title": "  ", "due_date": "2026-03-01", "course_id": "CS101"},
            {"title": "HW1", "due_date": "", "course_id": "CS101"},
        ])
        assert result == {"saved_count": 0, "skipped_count": 0, "skipped": []}

    def test_insert_new_assignments_still_answers_the_count(self):
        tbl = _tbl(select=[], insert=[])
        with patch("services.calendar_service.table", return_value=tbl), \
             patch("services.academics.enrollment_id_for", side_effect=_resolver):
            assert cs.insert_new_assignments(
                "user_andres", [{"title": "HW1", "due_date": "2026-03-01", "course_id": "CS101"}]) == 1
