"""Tests for assignment_dedupe_key (#16) — no heavy service imports."""

from services.assignment_dedupe import assignment_dedupe_key


class TestAssignmentDedupeKey:
    def test_strips_title(self):
        assert assignment_dedupe_key("  HW1 ", "2026-01-01") == ("HW1", "2026-01-01")

    def test_truncates_iso_datetime_to_date(self):
        assert assignment_dedupe_key("Exam", "2026-03-15T14:30:00Z") == ("Exam", "2026-03-15")

    def test_preserves_non_iso_due_strings(self):
        assert assignment_dedupe_key("A", "TBD") == ("A", "TBD")
