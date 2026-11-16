"""The student's own full data export (services/profile/full_export.py).

Two students share a room and a course. Student A exports. The export must
carry A's data across every table, decrypted, and NOTHING of B's — not B's
rows in any table, not B's room message in the room they share — and no
secret (OAuth tokens, Gradescope credentials, a secret-named column).
"""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from services import encryption
from services.profile import full_export
from test_account_bundle import FakeDB  # the in-memory PostgREST stand-in

A, B = "user_alice", "user_bob"


def E(value: str) -> str:
    return encryption.encrypt_if_present(value)


def EJ(value) -> str:
    return encryption.encrypt_json(value)


def _seed() -> FakeDB:
    rows: dict[str, list[dict]] = {}

    def add(name, **row):
        rows.setdefault(name, []).append(row)

    for uid, tag in ((A, "ALICE"), (B, "BOB")):
        add("graph_nodes", id=f"gn-{uid}", user_id=uid, concept_name=f"{tag}_CONCEPT",
            course_id="course-1")
        add("node_mastery_events", id=f"me-{uid}", node_id=f"gn-{uid}", delta=0.1)
        add("documents", id=f"doc-{uid}", user_id=uid, offering_id="off-1",
            file_name=f"{tag}_FILE.pdf", summary=E(f"{tag}_DOC_SUMMARY"),
            extracted_text=E(f"{tag}_EXTRACTED_TEXT"), concept_notes=EJ([{"n": f"{tag}_CN"}]))
        add("enrollments", id=f"enr-{uid}", user_id=uid, offering_id="off-1")
        add("assignments", id=f"as-{uid}", enrollment_id=f"enr-{uid}", title=f"{tag}_ASSIGNMENT",
            notes=E(f"{tag}_ASSIGNMENT_NOTES"), points_earned=E("17"))
        add("notes", id=f"note-{uid}", user_id=uid, title=E(f"{tag}_NOTE_TITLE"),
            body=E(f"{tag}_NOTE_BODY"))
        add("flashcards", id=f"fc-{uid}", user_id=uid, front=E(f"{tag}_FRONT"), back=E(f"{tag}_BACK"))
        add("sessions", id=f"s-{uid}", user_id=uid, summary_json=EJ({"s": f"{tag}_SESSION"}),
            # An encrypted column the bundle's map does not list: still decrypted.
            close_json=EJ({"c": f"{tag}_CLOSE"}))
        add("messages", id=f"m-{uid}", session_id=f"s-{uid}", role="user",
            content=E(f"{tag}_CHAT_MESSAGE"))
        add("study_guides", id=f"sg-{uid}", user_id=uid, content=EJ({"g": f"{tag}_GUIDE"}))
        add("quiz_attempts", id=f"qa-{uid}", user_id=uid,
            questions_json=EJ([{"q": f"{tag}_QUESTION"}]), answers_json=EJ([f"{tag}_ANSWER"]))
        add("quiz_responses", id=f"qr-{uid}", attempt_id=f"qa-{uid}",
            answer_text=EJ(f"{tag}_WRITTEN_ANSWER"))
        add("xp_events", id=f"xp-{uid}", user_id=uid, amount=5, rule_key=f"{tag}_RULE")
        add("room_members", room_id="room-1", user_id=uid)
        add("room_messages", id=f"rm-{uid}", room_id="room-1", user_id=uid,
            user_name=tag, text=E(f"{tag}_ROOM_MESSAGE"), created_at="2026-11-01T00:00:00Z")
        add("gradescope_course_links", id=f"gl-{uid}", user_id=uid, gradescope_course_id="gc-1",
            access_token=f"{tag}_LEAKED_TOKEN")
        add("feedback", id=f"fb-{uid}", user_id=uid, comment=E(f"{tag}_FEEDBACK"))
        add("issue_reports", id=f"ir-{uid}", user_id=uid, description=E(f"{tag}_ISSUE"))
        add("oauth_tokens", id=f"ot-{uid}", user_id=uid, access_token=f"{tag}_OAUTH_TOKEN")
        add("gradescope_credentials", id=f"gc-{uid}", user_id=uid,
            password=f"{tag}_GRADESCOPE_PASSWORD")
    add("course_offerings", id="off-1", course_id="course-1", term_id="fall-2026", section="A1")
    add("courses", id="course-1", course_code="CAS CS 111", course_name="Intro CS")
    return FakeDB(rows)


class Recording(FakeDB):
    def __init__(self, base: FakeDB):
        super().__init__(base.data)
        self.read: list[str] = []

    def table(self, name):
        self.read.append(name)
        return super().table(name)


@pytest.fixture
def db(monkeypatch):
    fake = Recording(_seed())
    monkeypatch.setattr(full_export, "table", fake.table)
    return fake


def _export(user_id: str, head: dict | None = None) -> tuple[str, dict]:
    text = "".join(full_export.stream_export(user_id, head or {"user": {"id": user_id}}))
    return text, json.loads(text)


