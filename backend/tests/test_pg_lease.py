"""Cross-replica leases behind `stateless_locks` (#117 wave 3).

Hermetic: `claim_lease()` / `renew_lease()` / `release_lease()` are faked at the rpc seam by a
small stateful model of the SQL (the SQL itself is pinned against real
Postgres in tests/integration/test_app_leases_db.py). Pinned here:

* off (default): no DB call; every lease is granted (the caller's in-process
  lock is the whole guard, as before);
* on: one bounded rpc per claim, as service role; a held lease is released by
  the same holder on exit, renewed while the body runs; another holder's live
  lease yields False (after polling up to wait_s); a renewal never recreates
  a released lease, and exit waits for an in-flight renewal before releasing;
* a DB failure (or a pre-migration 404) grants the lease (fail open to the
  in-process layer), marks the store down for DB_DOWN_S, warns once per
  outage; the next answer re-arms the warning;
* consume_once never releases, and the callers (account ops, OAuth nonce,
  study-guide single-flight) use it the way their docstrings say: a raw nonce
  never reaches the DB.
"""
from __future__ import annotations

import logging
import time
from types import SimpleNamespace

import pytest

import db.connection as dbconn
from db import scope as db_scope
from services import pg_lease

FLAG_ENV = "SAPLING_FLAG_STATELESS_LOCKS"


class FakeLeases:
    """claim_lease / renew_lease / release_lease over a dict, recording each call."""

    def __init__(self):
        self.rows: dict[str, tuple[str, float]] = {}
        self.calls: list[tuple[str, dict, bool, float | None]] = []
        self.error: Exception | None = None
        self.answer_override = None
        self.on_renew = None  # called inside renew_lease (tests hold it open)

    def rpc(self, name, params, *, timeout=None):
        self.calls.append((name, dict(params), db_scope.in_service_scope(), timeout))
        if self.error:
            raise self.error
        if self.answer_override is not None:
            return self.answer_override
        now = time.monotonic()
        key = params["p_key"]
        if name == "claim_lease":
            cur = self.rows.get(key)
            if cur is None or cur[0] == params["p_holder"] or cur[1] <= now:
                self.rows[key] = (params["p_holder"], now + params["p_ttl_sec"])
                return True
            return False
        if name == "renew_lease":
            if self.on_renew:
                self.on_renew()
            cur = self.rows.get(key)
            if cur and cur[0] == params["p_holder"]:  # UPDATE only: never inserts
                self.rows[key] = (cur[0], time.monotonic() + params["p_ttl_sec"])
                self.calls.append(("renew_done", {}, True, None))
                return True
            self.calls.append(("renew_done", {}, True, None))
            return False
        if name == "release_lease":
            cur = self.rows.get(key)
            if cur and cur[0] == params["p_holder"]:
                del self.rows[key]
                return True
            return False
        raise AssertionError(name)

    def names(self):
        return [c[0] for c in self.calls]


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    pg_lease.reset_db_state()
    monkeypatch.delenv(FLAG_ENV, raising=False)
    yield
    pg_lease.reset_db_state()


@pytest.fixture
def fake(monkeypatch):
    f = FakeLeases()
    monkeypatch.setattr(dbconn, "rpc", f.rpc)
    return f


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv(FLAG_ENV, "on")


def _fake_clock(monkeypatch, on_sleep=None):
    """Replace pg_lease's view of `time` (never the global module)."""
    clock = {"now": 1000.0, "sleeps": []}

    def sleep(s):
        clock["sleeps"].append(s)
        clock["now"] += s
        if on_sleep:
            on_sleep(len(clock["sleeps"]))

    monkeypatch.setattr(pg_lease, "time", SimpleNamespace(
        monotonic=lambda: clock["now"], sleep=sleep))
    return clock


# ── flag off ────────────────────────────────────────────────────────────────


def test_off_grants_every_lease_and_touches_no_db(fake):
    with pg_lease.lease("k", 30) as a, pg_lease.lease("k", 30) as b:
        assert a is True and b is True
    assert pg_lease.consume_once("n", 60) is None
    assert fake.calls == []


# ── flag on ─────────────────────────────────────────────────────────────────


def test_on_claims_as_service_with_a_bounded_timeout_and_releases(fake, on):
    with pg_lease.lease("k", 30, renew=False) as held:
        assert held is True
        assert "k" in fake.rows
    assert "k" not in fake.rows
    (claim, cp, csvc, cto), (release, rp, rsvc, _rto) = fake.calls
    assert (claim, release) == ("claim_lease", "release_lease")
    assert cp["p_key"] == "k" and cp["p_ttl_sec"] == 30
    assert rp == {"p_key": "k", "p_holder": cp["p_holder"]}
    assert csvc and rsvc and cto == pg_lease.CLAIM_TIMEOUT_S


