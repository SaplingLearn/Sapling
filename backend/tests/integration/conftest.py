"""Fixtures for the opt-in integration suite (#362, #397) — real local Supabase.

Runs ONLY when RUN_INTEGRATION=1 and the local stack is up. Loads backend/.env
with override so the seed's ENCRYPTION_KEY / SESSION_SECRET / SUPABASE_* win over
the root conftest's hermetic test defaults (else decryption silently mismatches).

The defining constraint of this lane (#397): **writes go through the app; raw-SQL
assertions read back through a direct psycopg connection**, never through the same
`db.connection.table()` (PostgREST) layer that made the write — asserting through
the layer under test proves the echo, not the database. `db_conn` is that seam.

Safety (non-negotiable, #397): the autouse truncate runs over a direct Postgres
connection on SUPABASE_DB_URL, bypassing PostgREST entirely. That variable is
independent of SUPABASE_URL (which `_require_local_stack` checks) and .env.staging
/ .env.production both hold live direct-Postgres strings. `_require_local_db_url`
asserts SUPABASE_DB_URL is local and **raises loudly rather than skipping** before
any connection opens — a silent skip would read as "safe" while wiping real data.
"""
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest

_RUN = os.getenv("RUN_INTEGRATION") == "1"

# Must happen BEFORE any config/db/services import so the real key is in place.
if _RUN:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)


# Ids mirror db/seed_local_rich. Kept as literals so importing that module — and
# transitively `config` — stays deferred to fixture bodies, preserving the
# load_dotenv(override=True) ordering the header depends on.
USER_ACTIVE = "rich-user-active"
USER_SECOND = "rich-user-second"
COURSE_CS = "rich-course-cs101"


def _is_local() -> bool:
    url = (os.getenv("SUPABASE_URL") or "").strip()
    return "127.0.0.1" in url or "localhost" in url


# ── The direct-Postgres safety gate (#397) ─────────────────────────────────

_LOCAL_DB_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _db_url_is_local(url: str) -> bool:
    """True iff SUPABASE_DB_URL points at the local stack.

    Parses the host and requires an EXACT match against loopback names —
    deliberately stricter than a substring check, so a hostile or fat-fingered
    URL like ``postgresql://…@127.0.0.1.evil.com/…`` (which *contains* the string
    ``127.0.0.1``) is correctly rejected rather than treated as local.
    """
    if not url:
        return False
    try:
        host = (urlparse(url).hostname or "").strip().lower()
    except ValueError:
        return False
    return host in _LOCAL_DB_HOSTS


def _require_local_db_url(url: str) -> None:
    """Fail LOUDLY (raise, never skip) unless SUPABASE_DB_URL is local.

    This is the last line of defense before the truncate fixture opens a psycopg
    connection that bypasses PostgREST. `_require_local_stack` only inspects
    SUPABASE_URL — an independent variable — so the session gate can pass while
    SUPABASE_DB_URL still points at staging/production. A `skip` here would read
    as "safe" while a misconfigured var TRUNCATEs real customer data on every run.
    """
    if not _db_url_is_local(url):
        raise RuntimeError(
            "REFUSING to open the integration psycopg connection: SUPABASE_DB_URL "
            f"host is not local (got {url!r}). The truncate fixture bypasses "
            "PostgREST and would wipe whatever this points at. Point SUPABASE_DB_URL "
            "at the local stack (postgresql://postgres:postgres@127.0.0.1:54322/postgres) "
            "before running the integration lane."
        )


def mint_session(user_id: str, ttl: int = 3600) -> str:
    """Mint a sapling_session token via the canonical minter (#381).

    Thin wrapper, not a re-implementation: the import stays function-local so
    `config` is not imported at module scope, which would freeze SESSION_SECRET /
    ENCRYPTION_KEY before the `load_dotenv(override=True)` above has run.
    """
    from services.session_tokens import mint_session as _mint_session
    return _mint_session(user_id, ttl)


