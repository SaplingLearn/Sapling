"""The cross-environment account copy's HTTP surfaces and peer client.

- `/api/internal/account-sync/*` (routes/internal_account_sync.py): the
  server-to-server half, token-guarded exactly like /api/internal/metrics.
- `POST /api/admin/accounts/{user_id}/copy` (routes/admin_account_sync.py):
  the admin button, mapping every failure onto the spec's status contract.
- services/account_sync_client.py: the httpx peer client (httpx's module-level
  get/post are stubbed — the venv has no respx).

`main.py` mounts these routers; here they are mounted on a bare app at the
same prefixes so the tests do not depend on that wiring.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import routes.admin_account_sync as admin_sync
import routes.internal_account_sync as internal_sync
from services import account_bundle, account_summary, account_sync_client
from services.account_bundle import AccountNotFound, BundleError
from services.account_ops_lock import account_op
from services.account_wipe import AccountWipeIncomplete

INTERNAL = "/api/internal/account-sync"
ADMIN = "/api/admin/accounts"
TOKEN = "inbound-token-0123456789abcdef0123456789abcdef"
PEER_TOKEN = "peer-token-fedcba9876543210fedcba9876543210"
PEER = "https://peer.example"
UID = "user_42"


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(internal_sync.router, prefix=INTERNAL)
    app.include_router(admin_sync.router, prefix=ADMIN)
    return TestClient(app)


@pytest.fixture
def events(monkeypatch):
    seen: list[tuple] = []
    for mod in (internal_sync, admin_sync):
        monkeypatch.setattr(mod, "log_event", lambda et, **kw: seen.append((et, kw)))
    return seen


@pytest.fixture
def inbound(monkeypatch):
    monkeypatch.setenv("ACCOUNT_SYNC_INBOUND_TOKEN", TOKEN)


def _auth(token: str = TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── internal: the token gate ────────────────────────────────────────────────


@pytest.mark.parametrize("method,path", [
    ("get", "/ping"), ("get", f"/export?user_id={UID}"), ("post", f"/import?user_id={UID}"),
    ("get", f"/summary?user_id={UID}"),
])
def test_internal_routes_404_when_inbound_token_unset(client, monkeypatch, method, path):
    monkeypatch.delenv("ACCOUNT_SYNC_INBOUND_TOKEN", raising=False)
    # Even with "Bearer " — which would match an empty expected token.
    resp = getattr(client, method)(INTERNAL + path, headers={"Authorization": "Bearer "})
    assert resp.status_code == 404


def test_internal_blank_token_is_unset(client, monkeypatch):
    monkeypatch.setenv("ACCOUNT_SYNC_INBOUND_TOKEN", "   \n")
    assert client.get(f"{INTERNAL}/ping", headers={"Authorization": "Bearer "}).status_code == 404


@pytest.mark.parametrize("headers", [
    {}, {"Authorization": f"Bearer {TOKEN}x"}, {"Authorization": TOKEN},
    {"Authorization": "Basic abc"},
])
@pytest.mark.parametrize("method,path", [
    ("get", "/ping"), ("get", f"/export?user_id={UID}"), ("post", f"/import?user_id={UID}"),
    ("get", f"/summary?user_id={UID}"),
])
def test_internal_routes_one_generic_401(client, inbound, method, path, headers):
    resp = getattr(client, method)(INTERNAL + path, headers=headers)
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Unauthorized"


def test_unauthenticated_import_is_401_not_a_body_error(client, inbound):
    resp = client.post(f"{INTERNAL}/import", content=b"not json at all")
    assert resp.status_code == 401


def test_ping_reports_env(client, inbound, monkeypatch):
    monkeypatch.setattr(internal_sync.config, "APP_ENV", "staging")
    resp = client.get(f"{INTERNAL}/ping", headers=_auth())
    assert resp.status_code == 200 and resp.json() == {"env": "staging"}


def test_internal_routes_are_hidden_from_the_schema(client):
    assert not any(p.startswith(INTERNAL) for p in client.app.openapi()["paths"])


# ── internal: export / import ───────────────────────────────────────────────


def test_export_returns_bundle_and_audits(client, inbound, monkeypatch, events):
    bundle = {"version": 1, "user_id": UID, "tables": {"notes": [{"id": "n"}]}}
    monkeypatch.setattr(account_bundle, "export_account", lambda uid: bundle)

    resp = client.get(f"{INTERNAL}/export", params={"user_id": UID}, headers=_auth())

    assert resp.status_code == 200 and resp.json() == bundle
    # Never attributed to the student (that would count them active in
    # canopy_metrics / admin DAU): no user_id, the account in the payload.
    assert events == [("account.export", {
        "category": "audit", "user_id": None,
        "payload": {"target_user_id": UID, "tables": {"notes": 1}},
    })]


def test_export_unknown_account(client, inbound, monkeypatch, events):
    def missing(uid):
        raise AccountNotFound(uid)
    monkeypatch.setattr(account_bundle, "export_account", missing)

    resp = client.get(f"{INTERNAL}/export", params={"user_id": UID}, headers=_auth())
    assert resp.status_code == 404
    assert resp.json()["detail"] == account_sync_client.ACCOUNT_NOT_FOUND
    assert events == []


def test_export_requires_user_id(client, inbound):
    assert client.get(f"{INTERNAL}/export", headers=_auth()).status_code == 400


def test_import_applies_bundle_and_audits(client, inbound, monkeypatch, events):
    got = {}

    def fake_import(uid, bundle):
        got.update(uid=uid, bundle=bundle)
        return {"notes": 2}
    monkeypatch.setattr(account_bundle, "import_account", fake_import)
    bundle = {"version": 1, "user_id": UID, "source_env": "staging", "tables": {}}

    resp = client.post(f"{INTERNAL}/import", params={"user_id": UID}, json=bundle, headers=_auth())

    assert resp.status_code == 200 and resp.json() == {"counts": {"notes": 2}}
    assert got == {"uid": UID, "bundle": bundle}
    assert events[0][0] == "account.import"
    assert events[0][1]["user_id"] is None and events[0][1]["category"] == "audit"
    assert events[0][1]["payload"]["target_user_id"] == UID
    assert events[0][1]["payload"]["source_env"] == "staging"


@pytest.mark.parametrize("exc,status", [
    (AccountNotFound(UID), 404), (BundleError("bundle version 2 is not 1"), 400),
    (AccountWipeIncomplete("withdrawal failed"), 503),
])
def test_import_error_mapping(client, inbound, monkeypatch, exc, status):
    def boom(uid, bundle):
        raise exc
    monkeypatch.setattr(account_bundle, "import_account", boom)
    resp = client.post(f"{INTERNAL}/import", params={"user_id": UID}, json={}, headers=_auth())
    assert resp.status_code == status


def test_import_busy_is_409(client, inbound, monkeypatch):
    monkeypatch.setattr(account_bundle, "import_account", lambda uid, b: pytest.fail("ran"))
    with account_op(UID):
        resp = client.post(f"{INTERNAL}/import", params={"user_id": UID}, json={}, headers=_auth())
    assert resp.status_code == 409


def test_import_rejects_non_object_body(client, inbound):
    resp = client.post(f"{INTERNAL}/import", params={"user_id": UID}, json=[1], headers=_auth())
    assert resp.status_code == 400


# ── admin copy ──────────────────────────────────────────────────────────────


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("ACCOUNT_SYNC_PEER_URL", PEER + "/")
    monkeypatch.setenv("ACCOUNT_SYNC_PEER_TOKEN", PEER_TOKEN)
    monkeypatch.setattr(account_sync_client.config, "APP_ENV", "staging")
    monkeypatch.setattr(account_bundle, "account_exists", lambda uid: True)
    # conftest's session stub would name the PATH's user_id as the actor.
    monkeypatch.setattr(admin_sync, "get_session_user_id", lambda request, **kw: "admin_1")


@pytest.fixture
def audits(monkeypatch):
    seen = []
    monkeypatch.setattr(admin_sync, "log_admin_action", lambda *a: seen.append(a))
    return seen


class Peer:
    """Stand-in for the other deploy, at httpx's module-level get/post."""

    def __init__(self, monkeypatch, *, env="production", get=None, post=None):
        self.calls: list[tuple] = []
        self.env, self._get, self._post = env, get, post
        monkeypatch.setattr(account_sync_client.httpx, "get", self.get)
        monkeypatch.setattr(account_sync_client.httpx, "post", self.post)

    def _resp(self, method, url, status, body):
        return httpx.Response(status, json=body, request=httpx.Request(method, url))

    def get(self, url, *, headers=None, params=None, timeout=None):
        self.calls.append(("GET", url, headers, params))
        if url.endswith("/ping"):
            if isinstance(self.env, Exception):
                raise self.env
            return self._resp("GET", url, 200, {"env": self.env})
        return self._resp("GET", url, *self._get)

    def post(self, url, *, params=None, json=None, headers=None, timeout=None):
        self.calls.append(("POST", url, headers, params))
        return self._resp("POST", url, *self._post)


