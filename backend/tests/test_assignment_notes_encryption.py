"""
Regression test for #126 finding #4: syllabus-extracted assignment notes were
written to assignments.notes as PLAINTEXT (no encrypt_if_present), defeating
column-level encryption at rest.

This is an encryption-boundary correctness test (not a cross-user-access test):
it asserts the value handed to the DB insert is ciphertext, and that it
round-trips back to the original plaintext via decrypt.

Assignments are now enrollment-keyed (no user_id/course_id columns). Each
assignment must carry a course_id so insert_new_assignments can resolve the
enrollment; tests mock enrollment_id_for and user_enrollment_ids accordingly.
"""
from unittest.mock import patch

from services.calendar_service import insert_new_assignments
from services.encryption import decrypt

PLAINTEXT_NOTES = "Bring a calculator; covers chapters 3-5 (private)."


class TestAssignmentNotesEncryptedAtRest:
    def test_notes_are_encrypted_before_insert(self):
        captured = {}

        def _insert(rows):
            captured["rows"] = rows
            return rows

        with patch("services.calendar_service.table") as t, \
             patch("services.academics.user_enrollment_ids", return_value=[{"id": "e1", "offering_id": "o1"}]), \
             patch("services.academics.enrollment_id_for", return_value="e1"):
            # No existing rows → nothing deduped; capture what gets inserted.
            t.return_value.select.return_value = []
            t.return_value.insert.side_effect = _insert

            n = insert_new_assignments(
                "user_andres",
                [{"title": "Midterm", "due_date": "2026-03-01", "notes": PLAINTEXT_NOTES, "course_id": "CS101"}],
            )

        assert n == 1
        written = captured["rows"][0]["notes"]
        # Pre-fix: written == PLAINTEXT_NOTES (stored in the clear). Post-fix the
        # column holds ciphertext that is NOT the plaintext...
        assert written != PLAINTEXT_NOTES
        # ...and decrypts back to the original.
        assert decrypt(written) == PLAINTEXT_NOTES

    def test_none_notes_stay_none(self):
        captured = {}
        with patch("services.calendar_service.table") as t, \
             patch("services.academics.user_enrollment_ids", return_value=[{"id": "e1", "offering_id": "o1"}]), \
             patch("services.academics.enrollment_id_for", return_value="e1"):
            t.return_value.select.return_value = []
            t.return_value.insert.side_effect = lambda rows: captured.setdefault("rows", rows)
            insert_new_assignments(
                "user_andres",
                [{"title": "Reading", "due_date": "2026-03-02", "notes": None, "course_id": "CS101"}],
            )
        assert captured["rows"][0]["notes"] is None
