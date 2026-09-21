"""GET /api/internal/metrics — the server-to-server active-user counts Canopy polls.

The consumer stores whatever a valid 200 says, append-only and first-write-wins
per hour, so a wrong number is permanent. Almost every test below is therefore
about the ways this route must REFUSE to answer: disabled (404), unauthenticated
(one generic 401), or unable to vouch for its numbers (5xx — never zeros, never
a partial body).

The counting itself is one Postgres function (`canopy_active_users`, migration
20260921041555) reached through `db.connection.rpc`; these hermetic tests stub
that seam. The SQL is exercised against a real database in
`tests/integration/test_internal_metrics_db.py`.
"""
from __future__ import annotations

import logging
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

import main
import routes.internal_metrics as internal_metrics
from config import canopy_metrics_token
from services import events_service

URL = "/api/internal/metrics"
TOKEN = "s3cr3t-canopy-token-0f1e2d3c4b5a69788796a5b4c3d2e1f0"
WRONG = "wr0ng-canopy-token-ffffffffffffffffffffffffffffffff"
# A fixed, caller-supplied request id makes the {detail, request_id} error
# envelope byte-comparable across requests.
RID = {"X-Request-ID": "canopy-metrics-test-0001"}


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("CANOPY_METRICS_TOKEN", TOKEN)


def _auth(token: str = TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}", **RID}


def _rpc_returning(*rows):
    return patch.object(internal_metrics, "rpc", return_value=list(rows))


# ── config ───────────────────────────────────────────────────────────────────


def test_token_is_read_at_call_time_and_stripped(monkeypatch):
    monkeypatch.setenv("CANOPY_METRICS_TOKEN", f"  {TOKEN}\n")
    assert canopy_metrics_token() == TOKEN


@pytest.mark.parametrize("value", ["", "   ", "\n"])
def test_blank_token_is_unset(monkeypatch, value):
    monkeypatch.setenv("CANOPY_METRICS_TOKEN", value)
    assert canopy_metrics_token() == ""


# ── 404: the feature is off ──────────────────────────────────────────────────


def _assert_disabled(client):
    """Indistinguishable from a path that was never routed — same status, same
    body — and the database is never asked, even for a caller holding a token."""
    with patch.object(internal_metrics, "rpc") as rpc:
        unrouted = client.get("/api/internal/no-such-route", headers=RID)
        for headers in (RID, _auth(), {"Authorization": "Bearer ", **RID}):
            r = client.get(URL, headers=headers)
            assert r.status_code == 404
            assert r.json() == unrouted.json()
    rpc.assert_not_called()


def test_404_when_token_env_is_unset(client, monkeypatch):
    monkeypatch.delenv("CANOPY_METRICS_TOKEN", raising=False)
    _assert_disabled(client)


@pytest.mark.parametrize("value", ["", "   "])
def test_404_when_token_env_is_empty(client, monkeypatch, value):
    """An empty expected token must never reach the compare: `Bearer ` + ""
    would equal an empty bearer header and hand the counts to anyone."""
    monkeypatch.setenv("CANOPY_METRICS_TOKEN", value)
    _assert_disabled(client)


# ── 401: one generic answer for every wrong credential ───────────────────────

_BAD_CREDENTIALS = {
    "no header": {},
    "non-bearer scheme": {"Authorization": f"Basic {TOKEN}"},
    "wrong token": {"Authorization": f"Bearer {WRONG}"},
    "bare token, no scheme": {"Authorization": TOKEN},
    "lowercase scheme": {"Authorization": f"bearer {TOKEN}"},
    "token with a suffix": {"Authorization": f"Bearer {TOKEN}x"},
    "token prefix only": {"Authorization": f"Bearer {TOKEN[:-1]}"},
    "empty bearer": {"Authorization": "Bearer "},
    # Bytes, because httpx refuses to encode a non-ASCII str header. On the
    # server it arrives latin-1-decoded — a str hmac.compare_digest would raise
    # TypeError on (a 500) if the route compared str instead of bytes.
    "non-ascii header": {"Authorization": "Bearer caf\xe9".encode("latin-1")},
}