def _copy(client, direction="push", confirm="COPY"):
    return client.post(f"{ADMIN}/{UID}/copy", json={"direction": direction, "confirm": confirm})


def test_copy_is_admin_only(client, configured, monkeypatch):
    def deny(request):
        raise HTTPException(status_code=403, detail="Admin access required")
    monkeypatch.setattr(admin_sync, "require_admin", deny)
    monkeypatch.setattr(account_sync_client, "push", lambda uid: pytest.fail("pushed"))

    # 403 even for a malformed body: admin is checked before the body is read.
    assert _copy(client).status_code == 403
    assert client.post(f"{ADMIN}/{UID}/copy", json=["junk"]).status_code == 403


@pytest.mark.parametrize("body", [
    {"direction": "push", "confirm": "copy"},
    {"direction": "push"},
    {"direction": "sideways", "confirm": "COPY"},
    None,
])
def test_copy_bad_body_400(client, configured, body):
    assert client.post(f"{ADMIN}/{UID}/copy", json=body).status_code == 400


def test_copy_not_configured_503(client, monkeypatch):
    monkeypatch.delenv("ACCOUNT_SYNC_PEER_URL", raising=False)
    monkeypatch.setenv("ACCOUNT_SYNC_PEER_TOKEN", PEER_TOKEN)
    assert _copy(client).status_code == 503


