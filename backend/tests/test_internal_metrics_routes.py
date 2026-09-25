"""GET /api/internal/metrics — the server-to-server aggregate numbers Canopy polls.

The consumer stores whatever a valid 200 says, append-only and first-write-wins
per hour, so a wrong number is permanent. Almost every test below is therefore
about the ways this route must REFUSE to answer: disabled (404), unauthenticated
(one generic 401), or unable to vouch for its numbers (5xx — never zeros, never
a partial body).

The numbers themselves are one Postgres function (`canopy_metrics`, migration
20260921055024) returning one JSONB document — `active_users`, `counts`,
`totals` — reached through `db.connection.rpc`; these hermetic tests stub that
seam. The SQL is exercised against a real database in
`tests/integration/test_internal_metrics_db.py`.
"""
from __future__ import annotations

import copy
import json
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


# What the function returns, as PostgREST delivers it: one bare JSON object.
# Key order inside a window is JSONB's (shortest key first), NOT the wire's.
DOC = {
    "active_users": {"7d": 318, "24h": 74, "30d": 402},
    "counts": {
        "signups": {"7d": 21, "24h": 3, "30d": 96},
        "llm_cost_cents": {"7d": 2961, "24h": 412, "30d": 11830},
        "errors_5xx": {"7d": 0, "24h": 0, "30d": 0},
    },
    "totals": {"users": 1204, "users_pending": 7, "rag_document_chunks": 0},
}
WIRE = (
    '{"active_users":{"24h":74,"7d":318,"30d":402},'
    '"counts":{"signups":{"24h":3,"7d":21,"30d":96},'
    '"llm_cost_cents":{"24h":412,"7d":2961,"30d":11830},'
    '"errors_5xx":{"24h":0,"7d":0,"30d":0}},'
    '"totals":{"users":1204,"users_pending":7,"rag_document_chunks":0}}'
)


def _doc(**sections) -> dict:
    """DOC with whole sections replaced (a deep copy — DOC is never mutated)."""
    return {**copy.deepcopy(DOC), **sections}


def _rpc_returning(result=DOC):
    return patch.object(internal_metrics, "rpc", return_value=result)


def _all_ints(body: dict) -> bool:
    leaves = [
        *body["active_users"].values(),
        *(v for entry in body["counts"].values() for v in entry.values()),
        *body["totals"].values(),
    ]
    return bool(leaves) and all(type(v) is int for v in leaves)


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
    with _rpc_returning():
        assert client.get(URL, headers=_auth()).status_code == 200
        client.cookies.set("sapling_session", "anything")
        assert client.get(URL, headers=RID).status_code == 401


# ── 200: three sections of integers and nothing else ─────────────────────────


def test_200_exact_body_and_integer_types(client, enabled):
    with _rpc_returning() as rpc:
        r = client.get(URL, headers=_auth())

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == DOC
    assert _all_ints(r.json())
    # On the wire, not just after parsing: 74, never "74" or 74.0 — and every
    # windowed entry rebuilt in contract order, not in the order JSONB stores it.
    assert r.text.replace(" ", "") == WIRE
    rpc.assert_called_once_with("canopy_metrics", {})


def test_200_has_exactly_the_three_sections(client, enabled):
    with _rpc_returning():
        body = client.get(URL, headers=_auth()).json()
    assert list(body) == ["active_users", "counts", "totals"]
    assert set(body["active_users"]) == {"24h", "7d", "30d"}
    assert all(set(entry) == {"24h", "7d", "30d"} for entry in body["counts"].values())


def test_active_users_is_the_v1_shape_unchanged(client, enabled):
    """v2 is additive: a v1 consumer reading only `active_users` sees exactly
    what it always did."""
    with _rpc_returning():
        body = client.get(URL, headers=_auth()).json()
    assert body["active_users"] == {"24h": 74, "7d": 318, "30d": 402}


def test_the_route_is_generic_over_keys(client, enabled):
    """Adding a metric is a change to the SQL function only: any contract-legal
    key is forwarded, and Canopy files one it has no label for under "Other"."""
    doc = _doc(
        counts={"brand_new_metric": {"24h": 1, "7d": 2, "30d": 3}},
        totals={"another_new_total": 9},
    )
    with _rpc_returning(doc):
        body = client.get(URL, headers=_auth()).json()
    assert body["counts"] == {"brand_new_metric": {"24h": 1, "7d": 2, "30d": 3}}
    assert body["totals"] == {"another_new_total": 9}


def test_an_absent_key_stays_absent(client, enabled):
    """The function omits a key it cannot answer honestly (events logging off,
    no priced LLM call). The route must not paper over that with a zero."""
    with _rpc_returning(_doc(counts={}, totals={})):
        r = client.get(URL, headers=_auth())
    assert r.status_code == 200
    assert r.json() == {"active_users": DOC["active_users"], "counts": {}, "totals": {}}
    assert "0" not in json.dumps({k: r.json()[k] for k in ("counts", "totals")})