def test_a_live_lease_elsewhere_yields_false_and_is_not_released(fake, on):
    fake.rows["k"] = ("other", time.monotonic() + 60)
    with pg_lease.lease("k", 30) as held:
        assert held is False
    assert fake.rows["k"][0] == "other"
    assert fake.names() == ["claim_lease"]


def test_the_body_exception_still_releases(fake, on):
    with pytest.raises(RuntimeError):
        with pg_lease.lease("k", 30, renew=False):
            raise RuntimeError("boom")
    assert fake.rows == {}


def test_a_waiter_polls_until_the_holder_lets_go(fake, on, monkeypatch):
    fake.rows["k"] = ("other", time.monotonic() + 60)

    def _other_finishes(n):
        if n == 2:
            del fake.rows["k"]

    clock = _fake_clock(monkeypatch, _other_finishes)
    with pg_lease.lease("k", 30, wait_s=10, poll_s=0.5, renew=False) as held:
        assert held is True
    assert clock["sleeps"] == [0.5, 0.5]
    assert fake.names() == ["claim_lease"] * 3 + ["release_lease"]


def test_a_waiter_gives_up_after_wait_s(fake, on, monkeypatch):
    fake.rows["k"] = ("other", time.monotonic() + 60)
    _fake_clock(monkeypatch)
    with pg_lease.lease("k", 30, wait_s=2, poll_s=0.5, renew=False) as held:
        assert held is False
    assert fake.names() == ["claim_lease"] * 5  # t=0, .5, 1, 1.5, 2


def test_the_lease_is_renewed_while_the_body_runs(fake, on, monkeypatch):
    monkeypatch.setattr(pg_lease, "RENEW_MIN_S", 0.01)
    with pg_lease.lease("k", 0.03) as held:  # renews every ~0.01 s
        assert held is True
        deadline = time.monotonic() + 2
        while fake.names().count("renew_lease") < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
    claims = [c for c in fake.calls if c[0] in ("claim_lease", "renew_lease")]
    assert [c[0] for c in claims][:1] == ["claim_lease"] and len(claims) >= 3
    assert len({c[1]["p_holder"] for c in claims}) == 1  # the same acquisition
    assert fake.names()[-1] == "release_lease"


def test_a_renewal_never_recreates_a_released_lease(fake, on):
    """The renewal is UPDATE-only: one that lands after the release (or after
    another holder took an expired lease over) brings nothing back."""
    with pg_lease.lease("k", 30, renew=False):
        holder = fake.rows["k"][0]
    assert "k" not in fake.rows
    assert pg_lease._renew_db("k", holder, 30) is False
    assert "k" not in fake.rows
    fake.rows["k"] = ("other", time.monotonic() + 60)
    assert pg_lease._renew_db("k", holder, 30) is False
    assert fake.rows["k"][0] == "other"


def test_exit_waits_for_an_in_flight_renewal_before_releasing(fake, on, monkeypatch):
    """A renewal still running when the body ends used to race the release
    and could recreate the lease after it was deleted (an AccountBusy for up
    to the TTL). The exit now joins the renewer first: the release is last."""
    import threading

    monkeypatch.setattr(pg_lease, "RENEW_MIN_S", 0.01)
    in_renew, slow = threading.Event(), {"on": True}

    def _hold_renewal_open():
        if slow["on"]:
            slow["on"] = False
            in_renew.set()
            time.sleep(0.2)  # the body exits while this renewal is in flight

    fake.on_renew = _hold_renewal_open
    with pg_lease.lease("k", 0.03) as held:
        assert held is True
        assert in_renew.wait(2)
    names = fake.names()
    assert names.index("renew_done") < names.index("release_lease")
    assert names[-1] == "release_lease"
    assert "k" not in fake.rows


def test_ttl_is_clamped_to_what_the_sql_accepts(fake, on):
    pg_lease.consume_once("a", 0.2)
    pg_lease.consume_once("b", 10**9)
    assert [c[1]["p_ttl_sec"] for c in fake.calls] == [1, pg_lease.MAX_TTL_S]


# ── failure → in-process layer ──────────────────────────────────────────────


def test_a_db_failure_grants_and_skips_the_db_for_the_window(fake, on, caplog):
    fake.error = RuntimeError("PGRST202")
    with caplog.at_level(logging.WARNING, logger="sapling.pg_lease"):
        with pg_lease.lease("k", 30) as held:
            assert held is True
        with pg_lease.lease("k", 30) as again:
            assert again is True
        assert pg_lease.consume_once("n", 60) is None
    assert fake.names() == ["claim_lease"]  # down: no second attempt, no release
    warnings = [r for r in caplog.records if "stateless_locks" in r.getMessage()]
    assert len(warnings) == 1