def test_copy_unknown_local_account_404(client, configured, monkeypatch):
    monkeypatch.setattr(account_bundle, "account_exists", lambda uid: False)
    resp = _copy(client)
    assert resp.status_code == 404 and "staging" in resp.json()["detail"]


def test_self_copy_refused_409(client, configured, monkeypatch):
    peer = Peer(monkeypatch, env="staging")
    monkeypatch.setattr(account_bundle, "export_account", lambda uid: pytest.fail("exported"))
    resp = _copy(client)
    assert resp.status_code == 409 and "self-copy" in resp.json()["detail"]
    assert [c[0] for c in peer.calls] == ["GET"]  # only the ping


def test_unreachable_peer_502(client, configured, monkeypatch):
    Peer(monkeypatch, env=httpx.ConnectError("nope"))
    assert _copy(client).status_code == 502


def test_push_success(client, configured, monkeypatch, audits, events):
    peer = Peer(monkeypatch, post=(200, {"counts": {"notes": 3}}))
    monkeypatch.setattr(account_bundle, "export_account", lambda uid: {"user_id": uid})

    resp = _copy(client, "push")

    assert resp.status_code == 200
    assert resp.json() == {"direction": "push", "peer_env": "production", "counts": {"notes": 3}}
    method, url, headers, params = peer.calls[-1]
    assert (method, url) == ("POST", f"{PEER}/api/internal/account-sync/import")
    assert headers == {"Authorization": f"Bearer {PEER_TOKEN}"} and params == {"user_id": UID}
    assert audits == [("admin_1", "account.copy_push", "user", UID,
                       {"outcome": "ok", "peer_env": "production", "counts": {"notes": 3}})]
    assert events[0][0] == "account.copy_push" and events[0][1]["category"] == "audit"


def test_push_peer_unknown_account_maps_to_404(client, configured, monkeypatch, audits):
    Peer(monkeypatch, post=(404, {"detail": account_sync_client.ACCOUNT_NOT_FOUND}))
    monkeypatch.setattr(account_bundle, "export_account", lambda uid: {})
    resp = _copy(client, "push")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "account must sign in on production first"
    assert audits[0][1] == "account.copy_push" and audits[0][4]["outcome"] == "failed"


def test_bare_peer_404_is_a_peer_error_not_unknown_account(client, configured, monkeypatch):
    # A peer with its inbound token unset (or an old deploy) 404s every path.
    Peer(monkeypatch, post=(404, {"detail": "Not Found"}))
    monkeypatch.setattr(account_bundle, "export_account", lambda uid: {})
    assert _copy(client, "push").status_code == 502


def test_peer_500_is_502(client, configured, monkeypatch):
    Peer(monkeypatch, post=(500, {"detail": "boom"}))
    monkeypatch.setattr(account_bundle, "export_account", lambda uid: {})
    assert _copy(client, "push").status_code == 502


