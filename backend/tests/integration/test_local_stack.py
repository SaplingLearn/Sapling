"""Opt-in integration tests against the real local Supabase (#362).

Run: RUN_INTEGRATION=1 dotenv -f .env run -- \
     /home/andresl/Projects/sapling/backend/venv/bin/python -m pytest -m integration -q
(from backend/, local stack up). The conftest also loads .env, so plain
`RUN_INTEGRATION=1 pytest -m integration` works too.
"""
import pytest

from db.connection import table
from services.encryption import (
    decrypt_if_present, decrypt_numeric, encrypt_if_present,
)
from tests.integration.conftest import mint_session

pytestmark = pytest.mark.integration

_ACTIVE = "rich-user-active"


def test_db_roundtrip_write_read_delete():
    """A real insert → select → delete through db.connection.table()."""
    rid = "rich-it-school-roundtrip"
    table("schools").upsert(
        {"id": rid, "name": "IT Roundtrip", "slug": rid}, on_conflict="id"
    )
    rows = table("schools").select("id,slug", filters={"id": f"eq.{rid}"})
    assert rows and rows[0]["slug"] == rid
    table("schools").delete({"id": f"eq.{rid}"})
    assert table("schools").select("id", filters={"id": f"eq.{rid}"}) == []


def test_encryption_roundtrip_text_and_numeric():
    """Write encrypted → read raw → decrypt; both text and numeric paths."""
    nid = "rich-it-note-enc"
    secret = "integration-secret-body-✓"
    table("notes").upsert(
        {
            "id": nid,
            "user_id": _ACTIVE,
            "offering_id": "rich-off-cs101-s26",
            "title": encrypt_if_present("IT note"),
            "body": encrypt_if_present(secret),
            "tags": ["it"],
        },
        on_conflict="id",
    )
    raw = table("notes").select("body", filters={"id": f"eq.{nid}"})[0]["body"]
    assert raw != secret                       # stored ciphertext, not plaintext
    assert decrypt_if_present(raw) == secret   # round-trips back
    # numeric path via decrypt_numeric
    enc_points = encrypt_if_present("87.5")
    assert decrypt_numeric(enc_points) == 87.5
    table("notes").delete({"id": f"eq.{nid}"})


def test_route_e2e_auth_me(client, anon_client):
    """Full route E2E: real auth guard + real DB + real decryption."""
    anon = anon_client.get("/api/auth/me")
    assert anon.status_code == 401             # no cookie → unauthenticated

    client.cookies.set("sapling_session", mint_session(_ACTIVE))
    res = client.get("/api/auth/me")
    assert res.status_code == 200
    data = res.json()
    assert data["user_id"] == _ACTIVE
    assert data["is_approved"] is True
    assert isinstance(data["name"], str) and data["name"]   # decrypted display name


def test_route_e2e_gradebook_decrypt_numeric(client):
    """Gradebook route returns decrypt_numeric'd points end-to-end."""
    client.cookies.set("sapling_session", mint_session(_ACTIVE))
    # rich-user-active is enrolled in CS101 spring-2026 with graded assignments.
    res = client.get(
        "/api/gradebook/courses/rich-course-cs101",
        params={"user_id": _ACTIVE, "semester": "Spring 2026"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    graded = [a for a in body["assignments"] if a.get("points_earned") is not None]
    assert graded, "expected at least one graded assignment"
    for a in graded:
        assert isinstance(a["points_earned"], (int, float))     # decrypted numeric
        assert isinstance(a["points_possible"], (int, float))
