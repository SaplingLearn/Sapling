"""Owner seeding against real local Supabase, with raw SQL and app API assertions."""
import pytest

from db import seed_local_rich
from e2e_oracles import judges
from e2e_oracles.gather import _CIPHERTEXT_MANIFEST, _ORPHAN_CHECKS
from services.encryption import decrypt
from tests.integration.conftest import _client_for

pytestmark = pytest.mark.integration


def test_personal_account_seed_populates_api_surfaces_and_stays_idempotent(
    db_conn, seeded_user, monkeypatch,
):
    monkeypatch.setenv("APP_ENV", "local")
    uid = seeded_user(onboarding_completed=False, name="Personal Developer")
    client = _client_for(uid)
    seed_local_rich.main(["--owner-user-id", uid])

    paths = [
        (f"/api/graph/{uid}/courses", "courses", 4),
        (f"/api/documents/user/{uid}", "documents", 3),
        (f"/api/notes/user/{uid}", "notes", 2),
        (f"/api/social/rooms/{uid}", "rooms", 2),
    ]
    for path, key, count in paths:
        response = client.get(path)
        assert response.status_code == 200, response.text
        payload = response.json()
        rows = payload if isinstance(payload, list) else payload[key]
        assert len(rows) == count
        if key in {"documents", "notes"}:
            stored_count = db_conn.execute(
                f'SELECT count(*) AS n FROM "{key}" WHERE user_id = %s AND deleted_at IS NULL', (uid,),
            ).fetchone()["n"]
            assert judges.count_findings(key, len(rows), stored_count) == []

    graph = client.get(f"/api/graph/{uid}")
    assert graph.status_code == 200, graph.text
    assert len([n for n in graph.json()["nodes"] if n.get("mastery_tier") != "subject_root"]) == 13
    quizzes = client.get("/api/quiz/attempts", params={"user_id": uid})
    assert quizzes.status_code == 200, quizzes.text
    assert len(quizzes.json()["attempts"]) == 3
    gradebook = client.get("/api/gradebook/summary", params={"user_id": uid, "semester": "Fall 2025"})
    assert gradebook.status_code == 200, gradebook.text
    assert len(gradebook.json()["courses"]) == 2
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["onboarding_completed"] is True

    chunks = db_conn.execute(
        "SELECT * FROM course_chunks WHERE uploader_id = %s", (uid,),
    ).fetchall()
    assert len(chunks) == 3
    assert all(row["visibility"] == "private" and row["embedding"] is not None for row in chunks)

    # Compare stored rows, including ciphertext/timestamps, rather than only
    # counts: a merge-upsert would re-encrypt and overwrite edits on every run.
    tables = ["users", "enrollments", "graph_nodes", "documents", "notes", "quiz_attempts", "course_chunks"]
    before = {
        name: db_conn.execute(f'SELECT * FROM "{name}" ORDER BY id').fetchall()
        for name in tables
    }
    seed_local_rich.main(["--owner-user-id", uid])
    for name in tables:
        assert db_conn.execute(f'SELECT * FROM "{name}" ORDER BY id').fetchall() == before[name]

    for name, pk, column in _CIPHERTEXT_MANIFEST:
        rows = db_conn.execute(
            f'SELECT "{pk}", "{column}" FROM "{name}" WHERE "{column}" IS NOT NULL',
        ).fetchall()
        assert judges.ciphertext_findings(name, column, [(r[pk], r[column]) for r in rows], decrypt) == []
    for name, sql in _ORPHAN_CHECKS:
        assert judges.orphan_findings(name, [r["id"] for r in db_conn.execute(sql).fetchall()]) == []


def test_owner_email_flag_finds_a_signed_in_account(db_conn, seeded_user, monkeypatch):
    monkeypatch.setenv("APP_ENV", "local")
    uid = seeded_user()
    seed_local_rich.main(["--owner-email", f"{uid}@integration.test"])
    assert db_conn.execute("SELECT count(*) AS n FROM enrollments WHERE user_id = %s", (uid,)).fetchone()["n"] == 5
