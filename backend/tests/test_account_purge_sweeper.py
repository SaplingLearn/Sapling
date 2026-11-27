"""The daily purge job (services/account_purge_sweeper.py) and its claim SQL.

The claim function is pinned by its text here (the hermetic lane has no
Postgres); tests/integration must exercise it against a real database.
"""
import asyncio
import re
from pathlib import Path

import pytest

from services import account_purge, account_purge_sweeper as sw, events_service
from services.feature_flags import REGISTRY

MIGRATION = (Path(__file__).resolve().parents[1] / "db" / "migrations"
             / "20261114192918_account_purge.sql")


@pytest.fixture
def claims(monkeypatch):
    """A claim queue at the rpc seam, recording every call."""
    state = {"queue": [], "calls": []}

    def fake_rpc(name, params, **_):
        state["calls"].append((name, dict(params)))
        return [{"id": state["queue"].pop(0)}] if state["queue"] else []

    monkeypatch.setattr(sw, "rpc", fake_rpc)
    return state


@pytest.fixture
def purged(monkeypatch):
    done: list[str] = []
    monkeypatch.setattr(account_purge, "purge_account", lambda uid: done.append(uid) or {})
    return done


@pytest.fixture
def events(monkeypatch):
    logged = []
    monkeypatch.setattr(events_service, "log_event", lambda t, **kw: logged.append((t, kw)))
    return logged


def test_the_flag_is_registered_off_first_and_server_only():
    fd = REGISTRY["account_purge"]
    assert fd.variants[0] == "off" and fd.client_visible is False


def test_flag_off_is_a_no_op(monkeypatch, claims, purged):
    monkeypatch.setenv("SAPLING_FLAG_ACCOUNT_PURGE", "off")
    claims["queue"] = ["user_a"]

    assert sw.purge_once() == 0
    assert claims["calls"] == [] and purged == []


def test_flag_on_claims_and_purges_until_the_queue_is_empty(monkeypatch, claims, purged):
    monkeypatch.setenv("SAPLING_FLAG_ACCOUNT_PURGE", "on")
    claims["queue"] = ["user_a", "user_b"]

    assert sw.purge_once() == 2
    assert purged == ["user_a", "user_b"]
    # One account per claim; the grace the job asks for is the policy's.
    assert len(claims["calls"]) == 3
    name, params = claims["calls"][0]
    assert name == "claim_accounts_for_purge"
    assert params == {"grace_days": 30, "lease_seconds": sw.LEASE_SECONDS, "batch_size": 1}


def test_a_failed_purge_is_recorded_and_the_pass_goes_on(monkeypatch, claims, events):
    monkeypatch.setenv("SAPLING_FLAG_ACCOUNT_PURGE", "on")
    claims["queue"] = ["user_bad", "user_ok"]
    done = []

    def purge(uid):
        if uid == "user_bad":
            raise account_purge.AccountPurgeIncomplete("storage down")
        done.append(uid)

    monkeypatch.setattr(account_purge, "purge_account", purge)

    assert sw.purge_once() == 1
    assert done == ["user_ok"]
    ((event_type, kw),) = events
    assert event_type == "account.purge" and kw.get("user_id") is None
    assert kw["payload"] == {"outcome": "incomplete", "error": "AccountPurgeIncomplete"}


def test_a_claim_failure_ends_the_pass_without_raising(monkeypatch, purged):
    monkeypatch.setenv("SAPLING_FLAG_ACCOUNT_PURGE", "on")

    def down(*a, **k):
        raise RuntimeError("PGRST202 (migration not applied)")

    monkeypatch.setattr(sw, "rpc", down)
    assert sw.purge_once() == 0 and purged == []


def test_a_stop_request_ends_the_pass_before_the_next_claim(monkeypatch, claims, purged):
    import threading

    monkeypatch.setenv("SAPLING_FLAG_ACCOUNT_PURGE", "on")
    claims["queue"] = ["user_a"]
    stop = threading.Event()
    stop.set()

    assert sw.purge_once(stop) == 0 and claims["calls"] == []


# ── leftover credentials (any soft-deleted account, no grace) ───────────────


@pytest.fixture
def leftovers(monkeypatch):
    """The credential seams: who still holds credentials, and what was removed.
    The `credential_sweep` flag is on (as seeded)."""
    from services import account_credentials as ac

    monkeypatch.setenv("SAPLING_FLAG_CREDENTIAL_SWEEP", "on")
    state = {"owners": [], "removed": [], "revoked": [], "fail": set()}

    def remove(uid):
        if uid in state["fail"]:
            raise RuntimeError("db down")
        state["removed"].append(uid)
        return [f"tok-{uid}"]

    monkeypatch.setattr(ac, "deleted_accounts_with_credentials", lambda: list(state["owners"]))
    monkeypatch.setattr(ac, "remove_credentials", remove)
    monkeypatch.setattr(ac, "revoke_google_tokens", lambda t: state["revoked"].append(t))
    return state


