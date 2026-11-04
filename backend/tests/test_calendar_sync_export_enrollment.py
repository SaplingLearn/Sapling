# tests/test_calendar_sync_export_enrollment.py
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

class TestExportScoping:
    def test_export_skips_unowned_id(self):
        tables = {"assignments": _tbl(select=[], update=[])}  # id not owned -> no row
        creds = MagicMock()
        with patch("routes.calendar.table", side_effect=_dispatch(tables)), \
             patch("routes.calendar._require_google_creds", return_value=creds), \
             patch("routes.calendar.build") as build, \
             patch("routes.calendar.academics") as ac:
            ac.user_enrollment_ids.return_value = [{"id": "e1", "offering_id": "o1"}]
            r = client.post("/api/calendar/export",
                            json={"user_id": "user_andres", "assignment_ids": ["a-other"]})
        assert r.status_code == 200
        assert r.json() == {"exported_count": 0, "skipped_count": 0}
        build.return_value.events.return_value.insert.assert_not_called()

    def test_export_skips_undated_assignment(self):
        """An undated row must be skipped and counted, not sent to Google.

        Google rejects an all-day event with a null date, so one undated id in
        the payload used to fail the export partway through the batch.
        """
        rows = {
            "a-dated": {"id": "a-dated", "enrollment_id": "e1", "title": "PS 4",
                        "due_date": "2026-03-20", "notes": None, "google_event_id": None},
            "a-nodate": {"id": "a-nodate", "enrollment_id": "e1", "title": "Participation",
                         "due_date": None, "notes": None, "google_event_id": None},
        }
        assignments = MagicMock()
        assignments.select.side_effect = lambda *_a, **kw: [rows[kw["filters"]["id"][3:]]]
        tables = {"assignments": assignments}
        with patch("routes.calendar.table", side_effect=_dispatch(tables)), \
             patch("routes.calendar._require_google_creds", return_value=MagicMock()), \
             patch("routes.calendar.build") as build, \
             patch("routes.calendar._course_meta_cached", return_value={}), \
             patch("routes.calendar.academics") as ac:
            ac.user_enrollment_ids.return_value = [{"id": "e1", "offering_id": "o1"}]
            insert = build.return_value.events.return_value.insert
            insert.return_value.execute.return_value = {"id": "evt-1"}
            r = client.post("/api/calendar/export",
                            json={"user_id": "user_andres", "assignment_ids": ["a-nodate", "a-dated"]})
        assert r.status_code == 200
        assert r.json() == {"exported_count": 1, "skipped_count": 1}
        insert.assert_called_once()
        assert insert.call_args.kwargs["body"]["start"] == {"date": "2026-03-20"}