def test_peer_bundle_error_400_surfaces_as_400_with_detail(client, configured, monkeypatch,
                                                           audits):
    # The peer's BundleError, e.g. its schema lacks a column ("migrate it first").
    detail = "production's notes table cannot take this bundle's columns (migrate it first): x"
    Peer(monkeypatch, post=(400, {"detail": detail}))
    monkeypatch.setattr(account_bundle, "export_account", lambda uid: {})
    resp = _copy(client, "push")
    assert resp.status_code == 400
    assert "migrate it first" in resp.json()["detail"]
    assert resp.json()["detail"].startswith("production: ")
    assert audits[0][4] == {"outcome": "failed", "status": 400}


def test_pull_peer_export_400_surfaces_as_400(client, configured, monkeypatch):
    # The peer could not export honestly (e.g. a row under another key).
    Peer(monkeypatch, get=(400, {"detail": "notes.body (row n): ciphertext does not decrypt"}))
    monkeypatch.setattr(account_bundle, "import_account", lambda uid, b: pytest.fail("imported"))
    resp = _copy(client, "pull")
    assert resp.status_code == 400 and "does not decrypt" in resp.json()["detail"]


def test_copy_unexpected_error_is_audited_and_reraised(client, configured, monkeypatch, audits,
                                                       events):
    Peer(monkeypatch, get=(200, {"version": 1}))

    def boom(uid, b):
        raise RuntimeError("PostgREST 500 mid-import")
    monkeypatch.setattr(account_bundle, "import_account", boom)

    with pytest.raises(RuntimeError):
        _copy(client, "pull")
    assert audits == [("admin_1", "account.copy_pull", "user", UID,
                       {"outcome": "failed", "status": 500})]
    assert events[0][1]["payload"]["outcome"] == "failed"
    from services.account_ops_lock import is_busy
    assert not is_busy(UID)


def test_peer_busy_is_409(client, configured, monkeypatch):
    Peer(monkeypatch, post=(409, {"detail": "operation already running for this account"}))
    monkeypatch.setattr(account_bundle, "export_account", lambda uid: {})
    assert _copy(client, "push").status_code == 409


def test_pull_success_imports_locally(client, configured, monkeypatch, audits):
    remote = {"version": 1, "user_id": UID, "tables": {}}
    peer = Peer(monkeypatch, get=(200, remote))
    got = {}
    monkeypatch.setattr(account_bundle, "import_account",
                        lambda uid, b: got.update(uid=uid, b=b) or {"notes": 1})

    resp = _copy(client, "pull")

    assert resp.status_code == 200
    assert resp.json() == {"direction": "pull", "peer_env": "production", "counts": {"notes": 1}}
    assert got == {"uid": UID, "b": remote}
    assert peer.calls[-1][1] == f"{PEER}/api/internal/account-sync/export"
    assert audits[0][1] == "account.copy_pull"


def test_pull_peer_unknown_account_404(client, configured, monkeypatch):
    Peer(monkeypatch, get=(404, {"detail": account_sync_client.ACCOUNT_NOT_FOUND}))
    resp = _copy(client, "pull")
    assert resp.status_code == 404 and "production" in resp.json()["detail"]


def test_pull_bundle_error_is_400(client, configured, monkeypatch, audits):
    Peer(monkeypatch, get=(200, {"version": 2}))

    def refuse(uid, b):
        raise BundleError("bundle version 2 is not 1")
    monkeypatch.setattr(account_bundle, "import_account", refuse)
    resp = _copy(client, "pull")
    assert resp.status_code == 400 and "version" in resp.json()["detail"]


def test_pull_wipe_incomplete_is_503_and_audited(client, configured, monkeypatch, audits):
    Peer(monkeypatch, get=(200, {"version": 1}))

    def stuck(uid, b):
        raise AccountWipeIncomplete("withdrawal failed")
    monkeypatch.setattr(account_bundle, "import_account", stuck)
    assert _copy(client, "pull").status_code == 503
    assert audits[0][4] == {"outcome": "failed", "status": 503}


def test_copy_busy_409(client, configured, monkeypatch):
    monkeypatch.setattr(account_sync_client, "push", lambda uid: pytest.fail("pushed"))
    with account_op(UID):
        assert _copy(client).status_code == 409


# ── client: peer_status ─────────────────────────────────────────────────────