def test_a_document_wrapped_in_a_one_row_list_is_the_same_document(client, enabled):
    with _rpc_returning([DOC]):
        r = client.get(URL, headers=_auth())
    assert r.status_code == 200
    assert r.json() == DOC


def test_windows_nest_when_activity_is_only_in_the_wider_ones(client, enabled):
    # One user today, a second within the week, a third within the month.
    doc = _doc(active_users={"24h": 1, "7d": 2, "30d": 3})
    with _rpc_returning(doc):
        users = client.get(URL, headers=_auth()).json()["active_users"]
    assert users["24h"] <= users["7d"] <= users["30d"]
    assert users == {"24h": 1, "7d": 2, "30d": 3}


def test_a_quiet_month_is_a_real_zero(client, enabled):
    """Zeros are legitimate when the DATABASE says zero — only a failure must
    never be reported as one."""
    zero = {"24h": 0, "7d": 0, "30d": 0}
    doc = {"active_users": zero, "counts": {"signups": zero}, "totals": {"users": 0}}
    with _rpc_returning(doc):
        r = client.get(URL, headers=_auth())
    assert r.status_code == 200
    assert r.json() == doc


def test_the_contract_limits_themselves_are_accepted(client, enabled):
    """Off-by-one guards: the largest legal value, the longest legal key and
    exactly 48 / 24 keys are all VALID — only one past each is refused."""
    big = 1_000_000_000_000
    doc = {
        "active_users": {"24h": 0, "7d": 0, "30d": 10_000_000},
        "counts": {
            **{f"k{i}": {"24h": 0, "7d": 1, "30d": 1} for i in range(47)},
            "a" * 40: {"24h": big, "7d": big, "30d": big},
        },
        "totals": {**{f"t{i}": i for i in range(23)}, "z9_": big},
    }
    with _rpc_returning(doc):
        r = client.get(URL, headers=_auth())
    assert r.status_code == 200
    assert r.json() == doc
    assert len(r.json()["counts"]) == 48 and len(r.json()["totals"]) == 24


def test_route_is_not_in_the_openapi_schema(client):
    assert URL not in client.get("/openapi.json").json()["paths"]


def test_trailing_slash_is_not_the_route(client, enabled):
    """Canopy sends redirect: "manual" and treats a 3xx as a failure; this pins
    that the canonical path answers directly (no redirect hop to get there)."""
    with _rpc_returning():
        r = client.get(URL, headers=_auth(), follow_redirects=False)
    assert r.status_code == 200


# ── 5xx: never zeros, never a partial body ───────────────────────────────────


def _assert_unavailable(r):
    assert r.status_code == 503
    assert r.json() == {
        "detail": "Metrics temporarily unavailable",
        "request_id": RID["X-Request-ID"],
    }
    for section in ("active_users", "counts", "totals"):
        assert section not in r.text
    assert not any(ch.isdigit() for ch in r.json()["detail"])


def test_db_failure_is_a_5xx_not_zeros(client, enabled):
    request = httpx.Request("POST", "https://db.invalid/rest/v1/rpc/canopy_metrics")
    boom = httpx.HTTPStatusError(
        "500", request=request, response=httpx.Response(500, request=request),
    )
    with patch.object(internal_metrics, "rpc", side_effect=boom):
        _assert_unavailable(client.get(URL, headers=_auth()))


def test_missing_function_is_a_5xx(client, enabled):
    """Code deployed before the migration is applied: PostgREST 404s the RPC.
    Same answer v1 gave — Canopy writes nothing until the migration lands."""
    request = httpx.Request("POST", "https://db.invalid/rest/v1/rpc/canopy_metrics")
    missing = httpx.HTTPStatusError(
        "404", request=request, response=httpx.Response(404, request=request),
    )
    with patch.object(internal_metrics, "rpc", side_effect=missing):
        _assert_unavailable(client.get(URL, headers=_auth()))


_W = {"24h": 1, "7d": 2, "30d": 3}

# Every way a value can fail to be "a JSON integer, 0 <= v <= ceiling". bool is
# here because `isinstance(True, int)` is True in Python and it would go out as
# the JSON literal `true`; 3.0 because it compares equal to 3 and is not one.
_NOT_A_COUNT = [None, "1", 1.5, 3.0, True, False, -1, [1], {"n": 1}]