def test_401_is_identical_for_every_bad_credential(client, enabled):
    bodies = {}
    with patch.object(internal_metrics, "rpc") as rpc:
        for name, headers in _BAD_CREDENTIALS.items():
            r = client.get(URL, headers={**headers, **RID})
            assert r.status_code == 401, name
            assert "www-authenticate" not in r.headers, name
            bodies[name] = r.content
    rpc.assert_not_called()

    # The three the contract names, then all of them: byte-identical.
    assert bodies["no header"] == bodies["non-bearer scheme"] == bodies["wrong token"]
    assert len(set(bodies.values())) == 1
    body = client.get(URL, headers=RID).json()
    assert body == {"detail": "Unauthorized", "request_id": RID["X-Request-ID"]}


def test_a_user_session_is_neither_required_nor_sufficient(client, enabled):
    """conftest stubs session auth to always pass; the route must not care."""
    with _rpc_returning({"d1": 1, "d7": 1, "d30": 1}):
        assert client.get(URL, headers=_auth()).status_code == 200
        client.cookies.set("sapling_session", "anything")
        assert client.get(URL, headers=RID).status_code == 401


# ── 200: three integers and nothing else ─────────────────────────────────────


def test_200_exact_body_and_integer_types(client, enabled):
    with _rpc_returning({"d1": 74, "d7": 318, "d30": 318}) as rpc:
        r = client.get(URL, headers=_auth())

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == {"active_users": {"24h": 74, "7d": 318, "30d": 318}}
    # On the wire, not just after parsing: 74, never "74" or 74.0.
    assert r.text.replace(" ", "") == '{"active_users":{"24h":74,"7d":318,"30d":318}}'
    rpc.assert_called_once_with("canopy_active_users", {})


def test_200_has_no_key_beyond_the_three_windows(client, enabled):
    """The function's row is projected, never passed through: a column added to
    it later (or anything else PostgREST returns) must not reach the wire."""
    row = {"d1": 1, "d7": 2, "d30": 3, "user_ids": ["u1", "u2", "u3"], "email": "a@bu.edu"}
    with _rpc_returning(row):
        body = client.get(URL, headers=_auth()).json()

    assert set(body) == {"active_users"}
    assert set(body["active_users"]) == {"24h", "7d", "30d"}
    assert all(type(v) is int for v in body["active_users"].values())
    assert body == {"active_users": {"24h": 1, "7d": 2, "30d": 3}}


def test_windows_nest_when_users_are_active_only_in_the_wider_ones(client, enabled):
    # One user today, a second within the week, a third within the month.
    with _rpc_returning({"d1": 1, "d7": 2, "d30": 3}):
        users = client.get(URL, headers=_auth()).json()["active_users"]
    assert users["24h"] <= users["7d"] <= users["30d"]
    assert users == {"24h": 1, "7d": 2, "30d": 3}


def test_a_quiet_month_is_a_real_zero(client, enabled):
    """Zeros are legitimate when the DATABASE says zero — only a failure must
    never be reported as one."""
    with _rpc_returning({"d1": 0, "d7": 0, "d30": 0}):
        r = client.get(URL, headers=_auth())
    assert r.status_code == 200
    assert r.json() == {"active_users": {"24h": 0, "7d": 0, "30d": 0}}


def test_route_is_not_in_the_openapi_schema(client):
    assert URL not in client.get("/openapi.json").json()["paths"]


def test_trailing_slash_is_not_the_route(client, enabled):
    """Canopy sends redirect: "manual" and treats a 3xx as a failure; this pins
    that the canonical path answers directly (no redirect hop to get there)."""
    with _rpc_returning({"d1": 1, "d7": 1, "d30": 1}):
        r = client.get(URL, headers=_auth(), follow_redirects=False)
    assert r.status_code == 200


# ── 5xx: never zeros, never a partial body ───────────────────────────────────


def _assert_unavailable(r):
    assert r.status_code == 503
    assert r.json() == {
        "detail": "Metrics temporarily unavailable",
        "request_id": RID["X-Request-ID"],
    }
    assert "active_users" not in r.text
    assert not any(ch.isdigit() for ch in r.json()["detail"])


def test_db_failure_is_a_5xx_not_zeros(client, enabled):
    request = httpx.Request("POST", "https://db.invalid/rest/v1/rpc/canopy_active_users")
    boom = httpx.HTTPStatusError(
        "500", request=request, response=httpx.Response(500, request=request),
    )
    with patch.object(internal_metrics, "rpc", side_effect=boom):
        _assert_unavailable(client.get(URL, headers=_auth()))


