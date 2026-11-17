"""#771: the backend half of the ``hide_<feature>`` flags, and the flag
cache's single-flight + bounded maps."""
from __future__ import annotations

import re
import threading
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from main import app
from services import feature_flags as ff

client = TestClient(app, raise_server_exceptions=False)

#: (flag, a gated path, an exempt path or None) — one per gated router.
GATED = [
    ("hide_quiz", "/api/quiz/config", "/api/quiz/attempts?user_id=u1"),
    ("hide_study", "/api/flashcards/user/u1", None),
    ("hide_study", "/api/study-guide/u1/guides", None),
    ("hide_study", "/api/study/u1/daily", None),
    ("hide_calendar", "/api/calendar/status/u1", "/api/calendar/upcoming/u1"),
    # The consent flow lives in routes/calendar_connect.py, included by calendar.py.
    ("hide_calendar", "/api/calendar/auth-url?user_id=u1", None),
    ("hide_social", "/api/social/public-rooms?user_id=u1", "/api/social/friends/u1"),
    ("hide_achievements", "/api/gamification/leaderboard?user_id=u1",
     "/api/gamification/me?user_id=u1"),
    ("hide_grades", "/api/gradebook/summary?user_id=u1", None),
    ("hide_notetaker", "/api/notes/user/u1", None),
]


def _gated(r) -> bool:
    return r.status_code == 404 and r.json().get("detail") == "Not found"


def test_every_hide_flag_is_enforced_or_says_why():
    hide = {k for k in ff.REGISTRY if k.startswith("hide_")}
    enforced, skipped = set(ff.NAV_FEATURE_API), set(ff.NAV_FEATURES_NOT_ENFORCED)
    assert enforced | skipped == hide
    assert not enforced & skipped
    prefixes = [p for routers in ff.NAV_FEATURE_API.values() for p in routers]
    assert len(prefixes) == len(set(prefixes)), "a router is gated by two flags"


def test_every_gated_router_has_a_probe():
    prefixes = {p for routers in ff.NAV_FEATURE_API.values() for p in routers}
    probed = {next(p for p in prefixes if path.startswith(p + "/")) for _, path, _ in GATED}
    assert probed == prefixes


@pytest.mark.parametrize("flag,path,exempt", GATED)
def test_a_hidden_feature_404s_on_its_api(monkeypatch, flag, path, exempt):
    monkeypatch.setenv(f"SAPLING_FLAG_{flag.upper()}", "on")
    assert _gated(client.get(path)), f"{path} served while {flag} hides it"
    if exempt:
        assert not _gated(client.get(exempt)), f"{exempt} is used by another surface"


@pytest.mark.parametrize("flag,path,exempt", GATED)
def test_a_visible_feature_is_not_gated(monkeypatch, flag, path, exempt):
    monkeypatch.setenv(f"SAPLING_FLAG_{flag.upper()}", "off")
    assert not _gated(client.get(path))


#: (flag, method, path): a call ANOTHER visible surface makes on a gated
#: router, so it must keep working while the flag hides the feature's page.
EXEMPT_CALLS = [
    # Dashboard: upcoming-deadlines card.
    ("hide_calendar", "GET", "/api/calendar/upcoming/u1"),
    # Study hub exam tabs + deadlines; Flashcards page exam tags.
    ("hide_calendar", "GET", "/api/calendar/all/u1"),
    # Study hub "+ Add Exam or Deadline".
    ("hide_calendar", "POST", "/api/calendar/save"),
    # Study hub Exams and Deadlines editor.
    ("hide_calendar", "PATCH", "/api/calendar/assignments/a1"),
    ("hide_calendar", "DELETE", "/api/calendar/assignments/a1?user_id=u1"),
    # Tree + Study hub: recent attempts.
    ("hide_quiz", "GET", "/api/quiz/attempts?user_id=u1"),
]

