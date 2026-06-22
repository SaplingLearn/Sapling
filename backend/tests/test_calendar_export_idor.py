"""
Regression test for #123: calendar.export_to_google cross-user IDOR.

Pre-fix, export_to_google selected each assignment by `id` alone, so an
authenticated user could pass ANOTHER user's assignment UUIDs to read+decrypt
their private notes, push them into the caller's Google Calendar, and stamp
google_event_id onto the victim's row. The fix scopes the select (and the
write-back) by user_id, so a non-owned id returns no row and is skipped.

The cross-user test makes the DB mock behave like a real row-scoped store: the
victim's row is only returned when the query is NOT scoped to the caller
(pre-fix) or is scoped to the victim. The fix queries scoped to the caller, so
the victim row is never returned, never decrypted, never pushed.
"""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

ATTACKER = "user_attacker"
VICTIM = "user_victim"
VICTIM_ASSIGNMENT_ID = "assignment_owned_by_victim"

VICTIM_ROW = {
    "id": VICTIM_ASSIGNMENT_ID,
    "title": "Victim private assignment",
    "due_date": "2026-03-01",
    "notes": "ENC_secret_victim_notes",
    "google_event_id": None,
    "courses": {"course_code": "BIO101", "course_name": "Biology"},
}


def _row_scoped_select(*_args, **kwargs):
    """Simulate a row-scoped table: return the victim row only for an unscoped
    query (pre-fix) or one scoped to the victim — never for one scoped to the
    attacker."""
    filters = kwargs.get("filters", {})
    uid = filters.get("user_id")
    if uid is None or uid == f"eq.{VICTIM}":
        return [VICTIM_ROW]
    return []


class TestCalendarExportIDOR:
    def test_cannot_export_another_users_assignment(self):
        with patch("routes.calendar._require_google_creds", return_value=MagicMock()), \
             patch("routes.calendar.build") as build, \
             patch("routes.calendar.decrypt_if_present") as decrypt, \
             patch("routes.calendar.table") as t:
            service = MagicMock()
            service.events.return_value.insert.return_value.execute.return_value = {"id": "evt_new"}
            build.return_value = service
            t.return_value.select.side_effect = _row_scoped_select

            # Attacker authenticates as themselves but targets the victim's id.
            r = client.post(
                "/api/calendar/export",
                json={"user_id": ATTACKER, "assignment_ids": [VICTIM_ASSIGNMENT_ID]},
            )

        assert r.status_code == 200
        # Nothing exported: the user_id-scoped query found no row → skipped.
        assert r.json()["exported_count"] == 0
        # The victim's notes were never decrypted and never pushed to a calendar.
        decrypt.assert_not_called()
        service.events.return_value.insert.assert_not_called()
        # And the victim's row was never stamped (no data corruption).
        t.return_value.update.assert_not_called()

    def test_owner_can_export_their_own_assignment(self):
        """Control: scoping by user_id must not break the legitimate path."""
        own_row = {**VICTIM_ROW, "id": "my_assignment"}

        def _select(*_args, **kwargs):
            uid = kwargs.get("filters", {}).get("user_id")
            return [own_row] if uid == f"eq.{VICTIM}" else []

        with patch("routes.calendar._require_google_creds", return_value=MagicMock()), \
             patch("routes.calendar.build") as build, \
             patch("routes.calendar.decrypt_if_present", return_value="secret"), \
             patch("routes.calendar.table") as t:
            service = MagicMock()
            service.events.return_value.insert.return_value.execute.return_value = {"id": "evt_new"}
            build.return_value = service
            t.return_value.select.side_effect = _select

            r = client.post(
                "/api/calendar/export",
                json={"user_id": VICTIM, "assignment_ids": ["my_assignment"]},
            )

        assert r.status_code == 200
        assert r.json()["exported_count"] == 1
        service.events.return_value.insert.assert_called_once()