def test_missing_function_is_a_5xx(client, enabled):
    """Code deployed before the migration is applied: PostgREST 404s the RPC."""
    request = httpx.Request("POST", "https://db.invalid/rest/v1/rpc/canopy_active_users")
    missing = httpx.HTTPStatusError(
        "404", request=request, response=httpx.Response(404, request=request),
    )
    with patch.object(internal_metrics, "rpc", side_effect=missing):
        _assert_unavailable(client.get(URL, headers=_auth()))


@pytest.mark.parametrize(
    "result",
    [
        [],                                              # no row at all
        None,
        {"d1": 1, "d7": 2, "d30": 3},                    # a bare object, not a row list
        [{"d1": 1, "d7": 2, "d30": 3}, {"d1": 1, "d7": 2, "d30": 3}],
        ["not a row"],
        [{"d1": 1, "d7": 2}],                            # a window missing
        [{"d1": None, "d7": 2, "d30": 3}],
        [{"d1": "1", "d7": 2, "d30": 3}],                # a string is not a count
        [{"d1": 1.5, "d7": 2, "d30": 3}],
        [{"d1": True, "d7": 2, "d30": 3}],               # bool is an int in Python
        [{"d1": -1, "d7": 2, "d30": 3}],
        [{"d1": 1, "d7": 2, "d30": 10_000_001}],         # past Canopy's own ceiling
        [{"d1": 3, "d7": 2, "d30": 3}],                  # 24h > 7d
        [{"d1": 1, "d7": 4, "d30": 3}],                  # 7d > 30d
    ],
)
def test_an_untrustworthy_result_is_a_5xx_never_a_partial_body(client, enabled, result):
    """One bad window refuses the other two — the same rule Canopy applies on
    its side, applied here first so a refusal is visible in THIS app's logs."""
    with patch.object(internal_metrics, "rpc", return_value=result):
        _assert_unavailable(client.get(URL, headers=_auth()))


def test_there_is_no_scan_path_that_could_truncate():
    """admin_analytics counts distinct users by paging `events` into Python and
    stops at a 100k-row cap with `truncated: true`. A truncated scan UNDERCOUNTS,
    and Canopy would keep that number forever — so this route must never grow a
    row-scan fallback. It counts in SQL (which cannot truncate) or answers 5xx.
    Pinned on the module's namespace: the row-reading seams are not importable
    from it, so there is no scan for a cap to cut short."""
    for seam in ("table", "page_all", "_scan_range", "SupabaseTable"):
        assert not hasattr(internal_metrics, seam), (
            f"internal_metrics must not read rows via {seam}"
        )


# ── the token never reaches a log or an event row ────────────────────────────


def test_token_never_appears_in_logs_or_events(client, enabled, caplog, sink):
    caplog.set_level(logging.DEBUG)
    request = httpx.Request("POST", "https://db.invalid/rest/v1/rpc/canopy_active_users")
    boom = httpx.HTTPStatusError(
        "500", request=request, response=httpx.Response(500, request=request),
    )

    with _rpc_returning({"d1": 1, "d7": 2, "d30": 3}):
        assert client.get(URL, headers=_auth()).status_code == 200
    assert client.get(URL, headers=_auth(WRONG)).status_code == 401
    assert client.get(URL, headers={"Authorization": f"Basic {TOKEN}", **RID}).status_code == 401
    with patch.object(internal_metrics, "rpc", side_effect=boom):
        assert client.get(URL, headers=_auth()).status_code == 503
    with patch.object(internal_metrics, "rpc", return_value=[{"d1": 9, "d7": 2, "d30": 3}]):
        assert client.get(URL, headers=_auth()).status_code == 503

    events_service.flush_now()
    logged = caplog.text + "".join(
        f"{rec.getMessage()} {rec.args!r} {rec.exc_text or ''}" for rec in caplog.records
    )
    assert caplog.records, "nothing was captured — the assertion below would be vacuous"
    for secret in (TOKEN, WRONG, "Bearer ", "Basic "):
        assert secret not in logged
        assert secret not in repr(sink)
    # The failures WERE logged (so the owner can see why Canopy went quiet) …
    assert any(r.name == "sapling.internal_metrics" and r.levelno >= logging.ERROR
               for r in caplog.records)
    # … and the 4xx/5xx rows the middleware records carry no actor.
    assert sink and all(row["user_id"] is None for row in sink)