#: (flag, method, path): the rest of an exempted router stays hidden. An
#: exemption names one method on one path, never the router.
STILL_GATED_CALLS = [
    ("hide_calendar", "GET", "/api/calendar/status/u1"),
    ("hide_calendar", "GET", "/api/calendar/auth-url?user_id=u1"),
    ("hide_calendar", "GET", "/api/calendar/import/u1"),
    ("hide_calendar", "POST", "/api/calendar/extract"),
    ("hide_calendar", "POST", "/api/calendar/suggest-study-blocks"),
    ("hide_calendar", "POST", "/api/calendar/sync"),
    ("hide_calendar", "POST", "/api/calendar/export"),
    ("hide_calendar", "DELETE", "/api/calendar/disconnect/u1"),
    # The hub hides its own Quiz buttons under hide_quiz: no exemption.
    ("hide_quiz", "POST", "/api/quiz/generate"),
    ("hide_quiz", "GET", "/api/quiz/attempts/a1"),
]


def _call(method: str, path: str):
    body = {} if method in ("POST", "PATCH") else None
    return client.request(method, path, json=body)


@pytest.mark.parametrize("flag,method,path", EXEMPT_CALLS)
def test_a_cross_feature_call_survives_the_hidden_feature(monkeypatch, flag, method, path):
    monkeypatch.setenv(f"SAPLING_FLAG_{flag.upper()}", "on")
    r = _call(method, path)
    assert not _gated(r), f"{method} {path} is used by another surface"
    assert r.status_code != 405, f"{method} {path} is not a route"


@pytest.mark.parametrize("flag,method,path", STILL_GATED_CALLS)
def test_the_rest_of_an_exempted_router_stays_hidden(monkeypatch, flag, method, path):
    monkeypatch.setenv(f"SAPLING_FLAG_{flag.upper()}", "on")
    assert _gated(_call(method, path)), f"{method} {path} served while {flag} hides it"
    monkeypatch.setenv(f"SAPLING_FLAG_{flag.upper()}", "off")
    assert not _gated(_call(method, path)), f"{method} {path} is not a route"


def test_every_exemption_has_a_probe():
    """A new NAV_FEATURE_API exemption needs a row in EXEMPT_CALLS (or, for
    the routers GATED covers with a GET, its exempt column)."""
    probes = [(f, m, p.split("?")[0]) for f, m, p in EXEMPT_CALLS]
    probes += [(f, "GET", e.split("?")[0]) for f, _, e in GATED if e]
    for flag, routers in ff.NAV_FEATURE_API.items():
        for prefix, exemptions in routers.items():
            for method, pattern in exemptions:
                rx = re.compile(re.escape(prefix) + pattern + r"/?$")
                assert any(
                    f == flag and method in ("*", m) and rx.match(p) for f, m, p in probes
                ), f"no probe for {flag}: {method} {prefix}{pattern}"


def test_admin_and_auth_routes_are_never_gated(monkeypatch):
    for flag in ff.NAV_FEATURE_API:
        monkeypatch.setenv(f"SAPLING_FLAG_{flag.upper()}", "on")
    assert client.get("/api/flags").status_code == 200
    assert client.get("/api/health").status_code == 200


# ── /api/flags degraded marker ──────────────────────────────────────────────


def test_flags_route_says_when_the_store_is_unreadable(monkeypatch):
    # the suite turns the learning_loop flag on by env override (conftest); this
    # test reads every flag off the (down) store
    monkeypatch.delenv("SAPLING_FLAG_LEARNING_LOOP", raising=False)
    with patch("services.feature_flags.read_config", side_effect=httpx.ConnectError("down")):
        r = client.get("/api/flags")
    assert r.status_code == 200
    assert r.json()["degraded"] is True
    assert set(r.json()["flags"].values()) == {"off"}


def test_flags_route_has_no_degraded_marker_normally():
    assert "degraded" not in client.get("/api/flags").json()


# ── Single-flight + bounded maps ────────────────────────────────────────────


