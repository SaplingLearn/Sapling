"""Opt-in integration tests against the real local Supabase (#362, #397).

Run: RUN_INTEGRATION=1 dotenv -f .env run -- \
     python -m pytest -m integration -q
(from backend/, local stack up). The conftest also loads .env, so plain
`RUN_INTEGRATION=1 pytest -m integration` works too.

The lane's rule (#397): **writes go through the app; assertions read back with
raw SQL** via the session `db_conn` (psycopg), never through the same PostgREST
`table()` layer that made the write. Auth comes from `authed_client` /
`other_user_client`; isolation comes from the autouse truncate + reseed.
"""
import pytest

from db.connection import table
from services.encryption import (
    decrypt_if_present, decrypt_numeric, encrypt_if_present,
)
from tests.integration.conftest import COURSE_CS, USER_ACTIVE, USER_SECOND

pytestmark = pytest.mark.integration

# Seeded offering ids (mirror db/seed_local_rich; literals keep config imports
# deferred — see the conftest header).
OFF_CS_F25 = "rich-off-cs101-f25"
OFF_CS_S26 = "rich-off-cs101-s26"


# ── The raw-SQL seam: write via the app, assert with psycopg (#397) ─────────


def test_note_created_via_app_is_encrypted_at_rest(authed_client, db_conn):
    """The flagship pattern: POST a note through the real route, then read the
    raw `body` column with psycopg. The write went through PostgREST; the
    assertion does NOT — so a broken encrypt-on-write or a wrong column would be
    caught, where a table()-both-ways round-trip would only prove the echo."""
    secret = "raw-sql-secret ✓ gradient descent minimizes loss"
    res = authed_client.post(
        "/api/notes",
        json={
            "user_id": USER_ACTIVE,
            "course_id": COURSE_CS,
            "title": "Encrypted-at-rest note",
            "body": secret,
            "tags": ["it-raw-sql"],
        },
    )
    assert res.status_code == 200, res.text
    note_id = res.json()["id"]

    row = db_conn.execute(
        "SELECT body FROM notes WHERE id = %s", (note_id,)
    ).fetchone()
    assert row is not None, "note the app claims to have written is absent in raw SQL"
    raw_body = row["body"]
    assert raw_body != secret, "body stored as plaintext — encryption-on-write regressed"
    assert decrypt_if_present(raw_body) == secret, "ciphertext does not round-trip back"


def test_db_roundtrip_write_read_delete(db_conn):
    """Low-level insert/delete via table(), but every assertion reads through raw
    SQL (psycopg) rather than table() — so this exercises the database, not the
    PostgREST echo of the write."""
    rid = "rich-it-school-roundtrip"
    try:
        table("schools").upsert(
            {"id": rid, "name": "IT Roundtrip", "slug": rid}, on_conflict="id"
        )
        row = db_conn.execute(
            "SELECT slug FROM schools WHERE id = %s", (rid,)
        ).fetchone()
        assert row is not None and row["slug"] == rid
    finally:
        table("schools").delete({"id": f"eq.{rid}"})
    gone = db_conn.execute("SELECT id FROM schools WHERE id = %s", (rid,)).fetchall()
    assert gone == []


def test_encryption_roundtrip_text_and_numeric(db_conn):
    """Write an encrypted note via table(), then read the raw ciphertext column
    with psycopg: the stored bytes must be ciphertext, and must decrypt back."""
    nid = "rich-it-note-enc"
    secret = "integration-secret-body-✓"
    try:
        table("notes").upsert(
            {
                "id": nid,
                "user_id": USER_ACTIVE,
                "offering_id": OFF_CS_S26,
                "title": encrypt_if_present("IT note"),
                "body": encrypt_if_present(secret),
                "tags": ["it"],
            },
            on_conflict="id",
        )
        raw = db_conn.execute(
            "SELECT body FROM notes WHERE id = %s", (nid,)
        ).fetchone()["body"]
        assert raw != secret                       # stored ciphertext, not plaintext
        assert decrypt_if_present(raw) == secret   # round-trips back
        # numeric path via decrypt_numeric — this is the unit-level check; the
        # real DB numeric round-trip is covered end-to-end by
        # test_route_e2e_gradebook_decrypt_numeric.
        enc_points = encrypt_if_present("87.5")
        assert decrypt_numeric(enc_points) == 87.5
    finally:
        table("notes").delete({"id": f"eq.{nid}"})


