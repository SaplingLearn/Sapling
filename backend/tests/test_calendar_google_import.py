from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import calendar

app = FastAPI()
app.include_router(calendar.router, prefix="/api/calendar")
client = TestClient(app)
RANGE = "time_min=2026-11-01T00:00:00Z&time_max=2026-12-01T00:00:00Z"


def event(event_id="g1", **extra):
    return {"id": event_id, "summary": "Workshop", "start": {"date": "2026-11-02"},
            "end": {"date": "2026-11-03"}, **extra}


def test_import_reads_every_calendar_and_event_page_without_duplicates():
    service = MagicMock()
    service.calendarList.return_value.list.return_value.execute.side_effect = [
        {"items": [{"id": "c1", "primary": True}], "nextPageToken": "cal-page-2"},
        {"items": [{"id": "c2", "summary": "Classes"}, {"id": "c1", "primary": True}]},
    ]
    service.events.return_value.list.return_value.execute.side_effect = [
        {"items": [event()], "nextPageToken": "events-page-2"},
        {"items": [], "nextPageToken": "events-page-3"},
        {"items": [event(), event("g2"), event("cancelled", status="cancelled")]},
        {"items": [event()]},
    ]
    with patch.object(calendar, "_require_google_creds"), patch.object(calendar, "build", return_value=service):
        response = client.get(f"/api/calendar/import/u1?{RANGE}")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["count"] == 3
    assert [(e["calendar_id"], e["google_event_id"]) for e in response.json()["events"]] == [
        ("c1", "g1"), ("c1", "g2"), ("c2", "g1"),
    ]
    calls = service.events.return_value.list.call_args_list
    assert calls[2].kwargs["pageToken"] == "events-page-3"
    assert calls[0].kwargs["singleEvents"] is True
    assert response.json()["events"][0]["primary_calendar"] is True


@pytest.mark.parametrize("query", [
    "time_min=2026-11-01T00:00:00Z",
    "time_min=2026-11-01T00:00:00&time_max=2026-12-01T00:00:00",
    "time_min=2026-12-01T00:00:00Z&time_max=2026-11-01T00:00:00Z",
    "time_min=2026-01-01T00:00:00Z&time_max=2028-01-01T00:00:00Z",
])
def test_invalid_ranges_do_not_call_google(query):
    with patch.object(calendar, "_require_google_creds") as creds:
        assert client.get(f"/api/calendar/import/u1?{query}").status_code == 400
    creds.assert_not_called()


def test_google_failure_returns_actionable_error_instead_of_partial_success():
    service = MagicMock()
    service.calendarList.return_value.list.return_value.execute.side_effect = RuntimeError("private provider detail")
    with patch.object(calendar, "_require_google_creds"), patch.object(calendar, "build", return_value=service):
        response = client.get(f"/api/calendar/import/u1?{RANGE}")
    assert response.status_code == 502
    assert "private provider detail" not in response.text
    assert "reconnect" in response.json()["detail"]


def test_import_cannot_read_another_users_google_account(monkeypatch):
    from services import auth_guard

    monkeypatch.setattr(calendar, "require_self", auth_guard._real_require_self)
    monkeypatch.setattr(auth_guard, "get_session_user_id", lambda request: "someone-else")
    with patch.object(calendar, "_require_google_creds") as creds:
        response = client.get(f"/api/calendar/import/u1?{RANGE}")
    assert response.status_code == 403
    creds.assert_not_called()


def test_event_disconnect_and_reconnect_preserve_google_credentials():
    row = {"user_id": "u1", "access_token": "encrypted-access", "refresh_token": "encrypted-refresh",
           "expires_at": "2030-01-01T00:00:00Z", "calendar_events_enabled": True}
    token_table = MagicMock()
    token_table.select.side_effect = lambda *args, **kwargs: [dict(row)]
    token_table.update.side_effect = lambda data, **kwargs: row.update(data) or [dict(row)]
    with patch.object(calendar, "table", return_value=token_table):
        assert client.delete("/api/calendar/disconnect/u1").status_code == 200
        status = client.get("/api/calendar/status/u1").json()
        assert status["connected"] is True
        assert status["events_enabled"] is False
        assert client.post("/api/calendar/connect/u1").status_code == 200
        assert client.get("/api/calendar/status/u1").json()["events_enabled"] is True
    token_table.delete.assert_not_called()
    assert row["access_token"] == "encrypted-access"
    assert row["refresh_token"] == "encrypted-refresh"


def test_import_is_blocked_when_events_are_disconnected(monkeypatch):
    token_table = MagicMock()
    token_table.select.return_value = [{"access_token": "encrypted", "calendar_events_enabled": False}]
    monkeypatch.setattr(calendar, "GOOGLE_AVAILABLE", True)
    monkeypatch.setattr(calendar, "GOOGLE_CLIENT_ID", "mock-id")
    with patch.object(calendar, "table", return_value=token_table), patch.object(calendar, "build") as build:
        assert client.get(f"/api/calendar/import/u1?{RANGE}").status_code == 409
    build.assert_not_called()
