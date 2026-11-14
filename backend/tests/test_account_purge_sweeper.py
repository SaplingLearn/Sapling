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
    """The credential seams: who still holds credentials, and what was removed."""
    from services import account_credentials as ac

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


def test_never_started_under_pytest():
    assert sw.sweeper_enabled() is False
    asyncio.run(_start_and_stop())


async def _start_and_stop():
    sw.start_purge_sweeper()
    assert sw._task is None
    await sw.stop_purge_sweeper()


# ── the claim SQL ───────────────────────────────────────────────────────────


def _claim_sql() -> str:
    sql = re.sub(r"--[^\n]*", "", MIGRATION.read_text())
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
    lockdown = (Path(__file__).resolve().parent / "integration" / "test_rls_lockdown_db.py").read_text()
    assert '"claim_accounts_for_purge"' in lockdown
