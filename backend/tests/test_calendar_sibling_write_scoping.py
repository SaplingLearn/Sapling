"""
Defense-in-depth follow-up to #123: the assignment mutation endpoints
(update / delete / sync) do a user_id-scoped SELECT and 404 a non-owned id
before writing, so they're not exploitable today — but their write filters
were id-only, relying solely on that guard. These tests assert the write/delete
now also scope by user_id, so a future change to the read-guard can't silently
reopen the IDOR.
"""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

OWNER = "user_andres"
AID = "assignment_1"


class TestSiblingWriteScoping:
    def test_update_scopes_write_by_user_id(self):
        with patch("routes.calendar.table") as t:
            t.return_value.select.return_value = [{"id": AID}]  # owner's row exists
            r = client.patch(
                f"/api/calendar/assignments/{AID}",
                json={"user_id": OWNER, "title": "New title"},
            )
        assert r.status_code == 200
        # The UPDATE filter must include user_id, not just id.
        update_filters = t.return_value.update.call_args.kwargs["filters"]
        assert update_filters.get("user_id") == f"eq.{OWNER}"
        assert update_filters.get("id") == f"eq.{AID}"

    def test_delete_scopes_delete_by_user_id(self):
        with patch("routes.calendar.table") as t:
            t.return_value.select.return_value = [{"id": AID}]
            r = client.delete(f"/api/calendar/assignments/{AID}?user_id={OWNER}")
        assert r.status_code == 200
        delete_filters = t.return_value.delete.call_args.kwargs["filters"]
        assert delete_filters.get("user_id") == f"eq.{OWNER}"
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