def test_the_pass_removes_any_deleted_accounts_leftover_credentials(leftovers):
    leftovers["owners"] = ["user_a", "user_b"]

    assert sw.sweep_leftover_credentials() == 2
    assert leftovers["removed"] == ["user_a", "user_b"]
    assert leftovers["revoked"] == [["tok-user_a"], ["tok-user_b"]]


def test_the_credential_sweep_flag_is_registered_off_first_and_seeded_on():
    fd = REGISTRY["credential_sweep"]
    assert fd.variants == ("off", "on") and fd.client_visible is False
    migrations = Path(__file__).resolve().parents[1] / "db" / "migrations"
    seeded = [p for p in migrations.glob("*_credential_sweep_flag.sql")
              if "('credential_sweep', 'on')" in p.read_text(encoding="utf-8")]
    assert len(seeded) == 1


def test_the_kill_switch_stops_the_credential_sweep(monkeypatch, leftovers, leases):
    """SAPLING_FLAG_CREDENTIAL_SWEEP=off: nothing is read, deleted or
    revoked, and no lease is taken; the purge itself is unaffected."""
    monkeypatch.setenv("SAPLING_FLAG_CREDENTIAL_SWEEP", "off")
    monkeypatch.setenv("SAPLING_FLAG_STATELESS_LOCKS", "on")
    leftovers["owners"] = ["user_a"]
    scanned = []
    from services import account_credentials as ac

    monkeypatch.setattr(ac, "deleted_accounts_with_credentials", lambda: scanned.append(1) or ["user_a"])

    assert sw.sweep_leftover_credentials() == 0
    assert scanned == [] and leftovers["removed"] == [] and leftovers["revoked"] == []
    assert leases.calls == []


def test_the_credential_sweep_runs_with_its_flag_on(monkeypatch, leftovers):
    monkeypatch.setenv("SAPLING_FLAG_CREDENTIAL_SWEEP", "on")
    leftovers["owners"] = ["user_a"]
    assert sw.sweep_leftover_credentials() == 1
    assert leftovers["removed"] == ["user_a"]


def test_an_unreadable_credential_sweep_flag_skips_the_sweep(monkeypatch, leftovers):
    def broken(key, user_id):
        raise RuntimeError("flag store down")

    monkeypatch.setattr(sw, "flag_on", broken)
    leftovers["owners"] = ["user_a"]
    assert sw.sweep_leftover_credentials() == 0
    assert leftovers["removed"] == []


def test_a_failed_leftover_removal_is_logged_with_the_user_and_the_pass_goes_on(leftovers, caplog):
    leftovers["owners"] = ["user_bad", "user_ok"]
    leftovers["fail"] = {"user_bad"}

    with caplog.at_level("ERROR", logger=sw.__name__):
        assert sw.sweep_leftover_credentials() == 1

    assert leftovers["removed"] == ["user_ok"]
    assert any("user_bad" in r.getMessage() for r in caplog.records if r.levelname == "ERROR")


def test_a_failed_leftover_scan_never_raises(monkeypatch):
    from services import account_credentials as ac

    def down():
        raise RuntimeError("db down")

    monkeypatch.setattr(ac, "deleted_accounts_with_credentials", down)
    assert sw.sweep_leftover_credentials() == 0


def test_every_pass_sweeps_credentials_even_with_the_purge_flag_off(monkeypatch, claims, purged, leftovers):
    # The flag gates the 30-day hard delete. The credentials were due at the
    # delete itself (owner decision), so finishing that is not gated by it.
    monkeypatch.setenv("SAPLING_FLAG_ACCOUNT_PURGE", "off")
    leftovers["owners"] = ["user_a"]

    sw.run_pass()

    assert leftovers["removed"] == ["user_a"]
    assert claims["calls"] == [] and purged == []


def test_a_stop_request_ends_the_credential_sweep_between_accounts(monkeypatch, leftovers):
    """Shutdown sets the stop event; the sweep stops at the next account
    instead of working through the whole list."""
    import threading

    from services import account_credentials as ac

    stop = threading.Event()
    leftovers["owners"] = ["user_a", "user_b", "user_c"]

    def revoke(tokens):
        leftovers["revoked"].append(tokens)
        stop.set()  # shutdown arrives while user_a is being cleaned

    monkeypatch.setattr(ac, "revoke_google_tokens", revoke)
    assert sw.sweep_leftover_credentials(stop) == 1
    assert leftovers["removed"] == ["user_a"]


def test_a_pass_that_starts_stopped_sweeps_nothing(monkeypatch, claims, purged, leftovers):
    import threading

    stop = threading.Event()
    stop.set()
    leftovers["owners"] = ["user_a"]
    sw.run_pass(stop)
    assert leftovers["removed"] == [] and claims["calls"] == []


