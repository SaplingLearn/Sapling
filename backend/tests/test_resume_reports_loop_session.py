"""#866 Z08 (review): the resume payload says whether a session is a
learning-loop session, so a client that resumes it with the loop off (the
kill switch, or the flag off after the beta) still draws its transcript inert.

A loop session's saved rows include code-served class material (H2 passages,
H4/H6 payloads) that may carry links, autolinks or directives; the legacy
Tutor renders a resumed transcript through ChatPanel, so it needs the marker.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from main import app
from services import tutor_sessions
from tests.db_fakes import with_async_twins
from tests.split_patches import patch_tutor

pytestmark = pytest.mark.usefixtures("no_sync_db_on_loop")

client = TestClient(app)


def _resume(row: dict, seen: dict):
    def factory(name):
        mock = MagicMock()

        def select(cols, filters=None, order=None, limit=None, **_k):
            if name == "sessions":
                seen.setdefault("cols", []).append(cols)
                return [dict(row)]
            if name == "messages":
                return [{"id": "m1", "role": "assistant", "content": "Hello!",
                         "created_at": "2026-01-01T00:00:01"}]
            return []
        mock.select.side_effect = select
        return mock

    with patch_tutor("table", side_effect=with_async_twins(factory)):
        return client.get(f"/api/learn/sessions/{row['id']}/resume?user_id=u1")


BASE = {"user_id": "u1", "topic": "Loops", "mode": "socratic",
        "started_at": "2026-01-01T00:00:00", "ended_at": None, "offering_id": None}


# the marker is bool(phase): the first and the last phase stand for all four
@pytest.mark.parametrize("phase", ["probe", "close"])
def test_a_loop_session_resumes_marked_loop(phase):
    seen: dict = {}
    r = _resume({"id": "s-loop", **BASE, "loop_phase": phase}, seen)
    assert r.status_code == 200, r.text
    session = r.json()["session"]
    assert session["loop"] is True
    assert "loop_phase" not in session  # the marker is a bool, never the raw phase
    assert any("loop_phase:loop_state->>phase" in c for c in seen["cols"])


def test_a_legacy_session_resumes_unmarked():
    seen: dict = {}
    r = _resume({"id": "s-legacy", **BASE, "loop_phase": None}, seen)
    assert r.status_code == 200, r.text
    assert r.json()["session"]["loop"] is False
    assert r.json()["messages"][0]["content"] == "Hello!"


@pytest.mark.parametrize("loop", [True, False])
def test_a_pending_session_carries_its_loop_marker(loop):
    sid = f"s-pending-{loop}"
    payload = {"user_id": "u1", "mode": "socratic", "topic": "T", "offering_id": None,
               "assistant_reply": "Hi!", "graph_update": {}}
    if loop:
        payload["loop"] = True
    tutor_sessions.stash_pending(sid, payload)
    try:
        r = client.get(f"/api/learn/sessions/{sid}/resume?user_id=u1")
    finally:
        tutor_sessions.discard_if_pending(sid, user_id="u1", reason="deleted", always=True)
    assert r.status_code == 200, r.text
    assert r.json()["session"]["loop"] is loop