def test_peer_status_not_configured(monkeypatch):
    monkeypatch.delenv("ACCOUNT_SYNC_PEER_URL", raising=False)
    monkeypatch.delenv("ACCOUNT_SYNC_PEER_TOKEN", raising=False)
    assert account_sync_client.peer_status() == {"configured": False, "peer_env": None}


def test_peer_status_url_without_token_is_not_configured(monkeypatch):
    monkeypatch.setenv("ACCOUNT_SYNC_PEER_URL", PEER)
    monkeypatch.delenv("ACCOUNT_SYNC_PEER_TOKEN", raising=False)
    assert account_sync_client.peer_status() == {"configured": False, "peer_env": None}


def test_peer_status_reachable(configured, monkeypatch):
    peer = Peer(monkeypatch)
    assert account_sync_client.peer_status() == {"configured": True, "peer_env": "production"}
    # Trailing slash on the configured URL is stripped.
    assert peer.calls[0][1] == f"{PEER}/api/internal/account-sync/ping"


@pytest.mark.parametrize("failure", [httpx.ConnectTimeout("slow"), RuntimeError("weird")])
def test_peer_status_never_raises(configured, monkeypatch, failure):
    Peer(monkeypatch, env=failure)
    assert account_sync_client.peer_status() == {"configured": True, "peer_env": None}


def test_peer_status_on_401(configured, monkeypatch):
    def unauthorized(url, **kw):
        return httpx.Response(401, json={"detail": "Unauthorized"}, request=httpx.Request("GET", url))
    monkeypatch.setattr(account_sync_client.httpx, "get", unauthorized)
    assert account_sync_client.peer_status() == {"configured": True, "peer_env": None}


# ── review step: internal summary, peer_summary, copy-preview ───────────────

SUMMARY = {
    "exists": True,
    "courses": [{"code": "CAS CS 111", "name": "Intro to CS 1", "term_id": "fall-2026"}],
    "counts": {"enrollments": 1, "notes": 2},
    "total_xp": 120,
    "empty": False,
}


def test_internal_summary_returns_counts_without_audit(client, inbound, monkeypatch, events):
    monkeypatch.setattr(internal_sync, "summarize_account", lambda uid: dict(SUMMARY))
    resp = client.get(f"{INTERNAL}/summary", params={"user_id": UID}, headers=_auth())
    assert resp.status_code == 200 and resp.json() == SUMMARY
    assert events == []  # a read-only count is not an audited event


def test_internal_summary_unknown_account_is_account_not_found(client, inbound, monkeypatch):
    monkeypatch.setattr(internal_sync, "summarize_account",
                        lambda uid: account_summary.empty_summary())
    resp = client.get(f"{INTERNAL}/summary", params={"user_id": UID}, headers=_auth())
    assert resp.status_code == 404
    assert resp.json()["detail"] == account_sync_client.ACCOUNT_NOT_FOUND


def test_internal_summary_requires_user_id(client, inbound):
    assert client.get(f"{INTERNAL}/summary", headers=_auth()).status_code == 400


def test_internal_summary_is_not_refused_while_busy(client, inbound, monkeypatch):
    monkeypatch.setattr(internal_sync, "summarize_account", lambda uid: dict(SUMMARY))
    with account_op(UID):
        resp = client.get(f"{INTERNAL}/summary", params={"user_id": UID}, headers=_auth())
    assert resp.status_code == 200


def test_peer_summary_success(configured, monkeypatch):
    peer = Peer(monkeypatch, get=(200, SUMMARY))
    assert account_sync_client.peer_summary(UID) == {"env": "production", "summary": SUMMARY}
    method, url, headers, params = peer.calls[-1]
    assert url == f"{PEER}/api/internal/account-sync/summary"
    assert headers == {"Authorization": f"Bearer {PEER_TOKEN}"} and params == {"user_id": UID}


def test_peer_summary_unknown_account_is_an_answer_not_an_error(configured, monkeypatch):
    Peer(monkeypatch, get=(404, {"detail": account_sync_client.ACCOUNT_NOT_FOUND}))
    out = account_sync_client.peer_summary(UID)
    assert out["env"] == "production"
    assert out["summary"] == account_summary.empty_summary(exists=False)


@pytest.mark.parametrize("status,body,expected", [
    (404, {"detail": "Not Found"}, 502),  # an old peer without the route
    (500, {"detail": "boom"}, 502),
    (200, ["not", "a", "summary"], 502),
    (200, {"counts": {}}, 502),  # no `exists`
])
def test_peer_summary_failures(configured, monkeypatch, status, body, expected):
    Peer(monkeypatch, get=(status, body))
    with pytest.raises(account_sync_client.PeerError) as exc:
        account_sync_client.peer_summary(UID)
    assert exc.value.status == expected