_BAD_DOCUMENTS = {
    # the document itself
    "nothing": None,
    "no rows": [],
    "two documents": [DOC, DOC],
    "a row that is not a document": ["not a document"],
    "a string": json.dumps(DOC),
    "a number": 7,
    "v1's row shape": [{"d1": 1, "d7": 2, "d30": 3}],
    "no active_users": {"counts": {}, "totals": {}},
    "no counts": {"active_users": _W, "totals": {}},
    "no totals": {"active_users": _W, "counts": {}},
    "an extra top-level key": _doc(user_ids=["u1", "u2"]),
    "an extra top-level number": _doc(generated_at=1789000000),
    # active_users: whole-or-nothing, v1's rules
    "active_users is not an object": _doc(active_users=74),
    "active_users misses a window": _doc(active_users={"24h": 1, "7d": 2}),
    "active_users has a fourth window": _doc(active_users={**_W, "90d": 4}),
    "active_users past Canopy's ceiling": _doc(active_users={"24h": 1, "7d": 2, "30d": 10_000_001}),
    "active_users 24h > 7d": _doc(active_users={"24h": 3, "7d": 2, "30d": 3}),
    "active_users 7d > 30d": _doc(active_users={"24h": 1, "7d": 4, "30d": 3}),
    **{
        f"active_users window is {bad!r}": _doc(active_users={"24h": bad, "7d": 2, "30d": 3})
        for bad in _NOT_A_COUNT
    },
    # counts
    "counts is a list": _doc(counts=[{"signups": _W}]),
    "counts is null": _doc(counts=None),
    "counts is a number": _doc(counts=3),
    "counts has 49 keys": _doc(counts={f"k{i}": _W for i in range(49)}),
    "a counts entry is a bare number": _doc(counts={"signups": 3}),
    "a counts entry misses a window": _doc(counts={"signups": {"24h": 1, "7d": 2}}),
    "a counts entry has a fourth window": _doc(counts={"signups": {**_W, "90d": 4}}),
    "a counts entry past the ceiling": _doc(counts={"signups": {"24h": 1, "7d": 2, "30d": 10**12 + 1}}),
    "a counts entry with 24h > 7d": _doc(counts={"signups": {"24h": 3, "7d": 2, "30d": 3}}),
    "a counts entry with 7d > 30d": _doc(counts={"signups": {"24h": 1, "7d": 4, "30d": 3}}),
    "one bad counts entry among good ones": _doc(
        counts={"signups": _W, "approvals": _W, "llm_cost_cents": {"24h": 1, "7d": 2, "30d": 1.5}}
    ),
    **{
        f"a counts window is {bad!r}": _doc(counts={"signups": {"24h": 1, "7d": bad, "30d": 3}})
        for bad in _NOT_A_COUNT
    },
    # totals
    "totals is a list": _doc(totals=[1204]),
    "totals is null": _doc(totals=None),
    "totals has 25 keys": _doc(totals={f"t{i}": i for i in range(25)}),
    "a total past the ceiling": _doc(totals={"users": 10**12 + 1}),
    "a total shaped like a windowed entry": _doc(totals={"users": _W}),
    "one bad total among good ones": _doc(totals={"users": 1204, "rooms": "12"}),
    **{f"a total is {bad!r}": _doc(totals={"users": bad}) for bad in _NOT_A_COUNT},
    # keys: ^[a-z][a-z0-9_]{0,39}$
    **{
        f"counts key {key!r}": _doc(counts={key: _W})
        for key in ("", "Signups", "9lives", "_private", "has-dash", "has space", "sign.ups",
                    "a" * 41, "signups\n", "ünicode")
    },
    **{
        f"totals key {key!r}": _doc(totals={key: 1})
        for key in ("", "Users", "1st", "has-dash", "a" * 41, "users\n")
    },
}


@pytest.mark.parametrize("result", _BAD_DOCUMENTS.values(), ids=_BAD_DOCUMENTS.keys())
def test_an_untrustworthy_result_is_a_5xx_never_a_partial_body(client, enabled, result):
    """Everything Canopy checks (its spec, section 3) is checked here first. Canopy would
    drop the one bad key and keep the rest — silently; this route refuses the
    WHOLE response instead, so the failure is visible in THIS app's logs and no
    number from a document that was wrong somewhere is ever stored."""
    with patch.object(internal_metrics, "rpc", return_value=result):
        _assert_unavailable(client.get(URL, headers=_auth()))


def test_a_refused_document_is_logged_by_key_never_by_value(client, enabled, caplog):
    caplog.set_level(logging.DEBUG)
    doc = _doc(totals={"users": 1204, "rooms": -987654})
    with _rpc_returning(doc):
        _assert_unavailable(client.get(URL, headers=_auth()))
    logged = caplog.text
    assert "totals.rooms" in logged
    assert "987654" not in logged


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
    request = httpx.Request("POST", "https://db.invalid/rest/v1/rpc/canopy_metrics")
    boom = httpx.HTTPStatusError(
        "500", request=request, response=httpx.Response(500, request=request),
    )

    with _rpc_returning():
        assert client.get(URL, headers=_auth()).status_code == 200
    assert client.get(URL, headers=_auth(WRONG)).status_code == 401
    assert client.get(URL, headers={"Authorization": f"Basic {TOKEN}", **RID}).status_code == 401
    with patch.object(internal_metrics, "rpc", side_effect=boom):
        assert client.get(URL, headers=_auth()).status_code == 503
    with _rpc_returning(_doc(active_users={"24h": 9, "7d": 2, "30d": 3})):
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
