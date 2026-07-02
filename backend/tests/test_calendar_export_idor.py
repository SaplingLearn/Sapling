"""
Regression test for #123: calendar.export_to_google cross-user IDOR.

Pre-fix, export_to_google selected each assignment by `id` alone, so an
authenticated user could pass ANOTHER user's assignment UUIDs to read+decrypt
their private notes, push them into the caller's Google Calendar, and stamp
google_event_id onto the victim's row. The fix scopes the select (and the
write-back) by enrollment_id membership, so a non-owned id returns no row and
is skipped.  The `user_id` column no longer exists on the `assignments` table;
the new security boundary is the caller's own enrollment ids.

The cross-user test makes the DB mock behave like a real row-scoped store: the
victim's row is only returned when the query is NOT scoped to the caller's
enrollment ids (pre-fix) or is scoped to the victim's enrollment id. The fix
queries scoped to the caller's owned enrollment ids, so the victim row is never
returned, never decrypted, never pushed.
"""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

ATTACKER = "user_attacker"
VICTIM = "user_victim"
VICTIM_ASSIGNMENT_ID = "assignment_owned_by_victim"
VICTIM_ENROLLMENT_ID = "enr_victim"
ATTACKER_ENROLLMENT_ID = "enr_attacker"

VICTIM_ROW = {
    "id": VICTIM_ASSIGNMENT_ID,
    "enrollment_id": VICTIM_ENROLLMENT_ID,
    "title": "Victim private assignment",
    "due_date": "2026-03-01",
    "notes": "ENC_secret_victim_notes",
    "google_event_id": None,
}


def _row_scoped_select(*_args, **kwargs):
    """Simulate a row-scoped table: return the victim row only when the
    enrollment_id filter includes the victim's enrollment — never when it's
    scoped to the attacker's enrollment."""
    filters = kwargs.get("filters", {})
    enr_filter = filters.get("enrollment_id", "")
    if not enr_filter or VICTIM_ENROLLMENT_ID in enr_filter:
        return [VICTIM_ROW]
    return []


class TestCalendarExportIDOR:
    def test_cannot_export_another_users_assignment(self):
        with patch("routes.calendar._require_google_creds", return_value=MagicMock()), \
             patch("routes.calendar.build") as build, \
             patch("routes.calendar.decrypt_if_present") as decrypt, \
             patch("routes.calendar.table") as t, \
             patch("routes.calendar.academics") as ac:
            service = MagicMock()
            service.events.return_value.insert.return_value.execute.return_value = {"id": "evt_new"}
            build.return_value = service
            t.return_value.select.side_effect = _row_scoped_select
            # Attacker only owns their own enrollment, NOT the victim's.
            ac.user_enrollment_ids.return_value = [
                {"id": ATTACKER_ENROLLMENT_ID, "offering_id": "o1"}
            ]

            # Attacker authenticates as themselves but targets the victim's id.
            r = client.post(
                "/api/calendar/export",
                json={"user_id": ATTACKER, "assignment_ids": [VICTIM_ASSIGNMENT_ID]},
            )

        assert r.status_code == 200
        # Nothing exported: the enrollment-scoped query found no row → skipped.
        assert r.json()["exported_count"] == 0
        # The victim's notes were never decrypted and never pushed to a calendar.
        decrypt.assert_not_called()
        service.events.return_value.insert.assert_not_called()
        # And the victim's row was never stamped (no data corruption).
        t.return_value.update.assert_not_called()

    def test_owner_can_export_their_own_assignment(self):
        """Control: scoping by enrollment_id must not break the legitimate path."""
        own_row = {**VICTIM_ROW, "id": "my_assignment", "enrollment_id": VICTIM_ENROLLMENT_ID}

        def _select(*_args, **kwargs):
            enr_filter = kwargs.get("filters", {}).get("enrollment_id", "")
            return [own_row] if VICTIM_ENROLLMENT_ID in enr_filter else []

        with patch("routes.calendar._require_google_creds", return_value=MagicMock()), \
             patch("routes.calendar.build") as build, \
             patch("routes.calendar.decrypt_if_present", return_value="secret"), \
             patch("routes.calendar.table") as t, \
             patch("routes.calendar.academics") as ac:
            service = MagicMock()
            service.events.return_value.insert.return_value.execute.return_value = {"id": "evt_new"}
            build.return_value = service
            t.return_value.select.side_effect = _select
            ac.user_enrollment_ids.return_value = [
                {"id": VICTIM_ENROLLMENT_ID, "offering_id": "o1"}
            ]

            r = client.post(
                "/api/calendar/export",
                json={"user_id": VICTIM, "assignment_ids": ["my_assignment"]},
            )

        assert r.status_code == 200
        assert r.json()["exported_count"] == 1
        service.events.return_value.insert.assert_called_once()