# ── Truncate isolation (#397) ──────────────────────────────────────────────
#
# Preserve the reference/catalog layer; truncate everything else and restore the
# rich baseline before each test, so tests are order-independent. The denylist
# holds (a) the migration ledger and (b) tables seeded by MIGRATIONS that
# `seed_local_rich` does not restore, plus the catalog hierarchy (schools /
# courses / course_offerings) which the seed re-upserts idempotently and which —
# verified against the schema — carry no FK to `users`, so no CASCADE from a
# truncated user table can ever reach them. Adding a new migration-seeded
# reference table means adding it here, or its rows vanish on the first reset.
_TRUNCATE_DENYLIST = frozenset({
    "schema_migrations",
    "terms", "roles", "achievements", "achievement_triggers", "cosmetics",
    "schools", "courses", "course_offerings",
})


def _public_tables(conn) -> list[str]:
    rows = conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    ).fetchall()
    return [r["tablename"] for r in rows]


def _truncate_mutable(conn) -> None:
    targets = [t for t in _public_tables(conn) if t not in _TRUNCATE_DENYLIST]
    if not targets:
        return
    idents = ", ".join(f'"{t}"' for t in targets)
    # One statement so mutual FKs among the targets truncate together; CASCADE
    # only ever reaches children of the targets, all of which are themselves
    # targets (the denylist is catalog-parents-only, checked above).
    conn.execute(f"TRUNCATE {idents} RESTART IDENTITY CASCADE")


def _reseed_baseline() -> None:
    from db import seed_local_rich
    seed_local_rich.main()


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="session", autouse=True)
def _require_local_stack():
    if not _RUN:
        pytest.skip("integration suite: set RUN_INTEGRATION=1 (with the local stack up)")
    if not _is_local():
        pytest.skip(f"integration suite: SUPABASE_URL is not local ({os.getenv('SUPABASE_URL')!r})")
    # Ensure the rich dataset is present (idempotent, additive).
    _reseed_baseline()
    yield


@pytest.fixture(scope="session")
def db_conn():
    """Session-scoped raw psycopg connection on SUPABASE_DB_URL — the raw-SQL
    assertion seam (#397). autocommit so each read sees the app's just-committed
    PostgREST writes; dict rows so assertions read columns by name. Refuses to
    open against a non-local SUPABASE_DB_URL (raises, never skips)."""
    import psycopg
    from psycopg.rows import dict_row

    url = (os.getenv("SUPABASE_DB_URL") or "").strip()
    _require_local_db_url(url)
    conn = psycopg.connect(url, autocommit=True, row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _reset_between_tests(db_conn):
    """Truncate all mutable tables and restore the rich baseline BEFORE each test,
    so a prior test's writes (or a crash) cannot leak forward — making the suite
    pass under `-p no:randomly` and in reversed/shuffled order alike (#397)."""
    _truncate_mutable(db_conn)
    _reseed_baseline()
    yield


@pytest.fixture
def seeded_user():
    """Factory minting distinct, approved users on demand (#397). Each call
    returns a fresh unique id; the autouse reset removes them between tests, so
    no manual cleanup is needed. Ownership/IDOR negatives need real second rows —
    this is how tests get them beyond the two baseline users."""
    import uuid

    from db.connection import table
    from services.encryption import encrypt_if_present

    def _make(*, approved: bool = True, onboarding_completed: bool = True,
              name: str = "Seeded User") -> str:
        uid = f"it-user-{uuid.uuid4().hex[:12]}"
        table("users").insert({
            "id": uid,
            "email": encrypt_if_present(f"{uid}@integration.test"),
            "is_approved": approved,
            "onboarding_completed": onboarding_completed,
            "auth_provider": "google",
        })
        table("user_profiles").insert({
            "user_id": uid,
            "name": encrypt_if_present(name),
        })
        return uid

    return _make


def _client_for(user_id: str):
    from fastapi.testclient import TestClient

    from main import app
    c = TestClient(app)
    c.cookies.set("sapling_session", mint_session(user_id))
    return c


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from main import app
    return TestClient(app)


@pytest.fixture
def anon_client():
    from fastapi.testclient import TestClient

    from main import app
    return TestClient(app)


@pytest.fixture
def authed_client():
    """A TestClient authenticated as the primary baseline user (rich-user-active).
    Absorbs the per-test `cookies.set(..., mint_session(...))` boilerplate."""
    return _client_for(USER_ACTIVE)


@pytest.fixture
def other_user_client():
    """A TestClient authenticated as a DIFFERENT baseline user (rich-user-second)
    — the counterparty for ownership/IDOR negatives against real rows (#397)."""
    return _client_for(USER_SECOND)
