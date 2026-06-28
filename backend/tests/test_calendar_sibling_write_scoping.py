"""
Defense-in-depth follow-up to #123: the assignment mutation endpoints
(update / delete / sync) scope reads AND writes by enrollment_id membership,
so a caller cannot touch another user's assignments even if they know the UUID.
These tests assert both the SELECT guard and the write/delete filter scope by
enrollment_id (not user_id, which no longer exists on the assignments table).
"""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

OWNER = "user_andres"
AID = "assignment_1"
ENROLLMENT_ID = "e1"


class TestSiblingWriteScoping:
    def test_update_scopes_write_by_enrollment_id(self):
        with patch("routes.calendar.table") as t, \
             patch("routes.calendar.academics") as ac:
            ac.user_enrollment_ids.return_value = [{"id": ENROLLMENT_ID, "offering_id": "o1"}]
            t.return_value.select.return_value = [{"id": AID}]  # owner's row exists
            r = client.patch(
                f"/api/calendar/assignments/{AID}",
                json={"user_id": OWNER, "title": "New title"},
            )
        assert r.status_code == 200
        # The UPDATE filter must scope by enrollment_id, not user_id.
        update_filters = t.return_value.update.call_args.kwargs["filters"]
        assert "enrollment_id" in update_filters
        assert ENROLLMENT_ID in update_filters["enrollment_id"]
        assert update_filters.get("id") == f"eq.{AID}"

    def test_delete_scopes_delete_by_enrollment_id(self):
        with patch("routes.calendar.table") as t, \
             patch("routes.calendar.academics") as ac:
            ac.user_enrollment_ids.return_value = [{"id": ENROLLMENT_ID, "offering_id": "o1"}]
            t.return_value.select.return_value = [{"id": AID}]
            r = client.delete(f"/api/calendar/assignments/{AID}?user_id={OWNER}")
        assert r.status_code == 200
        delete_filters = t.return_value.delete.call_args.kwargs["filters"]
        assert "enrollment_id" in delete_filters
        assert ENROLLMENT_ID in delete_filters["enrollment_id"]
        assert delete_filters.get("id") == f"eq.{AID}"

    def test_sync_scopes_writeback_by_user_id(self):
        unsynced = [{
            "id": AID, "title": "HW", "due_date": "2026-03-01",
            "notes": None, "google_event_id": None, "courses": {},
        }]

        with patch("routes.calendar._require_google_creds", return_value=MagicMock()), \
             patch("routes.calendar.build") as build, \
             patch("routes.calendar.decrypt_if_present", return_value=""), \
             patch("routes.calendar.table") as t:
            service = MagicMock()
            service.events.return_value.insert.return_value.execute.return_value = {"id": "evt_1"}
            build.return_value = service
            # select returns the unsynced row on the first call, [] thereafter.
            t.return_value.select.side_effect = [unsynced, []]
            r = client.post("/api/calendar/sync", json={"user_id": OWNER})

        assert r.status_code == 200
        update_filters = t.return_value.update.call_args.kwargs["filters"]
        assert update_filters.get("user_id") == f"eq.{OWNER}"
        assert update_filters.get("id") == f"eq.{AID}"