def test_peer_summary_self_and_unreachable(configured, monkeypatch):
    Peer(monkeypatch, env="staging")
    with pytest.raises(account_sync_client.PeerError) as exc:
        account_sync_client.peer_summary(UID)
    assert exc.value.status == 409
    Peer(monkeypatch, env=httpx.ConnectError("nope"))
    with pytest.raises(account_sync_client.PeerError) as exc:
        account_sync_client.peer_summary(UID)
    assert exc.value.status == 502


def test_peer_summary_not_configured(monkeypatch):
    monkeypatch.delenv("ACCOUNT_SYNC_PEER_URL", raising=False)
    with pytest.raises(account_sync_client.PeerError) as exc:
        account_sync_client.peer_summary(UID)
    assert exc.value.status == 503


LOCAL = {**SUMMARY, "counts": {"enrollments": 4, "notes": 8}, "total_xp": 900}


def _preview(client, direction="push"):
    return client.get(f"{ADMIN}/{UID}/copy-preview", params={"direction": direction})


@pytest.fixture
def local_summary(monkeypatch):
    monkeypatch.setattr(admin_sync, "summarize_account", lambda uid: dict(LOCAL))


def test_copy_preview_is_admin_only(client, configured, local_summary, monkeypatch):
    def deny(request):
        raise HTTPException(status_code=403, detail="Admin access required")
    monkeypatch.setattr(admin_sync, "require_admin", deny)
    assert _preview(client).status_code == 403
    # Even a bad direction: admin is checked first.
    assert _preview(client, "sideways").status_code == 403


def test_copy_preview_push_sources_here(client, configured, local_summary, monkeypatch, audits,
                                        events):
    Peer(monkeypatch, get=(200, SUMMARY))
    monkeypatch.setattr(account_sync_client, "push", lambda uid: pytest.fail("pushed"))
    resp = _preview(client, "push")
    assert resp.status_code == 200
    assert resp.json() == {
        "direction": "push",
        "source": {"env": "staging", "summary": LOCAL},
        "destination": {"env": "production", "summary": SUMMARY},
    }
    assert audits == [] and events == []  # a preview changes and audits nothing


def test_copy_preview_pull_sources_the_peer(client, configured, local_summary, monkeypatch):
    Peer(monkeypatch, get=(200, SUMMARY))
    monkeypatch.setattr(account_bundle, "import_account", lambda uid, b: pytest.fail("imported"))
    body = _preview(client, "pull").json()
    assert body["source"] == {"env": "production", "summary": SUMMARY}
    assert body["destination"] == {"env": "staging", "summary": LOCAL}


def test_copy_preview_peer_without_the_account(client, configured, local_summary, monkeypatch):
    Peer(monkeypatch, get=(404, {"detail": account_sync_client.ACCOUNT_NOT_FOUND}))
    resp = _preview(client, "push")
    assert resp.status_code == 200
    assert resp.json()["destination"]["summary"]["exists"] is False


@pytest.mark.parametrize("direction", [None, "", "sideways"])
def test_copy_preview_bad_direction_400(client, configured, local_summary, direction):
    params = {} if direction is None else {"direction": direction}
    assert client.get(f"{ADMIN}/{UID}/copy-preview", params=params).status_code == 400


def test_copy_preview_not_configured_503(client, local_summary, monkeypatch):
    monkeypatch.delenv("ACCOUNT_SYNC_PEER_URL", raising=False)
    assert _preview(client).status_code == 503


def test_copy_preview_unknown_local_account_404(client, configured, monkeypatch):
    monkeypatch.setattr(admin_sync, "summarize_account",
                        lambda uid: account_summary.empty_summary())
    resp = _preview(client)
    assert resp.status_code == 404 and "staging" in resp.json()["detail"]


@pytest.mark.parametrize("peer_kw,status", [
    ({"env": "staging"}, 409),
    ({"env": httpx.ConnectError("nope")}, 502),
    ({"get": (500, {"detail": "boom"})}, 502),
])
def test_copy_preview_peer_errors(client, configured, local_summary, monkeypatch, peer_kw,
                                  status):
    Peer(monkeypatch, **peer_kw)
    assert _preview(client).status_code == status
