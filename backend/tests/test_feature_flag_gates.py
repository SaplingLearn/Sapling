"""#771: the backend half of the ``hide_<feature>`` flags, and the flag
cache's single-flight + bounded maps."""
from __future__ import annotations

import re
import threading
import time
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
    ("hide_study", "/api/study-guide/u1/cached", None),
    ("hide_study", "/api/study/u1/daily", None),
    ("hide_calendar", "/api/calendar/status/u1", "/api/calendar/upcoming/u1"),
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


def test_flags_route_says_when_the_store_is_unreadable():
    with patch("services.feature_flags.read_config", side_effect=httpx.ConnectError("down")):
        r = client.get("/api/flags")
    assert r.status_code == 200
    assert r.json()["degraded"] is True
    assert set(r.json()["flags"].values()) == {"off"}


def test_flags_route_has_no_degraded_marker_normally():
    assert "degraded" not in client.get("/api/flags").json()


# ── Single-flight + bounded maps ────────────────────────────────────────────


def test_concurrent_cold_reads_hit_the_store_once():
    calls: list[int] = []
    gate = threading.Event()

    def slow_read(**_k):
        calls.append(1)
        gate.wait(5)
        return ff.Snapshot(flags={}, targets={})

    results: list = []
    with patch("services.feature_flags.read_config", side_effect=slow_read):
        threads = [threading.Thread(target=lambda: results.append(ff._get_snapshot()))
                   for _ in range(8)]
        for t in threads:
            t.start()
        deadline = time.monotonic() + 5
        while not calls and time.monotonic() < deadline:
            time.sleep(0.001)
        time.sleep(0.05)  # let the others pile up behind the leader
        gate.set()
        for t in threads:
            t.join(5)
    assert len(calls) == 1
    assert len(results) == 8


def test_a_failed_leader_read_fails_its_waiters_closed():
    gate = threading.Event()

    def failing_read(**_k):
        gate.wait(5)
        raise httpx.ConnectError("down")

    errors: list = []

    def call():
        try:
            ff._get_snapshot()
        except Exception as exc:
            errors.append(type(exc))

    with patch("services.feature_flags.read_config", side_effect=failing_read) as rc:
        threads = [threading.Thread(target=call) for _ in range(4)]
        for t in threads:
            t.start()
        time.sleep(0.05)
        gate.set()
        for t in threads:
            t.join(5)
    assert rc.call_count == 1
    assert len(errors) == 4


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