# ── one replica sweeps per pass (services/pg_lease.py, stateless_locks) ─────


@pytest.fixture
def leases(monkeypatch):
    """claim_lease/renew_lease/release_lease at db.connection.rpc (pg_lease's seam)."""
    import db.connection as dbconn
    from services import pg_lease
    from tests.test_pg_lease import FakeLeases

    pg_lease.reset_db_state()
    fake = FakeLeases()
    monkeypatch.setattr(dbconn, "rpc", fake.rpc)
    yield fake
    pg_lease.reset_db_state()


def test_the_sweep_is_skipped_while_another_replica_holds_its_lease(monkeypatch, leases, leftovers):
    monkeypatch.setenv("SAPLING_FLAG_STATELESS_LOCKS", "on")
    leftovers["owners"] = ["user_a"]
    leases.rows[sw.CREDENTIAL_SWEEP_LEASE_KEY] = ("other-replica", float("inf"))

    assert sw.sweep_leftover_credentials() == 0
    assert leftovers["removed"] == []


def test_the_sweep_holds_the_lease_while_it_runs_and_lets_it_go(monkeypatch, leases, leftovers):
    monkeypatch.setenv("SAPLING_FLAG_STATELESS_LOCKS", "on")
    from services import account_credentials as ac

    leftovers["owners"] = ["user_a"]
    held_during: list[bool] = []
    real_remove = ac.remove_credentials

    def remove(uid):
        held_during.append(sw.CREDENTIAL_SWEEP_LEASE_KEY in leases.rows)
        return real_remove(uid)

    monkeypatch.setattr(ac, "remove_credentials", remove)
    assert sw.sweep_leftover_credentials() == 1
    assert held_during == [True]
    assert sw.CREDENTIAL_SWEEP_LEASE_KEY not in leases.rows  # released on exit
    claim = next(c for c in leases.calls if c[0] == "claim_lease")
    assert claim[1]["p_key"] == sw.CREDENTIAL_SWEEP_LEASE_KEY


def test_with_stateless_locks_off_every_replica_sweeps_and_no_lease_is_read(monkeypatch, leases, leftovers):
    monkeypatch.delenv("SAPLING_FLAG_STATELESS_LOCKS", raising=False)
    leftovers["owners"] = ["user_a"]
    assert sw.sweep_leftover_credentials() == 1
    assert leases.calls == []


def test_an_unavailable_lease_store_still_sweeps(monkeypatch, leases, leftovers):
    # Fail open, like every pg_lease caller: the sweep is idempotent, so a
    # second replica sweeping is wasted work, never harm.
    monkeypatch.setenv("SAPLING_FLAG_STATELESS_LOCKS", "on")
    leases.error = RuntimeError("db down")
    leftovers["owners"] = ["user_a"]
    assert sw.sweep_leftover_credentials() == 1


def test_never_started_under_pytest():
    assert sw.sweeper_enabled() is False
    asyncio.run(_start_and_stop())


async def _start_and_stop():
    sw.start_purge_sweeper()
    assert sw._task is None
    await sw.stop_purge_sweeper()


# ── the claim SQL ───────────────────────────────────────────────────────────


def _claim_sql() -> str:
    sql = re.sub(r"--[^\n]*", "", MIGRATION.read_text(encoding="utf-8"))
    return re.sub(r"\s+", " ", sql)


def test_the_claim_only_takes_accounts_deleted_more_than_30_days_ago_and_not_purged():
    sql = _claim_sql()
    assert "c.deleted_at IS NOT NULL" in sql and "c.purged_at IS NULL" in sql
    # The grace is floored in SQL: no caller value purges earlier than 30 days.
    assert "c.deleted_at < now() - make_interval(days => GREATEST(grace_days, 30))" in sql


def test_the_claim_is_safe_on_several_workers():
    sql = _claim_sql()
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "SET purge_claimed_at = now()" in sql
    assert ("c.purge_claimed_at IS NULL OR c.purge_claimed_at < now() - "
            "make_interval(secs => GREATEST(lease_seconds, 60))") in sql


def test_the_claim_is_executable_by_service_role_only():
    sql = _claim_sql()
    assert "REVOKE ALL ON FUNCTION public.claim_accounts_for_purge(INT, INT, INT) FROM PUBLIC" in sql
    assert "ARRAY['anon', 'authenticated']" in sql
    assert "GRANT EXECUTE ON FUNCTION public.claim_accounts_for_purge(INT, INT, INT) TO service_role" in sql
    assert "SECURITY INVOKER" in sql and "SET search_path = ''" in sql


def test_the_rls_lockdown_lane_knows_the_rpc():
    lockdown = (Path(__file__).resolve().parent / "integration" / "test_rls_lockdown_db.py").read_text(encoding="utf-8")
    assert '"claim_accounts_for_purge"' in lockdown
