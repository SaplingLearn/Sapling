"""services/local_seed_watcher.py + GET /api/auth/local-seed (#715).

On a developer's local stack, a Google account that signs in gets the rich
sample dataset copied onto it automatically — the same owner seed
`python -m db.seed_local_rich --owner-user-id` runs by hand. Fixture accounts
(rich-*/seed-*/it-*) are never touched, and nothing here exists outside local.
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import db.seed_local_rich as rich
from db import seed_helpers as h, seed_local_owner as owner_seed
from services import local_seed_watcher as watcher
from services import profiles
from services.encryption import encrypt
from tests.seed_memory_db import MemoryDatabase

GOOGLE = "user_1001"
GOOGLE_2 = "user_1002"


@pytest.fixture(autouse=True)
def _fresh_watcher_state():
    watcher._reset()
    yield
    watcher._reset()


@pytest.fixture
def local_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("SUPABASE_URL", "http://127.0.0.1:54321")


@pytest.fixture
def db(local_env, monkeypatch):
    database = MemoryDatabase()
    for module in (rich, h, owner_seed, profiles, watcher):
        monkeypatch.setattr(module, "table", database.table)
    database.rows["roles"] = [{"id": "11111111-2222-4333-8444-555555555555", "slug": "admin"}]
    database.rows["users"] = [
        {"id": GOOGLE, "email": encrypt("me@bu.edu"), "onboarding_completed": False,
         "is_approved": True, "created_at": "2026-10-18T00:00:00+00:00"},
        # Fixture accounts: the rich seed's, the staging seed's, the integration lane's.
        {"id": "rich-user-new", "onboarding_completed": False, "created_at": "2026-10-18T00:00:00+00:00"},
        {"id": "seed-user-1", "onboarding_completed": False, "created_at": "2026-10-18T00:00:00+00:00"},
        {"id": "it-user-71476fdfa7d5", "onboarding_completed": False, "created_at": "2026-10-18T00:00:00+00:00"},
        # SQL LIKE's `_` matches any character; the prefix check must not.
        {"id": "users-lookalike", "onboarding_completed": False, "created_at": "2026-10-18T00:00:00+00:00"},
    ]
    database.rows["user_profiles"] = [{"user_id": GOOGLE, "name": encrypt("Real Me")}]
    return database


@pytest.fixture
def seeds(monkeypatch):
    """Record which accounts the watcher seeds, without running the seed."""
    seen = []

    def fake_seed_owner(owner, *, report=True):
        assert report is False, "the watcher logs; it never prints the CLI summary"
        seen.append(owner["id"])
        return 1

    monkeypatch.setattr(rich, "seed_owner", fake_seed_owner)
    return seen


def _enrolled(database, user_id):
    return [row for row in database.rows["enrollments"] if row["user_id"] == user_id]


# ── the predicate ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("env,url,expected", [
    ("local", "http://127.0.0.1:54321", True),
    ("test", "http://localhost:54321", True),
    ("production", "http://127.0.0.1:54321", False),
    ("staging", "http://127.0.0.1:54321", False),
    ("local", "https://abc.supabase.co", False),
    ("local", "https://127.0.0.1.evil.example", False),
    ("local", "", False),
])
def test_the_watcher_uses_the_seed_guards_predicate(monkeypatch, env, url, expected):
    monkeypatch.setenv("APP_ENV", env)
    monkeypatch.setenv("SUPABASE_URL", url)
    assert h.is_local_backend() is expected
    assert watcher.watcher_enabled() is expected


# ── one pass ────────────────────────────────────────────────────────────────


def test_a_new_google_account_gets_the_sample_dataset(db):
    assert watcher.scan_once() == 1
    assert len(_enrolled(db, GOOGLE)) == 5
    assert db.rows["users"][0]["onboarding_completed"] is True
    assert watcher.status_for(GOOGLE) == {"state": "ready"}


def test_fixture_accounts_are_never_touched(db, seeds):
    db.rows["users"] = [u for u in db.rows["users"] if u["id"] != GOOGLE]
    assert watcher.scan_once() == 0
    assert seeds == []


def test_fixture_accounts_keep_their_rows_when_a_google_account_is_seeded(db):
    watcher.scan_once()
    for fixture in ("rich-user-new", "seed-user-1", "it-user-71476fdfa7d5", "users-lookalike"):
        assert _enrolled(db, fixture) == []
        assert next(u for u in db.rows["users"] if u["id"] == fixture)["onboarding_completed"] is False


def test_an_already_seeded_account_is_left_alone_after_a_restart(db, monkeypatch):
    watcher.scan_once()
    watcher._reset()  # a backend restart forgets everything in-process
    db.writes.clear()
    calls = []
    real = rich.seed_owner
    monkeypatch.setattr(rich, "seed_owner", lambda owner, **kw: calls.append(owner) or real(owner, **kw))

    assert watcher.scan_once() == 0
    assert calls == []
    assert db.writes == []
    assert watcher.status_for(GOOGLE) == {"state": "ready"}


def test_an_account_onboarded_by_hand_still_gets_the_sample_data(db, seeds):
    """Existing unseeded accounts are seeded the first time the watcher sees them."""
    db.rows["users"][0]["onboarding_completed"] = True
    assert watcher.scan_once() == 1
    assert seeds == [GOOGLE]


def test_a_seed_interrupted_before_onboarding_completed_is_finished(db, monkeypatch):
    """The marker enrollment is written early; only onboarding_completed, set
    after the whole seed succeeded, makes the account count as seeded."""
    original = owner_seed.OwnerSeedWriter.insert_if_absent
    state = {"failed": False}

    def interrupt_once(writer, name, row_id, row):
        if name == "documents" and not state["failed"]:
            state["failed"] = True
            raise RuntimeError("interrupted")
        return original(writer, name, row_id, row)

    monkeypatch.setattr(owner_seed.OwnerSeedWriter, "insert_if_absent", interrupt_once)
    watcher.scan_once()
    assert watcher.status_for(GOOGLE)["state"] == "failed"
    watcher._reset()  # a restart, so no backoff stands in the way

    assert watcher.scan_once() == 1
    assert len(db.rows["documents"]) == 3
    assert db.rows["users"][0]["onboarding_completed"] is True


def test_an_account_deleted_and_recreated_is_seeded_again(db, seeds):
    """users.id is user_<google id>, so re-signing in after deleting the account
    reuses the id; created_at is what tells the two accounts apart."""
    watcher.scan_once()
    db.rows["users"][0]["created_at"] = "2026-10-19T00:00:00+00:00"
    assert watcher.scan_once() == 1
    assert seeds == [GOOGLE, GOOGLE]


def test_a_seeded_account_is_not_reseeded_within_a_process(db, seeds):
    """Even when the marker never appears (a pre-existing enrollment in the
    sample offering keeps its own id), one process seeds an account once."""
    assert watcher.scan_once() == 1
    assert watcher.scan_once() == 0
    assert seeds == [GOOGLE]


def test_one_failing_account_does_not_stop_the_others(db, monkeypatch):
    db.rows["users"].append({"id": GOOGLE_2, "onboarding_completed": False,
                             "created_at": "2026-10-18T00:00:00+00:00"})
    seen = []

    def half_broken(owner, *, report=True):
        seen.append(owner["id"])
        if owner["id"] == GOOGLE:
            raise RuntimeError("boom")
        return 1

    monkeypatch.setattr(rich, "seed_owner", half_broken)
    assert watcher.scan_once() == 1
    assert sorted(seen) == [GOOGLE, GOOGLE_2]
    assert watcher.status_for(GOOGLE) == {"state": "failed", "error": "RuntimeError: boom"}
    assert watcher.status_for(GOOGLE_2) == {"state": "ready"}


def test_a_failing_account_backs_off_instead_of_hot_looping(db, monkeypatch):
    attempts = []

    def broken(owner, *, report=True):
        attempts.append(owner["id"])
        raise RuntimeError("still broken")

    monkeypatch.setattr(rich, "seed_owner", broken)
    watcher.scan_once(now=0)
    watcher.scan_once(now=1)
    watcher.scan_once(now=watcher.BACKOFF_BASE_SECONDS - 1)
    assert attempts == [GOOGLE]

    watcher.scan_once(now=watcher.BACKOFF_BASE_SECONDS)
    assert attempts == [GOOGLE, GOOGLE]
    # The second failure doubles the wait.
    watcher.scan_once(now=watcher.BACKOFF_BASE_SECONDS * 2.5)
    assert len(attempts) == 2
    watcher.scan_once(now=watcher.BACKOFF_BASE_SECONDS * 3)
    assert len(attempts) == 3


def test_the_backoff_is_capped(db, monkeypatch):
    monkeypatch.setattr(rich, "seed_owner", lambda owner, **kw: (_ for _ in ()).throw(RuntimeError("x")))
    now = 0.0
    for _ in range(20):
        watcher.scan_once(now=now)
        now += watcher.BACKOFF_MAX_SECONDS
    assert watcher._failures[GOOGLE].attempts == 20


def test_a_failure_that_then_succeeds_reports_ready(db, monkeypatch):
    calls = []
    real = rich.seed_owner

    def flaky(owner, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("transient")
        return real(owner, **kw)

    monkeypatch.setattr(rich, "seed_owner", flaky)
    watcher.scan_once(now=0)
    watcher.scan_once(now=watcher.BACKOFF_BASE_SECONDS)
    assert watcher.status_for(GOOGLE) == {"state": "ready"}


def test_a_failed_listing_is_a_quiet_zero(local_env, monkeypatch, seeds):
    def broken_table(_name):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(watcher, "table", broken_table)
    assert watcher.scan_once() == 0
    assert seeds == []


def test_scans_never_overlap(db, seeds):
    """h.counts is process-global and the seed is not built for two writers."""
    assert watcher._scan_lock.acquire(blocking=False)
    try:
        assert watcher.scan_once() == 0
    finally:
        watcher._scan_lock.release()
    assert seeds == []
    assert watcher.scan_once() == 1


def test_it_is_inert_outside_local(db, monkeypatch, seeds):
    monkeypatch.setenv("APP_ENV", "production")

    def unexpected(_name):
        pytest.fail("a non-local backend must not read accounts")

    monkeypatch.setattr(watcher, "table", unexpected)
    assert watcher.scan_once() == 0
    assert seeds == []


# ── lifecycle ───────────────────────────────────────────────────────────────


def test_start_and_stop(local_env, monkeypatch):
    monkeypatch.setattr(watcher, "scan_once", lambda: 0)

    async def scenario():
        watcher.start_watcher()
        task = watcher._task
        assert task is not None and not task.done()
        await watcher.stop_watcher()
        assert task.cancelled() or task.done()
        assert watcher._task is None

    asyncio.run(scenario())


@pytest.mark.parametrize("env,url", [
    ("production", "http://127.0.0.1:54321"),
    ("local", "https://abc.supabase.co"),
])
def test_not_started_outside_local(monkeypatch, env, url):
    monkeypatch.setenv("APP_ENV", env)
    monkeypatch.setenv("SUPABASE_URL", url)

    async def scenario():
        watcher.start_watcher()
        assert watcher._task is None
        await watcher.stop_watcher()  # stopping nothing is safe

    asyncio.run(scenario())


def test_a_nudge_wakes_the_loop_before_the_interval(local_env, monkeypatch):
    calls = []
    monkeypatch.setattr(watcher, "scan_once", lambda: calls.append(1) or 0)
    monkeypatch.setattr(watcher, "WATCH_INTERVAL_SECONDS", 3600)

    async def scenario():
        watcher.start_watcher()
        await asyncio.sleep(0.05)
        assert calls == []
        watcher.nudge()
        for _ in range(200):
            if calls:
                break
            await asyncio.sleep(0.01)
        await watcher.stop_watcher()

    asyncio.run(scenario())
    assert calls == [1]


def test_the_loop_survives_a_scan_that_raises(local_env, monkeypatch):
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("transient")
        return 0

    monkeypatch.setattr(watcher, "scan_once", flaky)
    monkeypatch.setattr(watcher, "WATCH_INTERVAL_SECONDS", 0)

    async def scenario():
        watcher.start_watcher()
        for _ in range(200):
            if len(calls) >= 2:
                break
            await asyncio.sleep(0.01)
        await watcher.stop_watcher()

    asyncio.run(scenario())
    assert len(calls) >= 2


def test_the_app_lifespan_starts_and_stops_the_watcher():
    with (
        patch("main.start_local_seed_watcher") as start,
        patch("main.stop_local_seed_watcher", new=AsyncMock()) as stop,
        patch("main.start_sweeper"),
        patch("main.stop_sweeper", new=AsyncMock()),
        patch("main.ensure_bucket_exists", new=AsyncMock()),
    ):
        from main import app

        with TestClient(app):
            start.assert_called_once()
            stop.assert_not_called()
        stop.assert_awaited_once()


# ── GET /api/auth/local-seed ────────────────────────────────────────────────


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


def _status(client, user_id=GOOGLE):
    # The conftest auth stub reads the session user off ?user_id=.
    return client.get(f"/api/auth/local-seed?user_id={user_id}")


@pytest.mark.parametrize("env,url", [
    ("production", "http://127.0.0.1:54321"),
    ("staging", "http://127.0.0.1:54321"),
    ("local", "https://abc.supabase.co"),
])
def test_status_is_404_outside_local(client, db, monkeypatch, env, url):
    monkeypatch.setenv("APP_ENV", env)
    monkeypatch.setenv("SUPABASE_URL", url)
    assert _status(client).status_code == 404


def test_status_is_404_for_a_fixture_account(client, db):
    """Not the watcher's to seed: the frontend keeps today's onboarding route."""
    assert _status(client, "rich-user-new").status_code == 404


def test_status_pending_nudges_the_watcher(client, db, monkeypatch):
    nudged = []
    monkeypatch.setattr(watcher, "nudge", lambda: nudged.append(1))
    resp = _status(client)
    assert resp.status_code == 200
    assert resp.json() == {"state": "pending"}
    assert nudged == [1]


def test_status_seeding(client, db, monkeypatch):
    watcher._seeding = GOOGLE
    assert _status(client).json() == {"state": "seeding"}


def test_status_ready_after_the_watcher_seeded(client, db):
    watcher.scan_once()
    assert _status(client).json() == {"state": "ready"}


def test_status_ready_for_an_account_seeded_by_an_earlier_process(client, db):
    rich.seed_owner(db.rows["users"][0], report=False)
    watcher._reset()
    assert _status(client).json() == {"state": "ready"}


def test_status_failed_carries_the_error(client, db, monkeypatch):
    def broken(owner, *, report=True):
        raise RuntimeError("seed exploded")

    monkeypatch.setattr(rich, "seed_owner", broken)
    watcher.scan_once()
    assert _status(client).json() == {"state": "failed", "error": "RuntimeError: seed exploded"}