def test_the_next_answer_rearms_the_warning(fake, on, caplog, monkeypatch):
    fake.error = RuntimeError("down")
    pg_lease.consume_once("a", 60)
    monkeypatch.setattr(pg_lease, "_db_down_until", 0.0)  # the window passed
    fake.error = None
    with caplog.at_level(logging.INFO, logger="sapling.pg_lease"):
        assert pg_lease.consume_once("b", 60) is True
    assert any("answers again" in r.getMessage() for r in caplog.records)
    fake.error = RuntimeError("down again")
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="sapling.pg_lease"):
        pg_lease.consume_once("c", 60)
    assert sum("failed" in r.getMessage() for r in caplog.records) == 1


@pytest.mark.parametrize("answer", [None, "yes", {"a": 1, "b": 2}, []])
def test_an_unexpected_answer_counts_as_a_failure(fake, on, answer):
    fake.answer_override = answer if answer is not None else {"x": None}
    assert pg_lease.consume_once("n", 60) is None
    assert pg_lease._db_down()


@pytest.mark.parametrize("answer,expected", [
    ([True], True), ([{"claim_lease": True}], True), ({"claim_lease": False}, False),
])
def test_row_shaped_answers_are_accepted(fake, on, answer, expected):
    fake.answer_override = answer
    assert pg_lease.consume_once("n", 60) is expected


# ── consume_once ────────────────────────────────────────────────────────────


def test_consume_once_is_first_wins_and_never_released(fake, on):
    assert pg_lease.consume_once("n", 60) is True
    assert pg_lease.consume_once("n", 60) is False
    assert "release_lease" not in fake.names()


def test_hashed_key_hides_its_parts():
    key = pg_lease.hashed_key("oauth_nonce", "s3cret-nonce")
    assert key.startswith("oauth_nonce:") and "s3cret" not in key
    assert key == pg_lease.hashed_key("oauth_nonce", "s3cret-nonce")
    assert key != pg_lease.hashed_key("oauth_nonce", "other")
    assert pg_lease.hashed_key("g", "a", "bc") != pg_lease.hashed_key("g", "ab", "c")


# ── the callers ─────────────────────────────────────────────────────────────


def test_account_op_is_refused_while_another_replica_holds_it(fake, on):
    from services import account_ops_lock as lk

    fake.rows["account_op:u1"] = ("other-replica", time.monotonic() + 60)
    with pytest.raises(lk.AccountBusy):
        with lk.account_op("u1"):
            pass
    assert not lk.is_busy("u1")  # the in-process slot went back
    with lk.account_op("u2"):
        assert fake.rows["account_op:u2"][0] != "other-replica"
    assert "account_op:u2" not in fake.rows


def test_account_op_fails_open_when_the_store_is_down(fake, on):
    from services import account_ops_lock as lk

    fake.error = RuntimeError("down")
    with lk.account_op("u1"):
        assert lk.is_busy("u1")
    assert not lk.is_busy("u1")


def test_oauth_nonce_replay_on_another_replica_is_refused(fake, on):
    from routes import auth

    auth.clear_consumed_oauth_nonces()
    nonce = "raw-nonce-value"
    key = pg_lease.hashed_key("oauth_nonce", nonce)
    fake.rows[key] = ("replica-b", time.monotonic() + 600)
    assert auth._consume_oauth_nonce(nonce) is False
    assert all(nonce not in str(c[1]) for c in fake.calls)
    assert fake.calls[0][1]["p_ttl_sec"] == auth._OAUTH_COOKIE_MAX_AGE
    # A fresh nonce goes through once, then is a replay in-process.
    assert auth._consume_oauth_nonce("fresh") is True
    assert auth._consume_oauth_nonce("fresh") is False


def test_oauth_nonce_flag_off_is_the_in_process_set(fake):
    from routes import auth

    auth.clear_consumed_oauth_nonces()
    assert auth._consume_oauth_nonce("n1") is True
    assert auth._consume_oauth_nonce("n1") is False
    assert fake.calls == []


def test_study_guide_single_flight_waits_for_another_replica(fake, on, monkeypatch):
    from routes import study_guide as sg

    key = pg_lease.hashed_key("study_guide", "u1", "off-1", "ex-1")
    fake.rows[key] = ("replica-b", time.monotonic() + 60)
    clock = _fake_clock(monkeypatch, lambda n: fake.rows.pop(key, None))
    with sg._single_flight("u1", "off-1", "ex-1"):
        assert fake.rows[key][0] != "replica-b"
    assert clock["sleeps"] == [sg.GUIDE_LEASE_POLL_S]
    assert [c[1]["p_key"] for c in fake.calls if c[0] == "claim_lease"][:2] == [key, key]
    assert key not in fake.rows