class _Arrivals:
    """Where each concurrent caller has got to: reading the store, waiting on
    the read already in flight (a follower), or back with its answer. A test
    holds the leader's read until every caller is accounted for, instead of
    sleeping and hoping the others piled up; a caller that skips the flight
    is accounted for as soon as it returns, so that fails at once."""

    def __init__(self):
        self.reads = 0
        self.followers = 0
        self._callers: set[int] = set()
        self._changed = threading.Condition()

    def _arrive(self):
        self._callers.add(threading.get_ident())
        self._changed.notify_all()

    def read(self):
        with self._changed:
            self.reads += 1
            self._arrive()

    def follow(self):
        with self._changed:
            self.followers += 1
            self._arrive()

    def returned(self):
        with self._changed:
            self._arrive()

    def wait_for(self, callers):
        with self._changed:
            assert self._changed.wait_for(lambda: len(self._callers) >= callers, timeout=30)


@pytest.fixture
def arrivals(monkeypatch):
    """Every in-flight read reports each follower that waits on it."""
    seen = _Arrivals()

    class _CountedDone(threading.Event):
        def wait(self, timeout=None):
            seen.follow()
            return super().wait(timeout)

    class _Flight(ff._Flight):
        def __init__(self, generation):
            super().__init__(generation)
            self.done = _CountedDone()

    monkeypatch.setattr(ff, "_Flight", _Flight)
    return seen


def test_concurrent_cold_reads_hit_the_store_once(arrivals):
    """Eight cold callers at once: one reads the store, seven wait on its read.
    The leader's read is held until every caller is accounted for, so the
    waiters provably piled up behind it (no sleep deciding that), and a broken
    single-flight shows as a second read at once rather than after a timeout."""
    gate = threading.Event()

    def slow_read(**_k):
        arrivals.read()
        assert gate.wait(30)  # a hang guard, never reached when the test passes
        return ff.Snapshot(flags={}, targets={})

    results: list = []

    def call():
        try:
            results.append(ff._get_snapshot())
        finally:
            arrivals.returned()

    with patch("services.feature_flags.read_config", side_effect=slow_read):
        threads = [threading.Thread(target=call) for _ in range(8)]
        for t in threads:
            t.start()
        arrivals.wait_for(8)
        gate.set()
        for t in threads:
            t.join(30)
    assert arrivals.reads == 1 and arrivals.followers == 7
    assert len(results) == 8


def test_a_failed_leader_read_fails_its_waiters_closed(arrivals):
    """The leader's read fails only once the three other callers have joined
    it, so each fails closed on the leader's own error. Without that hold, a
    caller arriving after the failure fails on the store-down mark instead and
    the test passes without exercising the waiters at all."""
    gate = threading.Event()

    def failing_read(**_k):
        arrivals.read()
        assert gate.wait(30)  # a hang guard, never reached when the test passes
        raise httpx.ConnectError("down")

    errors: list = []

    def call():
        try:
            ff._get_snapshot()
        except Exception as exc:
            errors.append(type(exc))
        finally:
            arrivals.returned()

    with patch("services.feature_flags.read_config", side_effect=failing_read) as rc:
        threads = [threading.Thread(target=call) for _ in range(4)]
        for t in threads:
            t.start()
        arrivals.wait_for(4)
        gate.set()
        for t in threads:
            t.join(30)
    assert rc.call_count == 1 and arrivals.followers == 3
    assert errors == [httpx.ConnectError] * 4


def test_roles_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(ff, "ROLES_CACHE_MAX", 5)

    class _T:
        def select(self, *a, **k):
            return []

    with patch("services.feature_flags.table", return_value=_T()):
        for i in range(20):
            ff._user_roles(f"user_{i}")
    assert len(ff._roles) == 5
    assert "user_19" in ff._roles and "user_0" not in ff._roles


def test_warned_set_is_bounded(monkeypatch):
    monkeypatch.setattr(ff, "WARNED_MAX", 3)
    monkeypatch.setattr(ff, "_warned", set())
    for i in range(10):
        ff.explain(f"not_registered_{i}", None)
    assert len(ff._warned) <= 3