# ── Auth fixtures replace the per-test cookie boilerplate (#397) ────────────


def test_route_e2e_auth_me(authed_client, anon_client):
    """Full route E2E: real auth guard + real DB + real decryption."""
    anon = anon_client.get("/api/auth/me")
    assert anon.status_code == 401             # no cookie → unauthenticated

    res = authed_client.get("/api/auth/me")
    assert res.status_code == 200
    data = res.json()
    assert data["user_id"] == USER_ACTIVE
    assert data["is_approved"] is True
    assert isinstance(data["name"], str) and data["name"]   # decrypted display name


def test_authed_and_other_user_are_distinct(authed_client, other_user_client):
    """authed_client and other_user_client must resolve to genuinely different
    real users — the precondition for every ownership/IDOR negative (#397)."""
    me = authed_client.get("/api/auth/me").json()
    them = other_user_client.get("/api/auth/me").json()
    assert me["user_id"] == USER_ACTIVE
    assert them["user_id"] == USER_SECOND
    assert me["user_id"] != them["user_id"]


def test_route_e2e_gradebook_decrypt_numeric(authed_client):
    """Gradebook route returns decrypt_numeric'd points end-to-end."""
    # rich-user-active is enrolled in CS101 spring-2026 with graded assignments.
    res = authed_client.get(
        "/api/gradebook/courses/rich-course-cs101",
        params={"user_id": USER_ACTIVE, "semester": "Spring 2026"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    graded = [a for a in body["assignments"] if a.get("points_earned") is not None]
    assert graded, "expected at least one graded assignment"
    for a in graded:
        assert isinstance(a["points_earned"], (int, float))     # decrypted numeric
        assert isinstance(a["points_possible"], (int, float))


# ── seeded_user factory (#397) ─────────────────────────────────────────────


def test_seeded_user_factory_makes_distinct_approved_users(seeded_user, db_conn):
    """Each call mints a distinct, approved user with a real row."""
    a = seeded_user(name="Alice IT")
    b = seeded_user(name="Bob IT")
    assert a != b
    rows = db_conn.execute(
        "SELECT id, is_approved FROM users WHERE id = ANY(%s)", ([a, b],)
    ).fetchall()
    assert {r["id"] for r in rows} == {a, b}
    assert all(r["is_approved"] for r in rows)


# ── Truncate isolation, proven order-independently (#397) ───────────────────
#
# Both tests insert a note with the SAME fixed id. If the autouse reset did not
# run between them, the second insert to run would either see a leaked row or
# collide on the PK. `_second` asserts the id is absent at entry, so it proves
# isolation whichever order the two run in (default, reversed, or shuffled).
_ISO_NOTE_ID = "it-iso-note-fixed-id"


def _insert_iso_note() -> None:
    table("notes").insert(
        {
            "id": _ISO_NOTE_ID,
            "user_id": USER_ACTIVE,
            "offering_id": OFF_CS_F25,
            "tags": ["iso"],
        }
    )


def test_truncate_isolation_first(db_conn):
    _insert_iso_note()
    rows = db_conn.execute(
        "SELECT id FROM notes WHERE id = %s", (_ISO_NOTE_ID,)
    ).fetchall()
    assert len(rows) == 1


def test_truncate_isolation_second(db_conn):
    pre = db_conn.execute(
        "SELECT id FROM notes WHERE id = %s", (_ISO_NOTE_ID,)
    ).fetchall()
    assert pre == [], "reset did not run: a prior test's row leaked into this one"
    _insert_iso_note()
    rows = db_conn.execute(
        "SELECT id FROM notes WHERE id = %s", (_ISO_NOTE_ID,)
    ).fetchall()
    assert len(rows) == 1
