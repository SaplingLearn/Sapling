"""STAGING-ONLY HTTP end-to-end test for the DB modular redesign.

Drives the real FastAPI app via TestClient (OUTSIDE pytest, so conftest's hermetic
DB mock never loads) against the seeded staging DB. Creates a namespaced e2e-<RUNID>
fixture, exercises every endpoint the redesign touched over real HTTP + auth, then
tears the fixture down. The per-domain journeys live in db/e2e_checks/<domain>.py and
each expose `run()`; they are discovered + called in order by main().

Run (from backend/, staging env):
    dotenv -f .env.staging run -- python -m db.e2e_staging_http
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import importlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

from config import SESSION_SECRET
from db.connection import table
from services.encryption import encrypt_if_present
from main import app

RUNID = "e2etest"
SCHOOL_ID = f"e2e-school-{RUNID}"
COURSE_ID = f"e2e-course-{RUNID}"
OFFERING_ID = f"e2e-off-{RUNID}"
USER_ID = f"e2e-user-{RUNID}"

# Journeys run in THIS order (later ones read what earlier ones write).
JOURNEYS = ["academics", "graph", "gradebook", "identity", "study_social_ops", "quiz"]

client = TestClient(app)   # carries the e2e session cookie (set in setup_fixture)
anon = TestClient(app)     # no cookie — for 401 assertions

_results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    """Record + print a PASS/FAIL line. Journeys call this for every assertion."""
    _results.append((name, bool(ok)))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -> {detail}" if detail else ""))


def mint_session(user_id: str, ttl: int = 3600) -> str:
    """Mint a session token exactly as services/auth_guard._decode_session verifies:
    `<payload_b64>.<sig_b64>`, payload {user_id, exp}, HMAC-SHA256 over payload_b64."""
    payload = {"user_id": user_id, "exp": int(time.time()) + ttl}
    pb = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(SESSION_SECRET.encode(), pb.encode(), hashlib.sha256).digest()
    sb = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{pb}.{sb}"


def current_term_id() -> str | None:
    from services.academics import current_term
    t = current_term()
    return t["id"] if t else None


def setup_fixture() -> None:
    """Create the namespaced e2e fixture (idempotent upsert on the real PKs) and
    attach the minted session cookie to `client`."""
    table("schools").upsert(
        {"id": SCHOOL_ID, "name": "E2E School", "slug": f"e2e-{RUNID}"}, on_conflict="id")
    table("courses").upsert(
        {"id": COURSE_ID, "school_id": SCHOOL_ID, "course_code": f"E2E{RUNID}",
         "course_name": "E2E Course", "credits": 3}, on_conflict="id")
    tid = current_term_id()
    if not tid:
        raise SystemExit("no current term seeded on staging — run db.migrate first")
    table("course_offerings").upsert(
        {"id": OFFERING_ID, "course_id": COURSE_ID, "term_id": tid, "section": ""},
        on_conflict="id")
    table("users").upsert(
        {"id": USER_ID, "email": encrypt_if_present(f"{USER_ID}@e2e.local"),
         "onboarding_completed": True, "streak_count": 0, "is_approved": True},
        on_conflict="id")
    table("user_profiles").upsert(
        {"user_id": USER_ID, "name": encrypt_if_present("E2E User"),
         "first_name": encrypt_if_present("E2E"), "last_name": encrypt_if_present("User")},
        on_conflict="user_id")
    client.cookies.set("sapling_session", mint_session(USER_ID))


def teardown_fixture() -> None:
    """Delete the fixture in dependency order. Some FKs to users are NOT ON DELETE
    CASCADE — notably enrollments (inherited `user_courses_user_id_fkey` from 0001) —
    so we delete dependents explicitly before the user, then the offering/course/school.
    Each delete is tolerant (table absent / no rows is fine)."""
    node_id = f"e2e-node-{RUNID}"
    deletes = (
        ("enrollments", {"user_id": f"eq.{USER_ID}"}),          # cascades gradebook categories/assignments
        ("quiz_context", {"concept_node_id": f"eq.{node_id}"}),
        ("quiz_attempts", {"user_id": f"eq.{USER_ID}"}),
        ("node_mastery_events", {"node_id": f"eq.{node_id}"}),
        ("graph_edges", {"user_id": f"eq.{USER_ID}"}),
        ("graph_nodes", {"user_id": f"eq.{USER_ID}"}),
        ("sessions", {"user_id": f"eq.{USER_ID}"}),
        ("notes", {"user_id": f"eq.{USER_ID}"}),
        ("documents", {"user_id": f"eq.{USER_ID}"}),
        ("feedback", {"user_id": f"eq.{USER_ID}"}),
        ("user_profiles", {"user_id": f"eq.{USER_ID}"}),
        ("users", {"id": f"eq.{USER_ID}"}),
        ("course_offerings", {"id": f"eq.{OFFERING_ID}"}),
        ("courses", {"id": f"eq.{COURSE_ID}"}),
        ("schools", {"id": f"eq.{SCHOOL_ID}"}),
    )
    for tbl, flt in deletes:
        try:
            table(tbl).delete(flt)
        except Exception:
            pass


def check_auth() -> None:
    r = anon.get("/api/users")
    check("GET /api/users (no cookie) -> 401", r.status_code == 401, f"got {r.status_code}")
    r = client.get("/api/users")
    check("GET /api/users (session) -> 200", r.status_code == 200, f"got {r.status_code}")


def main() -> int:
    print("\n== e2e_staging_http ==")
    setup_fixture()
    try:
        check_auth()
        for name in JOURNEYS:
            try:
                mod = importlib.import_module(f"db.e2e_checks.{name}")
            except ModuleNotFoundError:
                check(f"journey:{name}", False, "module not implemented yet")
                continue
            try:
                mod.run()
            except Exception as e:  # one journey must not abort teardown or the rest
                check(f"journey:{name} (uncaught)", False, f"{type(e).__name__}: {e}")
    finally:
        teardown_fixture()
    passed = sum(1 for _, ok in _results if ok)
    print("\n" + "=" * 56)
    print(f"  E2E (staging HTTP): {passed}/{len(_results)} checks passed")
    print("=" * 56)
    return 0 if passed == len(_results) else 1


if __name__ == "__main__":
    # Re-enter through the package module so the journeys (which `import
    # db.e2e_staging_http`) share THIS module's client/_results/check — not a
    # second copy. Running `python -m` loads this file as `__main__`; without
    # this redirect the imported journeys would hit a cookie-less client.
    from db.e2e_staging_http import main as _main
    sys.exit(_main())