def test_export_carries_the_students_data_decrypted(db):
    text, doc = _export(A)
    tables = doc["tables"]
    for needle in (
        "ALICE_CONCEPT", "ALICE_DOC_SUMMARY", "ALICE_EXTRACTED_TEXT", "ALICE_CN",
        "ALICE_ASSIGNMENT_NOTES", "ALICE_NOTE_TITLE", "ALICE_NOTE_BODY", "ALICE_FRONT",
        "ALICE_SESSION", "ALICE_CLOSE", "ALICE_CHAT_MESSAGE", "ALICE_GUIDE", "ALICE_QUESTION",
        "ALICE_ANSWER", "ALICE_WRITTEN_ANSWER", "ALICE_ROOM_MESSAGE", "ALICE_FEEDBACK",
        "ALICE_ISSUE",
    ):
        assert needle in text, needle
    assert tables["notes"][0]["body"] == "ALICE_NOTE_BODY"
    assert tables["sessions"][0]["summary_json"] == {"s": "ALICE_SESSION"}
    assert tables["sessions"][0]["close_json"] == {"c": "ALICE_CLOSE"}
    assert tables["documents"][0]["concept_notes"] == [{"n": "ALICE_CN"}]
    assert tables["assignments"][0]["points_earned"] == "17"
    assert len(tables["node_mastery_events"]) == 1 and len(tables["quiz_responses"]) == 1
    assert doc["courses"]["courses"]["course-1"]["course_code"] == "CAS CS 111"
    assert doc["courses"]["offerings"]["off-1"]["term_id"] == "fall-2026"
    assert doc["export_format"] == full_export.EXPORT_FORMAT
    assert "oauth_tokens" in doc["not_included"]


def test_another_students_data_never_appears(db):
    text, doc = _export(A)
    assert "BOB" not in text
    assert "user_bob" not in text
    # The shared room: A's own message only.
    assert [m["id"] for m in doc["tables"]["room_messages"]] == [f"rm-{A}"]
    # And B's export holds none of A's.
    text_b, _ = _export(B)
    assert "ALICE" not in text_b and A not in text_b


def test_no_secret_is_read_or_exported(db):
    text, doc = _export(A)
    assert "oauth_tokens" not in db.read and "gradescope_credentials" not in db.read
    assert "OAUTH_TOKEN" not in text and "GRADESCOPE_PASSWORD" not in text
    assert "LEAKED_TOKEN" not in text
    assert "access_token" not in doc["tables"]["gradescope_course_links"][0]
    assert doc["tables"]["gradescope_course_links"][0]["gradescope_course_id"] == "gc-1"


def test_a_row_the_filter_let_through_for_someone_else_is_dropped(db, monkeypatch):
    """Defence in depth: a top-level row naming another user is never written,
    even if a read returned it."""
    real = db.table

    def leaky(name):
        t = real(name)
        if name == "notes":
            t.select = lambda *a, **k: [{"id": "x", "user_id": B, "body": E("BOB_LEAK")}]
        return t

    monkeypatch.setattr(full_export, "table", leaky)
    text, doc = _export(A)
    assert "BOB_LEAK" not in text and doc["tables"]["notes"] == []


def test_paging_reads_every_row_one_page_at_a_time(db, monkeypatch):
    monkeypatch.setattr(full_export, "_PAGE", 3)
    db.data["notes"] = [
        {"id": f"n{i:03d}", "user_id": A, "body": E(f"BODY{i}")} for i in range(10)
    ] + db.data["notes"]
    _, doc = _export(A)
    ids = [n["id"] for n in doc["tables"]["notes"]]
    assert len(ids) == 11 and len(set(ids)) == 11


def test_undecryptable_value_is_marked_not_fatal(db):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    import base64
    import os

    nonce = os.urandom(12)
    foreign = base64.b64encode(
        nonce + AESGCM(bytes.fromhex("33" * 32)).encrypt(nonce, b"other key", None)
    ).decode()
    db.data["notes"][0]["body"] = foreign
    _, doc = _export(A)
    note = next(n for n in doc["tables"]["notes"] if n["id"] == f"note-{A}")
    assert note["body"] == full_export.UNREADABLE


def test_every_bundle_table_is_exported():
    from services import account_bundle

    names = {s.name for s in full_export.SECTIONS}
    assert {s.name for s in account_bundle.SPECS} <= names
    assert not names & {"oauth_tokens", "gradescope_credentials", "course_chunks",
                        "room_summaries", "events", "llm_usage"}


# ── the route ───────────────────────────────────────────────────────────────


def _client():
    from fastapi import FastAPI

    import routes.profile as profile_module

    app = FastAPI()
    app.include_router(profile_module.router, prefix="/api/profile")
    return TestClient(app)


def test_route_streams_the_full_export(db, monkeypatch):
    import routes.profile as profile_module

    monkeypatch.setattr(profile_module, "_export_account_data",
                        lambda uid: {"user": {"id": uid}, "settings": {}, "roles": [],
                                     "achievements": [], "cosmetics": []})
    r = _client().post(f"/api/profile/{A}/export")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["content-type"].startswith("application/json")
    doc = r.json()
    assert doc["user"]["id"] == A and doc["roles"] == []
    assert doc["tables"]["notes"][0]["body"] == "ALICE_NOTE_BODY"
    assert "BOB" not in r.text


def test_route_requires_self_before_reading_anything(db, monkeypatch):
    """Another student's id in the path is refused by require_self before a
    single row is read."""
    import routes.profile as profile_module

    def require_self(user_id, request, **kw):
        assert kw.get("allow_unapproved") is True
        if user_id != B:  # the session belongs to B
            raise HTTPException(status_code=403, detail="Forbidden")

    monkeypatch.setattr(profile_module, "require_self", require_self)
    r = _client().post(f"/api/profile/{A}/export")
    assert r.status_code == 403
    assert db.read == []


def test_route_missing_account_is_a_clean_404(db, monkeypatch):
    import routes.profile as profile_module

    def gone(uid):
        raise HTTPException(status_code=404, detail="User not found")

    monkeypatch.setattr(profile_module, "_export_account_data", gone)
    r = _client().post(f"/api/profile/{A}/export")
    assert r.status_code == 404
    assert db.read == []
