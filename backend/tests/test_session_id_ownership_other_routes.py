"""Non-tutor routes that take a tutor session id apply the same ownership
rule as routes/learn.py (services/tutor_sessions.py).

- POST /api/flashcards/generate reads and decrypts `sessions.summary_json`
  into the prompt. A missing or foreign session id is a 404, decided BEFORE
  anything is read or decrypted.
- POST /api/feedback stores `session_id` on the row. A session id the
  caller doesn't own is dropped (stored NULL) instead of failing the
  user's feedback.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from services.tutor_sessions import PENDING_SESSIONS

client = TestClient(app)

OWNER = "user_owner"
INTRUDER = "user_intruder"
SESSION = "sess-owned-by-owner"
PENDING = "sess-pending-owner"


def _sessions_table(owner: str | None = OWNER):
    """`services.tutor_sessions.table` stand-in: `sessions` answers with one
    row owned by `owner` (or nothing)."""
    sessions = MagicMock(name="table(sessions)")
    sessions.select.return_value = [{"user_id": owner}] if owner else []

    def factory(name):
        if name == "sessions":
            return sessions
        m = MagicMock(name=f"table({name})")
        m.select.return_value = []
        return m

    factory.sessions = sessions
    return factory


@pytest.fixture
def pending_for_owner():
    PENDING_SESSIONS[PENDING] = {"user_id": OWNER, "topic": "t", "mode": "socratic"}
    yield
    PENDING_SESSIONS.pop(PENDING, None)


# ── POST /api/flashcards/generate ────────────────────────────────────────────

def _flash_tables():
    """`routes.flashcards.table` stand-in; records summary reads."""
    mocks: dict[str, MagicMock] = {}

    def factory(name):
        if name not in mocks:
            m = MagicMock(name=f"flash.table({name})")
            m.select.return_value = (
                [{"summary_json": {"concepts_covered": ["Recursion"]}}]
                if name == "sessions" else []
            )
            m.insert.return_value = []
            mocks[name] = m
        return mocks[name]

    factory.mocks = mocks
    return factory


def _generate(uid, sid):
    return client.post("/api/flashcards/generate", json={
        "user_id": uid, "topic": "CS", "count": 1, "session_id": sid,
    })


@pytest.fixture
def flash():
    flash_tables = _flash_tables()
    with patch("routes.flashcards.table", side_effect=flash_tables), \
         patch("routes.flashcards._get_course_documents", return_value=[]), \
         patch("routes.flashcards._get_weak_concepts", return_value=[]), \
         patch("routes.flashcards._generate",
               return_value=[{"front": "q", "back": "a"}]) as gen, \
         patch("routes.flashcards.decrypt_json") as dec, \
         patch("services.achievement_service.check_achievements"):
        yield {"tables": flash_tables, "generate": gen, "decrypt_json": dec}


def _summary_read(flash) -> bool:
    m = flash["tables"].mocks.get("sessions")
    return bool(m and m.select.called)


@pytest.mark.parametrize("owner", [OWNER, None], ids=["foreign", "missing"])
def test_generate_with_foreign_or_missing_session_is_404_before_summary_read(flash, owner):
    with patch("services.tutor_sessions.table", side_effect=_sessions_table(owner)):
        r = _generate(INTRUDER if owner else OWNER, SESSION)
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "Session not found"
    assert not _summary_read(flash), "must not read another student's session summary"
    assert not flash["decrypt_json"].called, "must not decrypt another student's summary"
    assert not flash["generate"].called, "no model call"
    assert not flash["tables"].mocks.get("flashcards", MagicMock()).insert.called


def test_generate_with_own_session_uses_its_summary(flash):
    with patch("services.tutor_sessions.table", side_effect=_sessions_table(OWNER)):
        r = _generate(OWNER, SESSION)
    assert r.status_code == 200, r.text
    assert _summary_read(flash)
    assert "Recursion" in flash["generate"].call_args.kwargs["context"]


def test_generate_without_session_id_skips_the_check(flash):
    st = _sessions_table(OWNER)
    with patch("services.tutor_sessions.table", side_effect=st):
        r = client.post("/api/flashcards/generate", json={
            "user_id": OWNER, "topic": "CS", "count": 1,
        })
    assert r.status_code == 200, r.text
    assert not st.sessions.select.called


def test_generate_with_someone_elses_pending_session_is_404(flash, pending_for_owner):
    with patch("services.tutor_sessions.table", side_effect=_sessions_table(None)):
        r = _generate(INTRUDER, PENDING)
    assert r.status_code == 404
    assert PENDING in PENDING_SESSIONS
    assert not _summary_read(flash)


def test_generate_with_own_pending_session_works(flash, pending_for_owner):
    with patch("services.tutor_sessions.table", side_effect=_sessions_table(None)):
        r = _generate(OWNER, PENDING)
    assert r.status_code == 200, r.text


# ── POST /api/feedback ───────────────────────────────────────────────────────

def _feedback(uid, sid):
    recorded: list = []
    fb = MagicMock(name="table(feedback)")
    fb.insert.side_effect = lambda data: recorded.append(data) or [data]
    with patch("routes.feedback.table", return_value=fb):
        # The conftest auth stub reads the session user off ?user_id=.
        r = client.post(f"/api/feedback?user_id={uid}", json={
            "user_id": uid, "type": "session", "rating": 4,
            "comment": "ok", "session_id": sid,
        })
    return r, recorded


def test_feedback_keeps_own_session_id():
    with patch("services.tutor_sessions.table", side_effect=_sessions_table(OWNER)):
        r, rows = _feedback(OWNER, SESSION)
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert rows[0]["session_id"] == SESSION


@pytest.mark.parametrize("owner", [OWNER, None], ids=["foreign", "missing"])
def test_feedback_drops_foreign_or_missing_session_id(owner):
    """The feedback itself still lands; only the unowned link is dropped."""
    with patch("services.tutor_sessions.table", side_effect=_sessions_table(owner)):
        r, rows = _feedback(INTRUDER if owner else OWNER, SESSION)
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert len(rows) == 1
    assert rows[0]["session_id"] is None
    assert rows[0]["rating"] == 4


def test_feedback_drops_pending_session_id(pending_for_owner):
    """A pending session has no `sessions` row yet, so storing its id would
    violate feedback.session_id's FK. Even the owner's pending id is dropped."""
    with patch("services.tutor_sessions.table", side_effect=_sessions_table(None)):
        r, rows = _feedback(OWNER, PENDING)
    assert r.status_code == 200
    assert rows[0]["session_id"] is None


def test_feedback_without_session_id_skips_the_check():
    st = _sessions_table(OWNER)
    with patch("services.tutor_sessions.table", side_effect=st):
        r, rows = _feedback(OWNER, None)
    assert r.status_code == 200
    assert rows[0]["session_id"] is None
    assert not st.sessions.select.called
