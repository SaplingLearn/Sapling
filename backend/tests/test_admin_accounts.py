"""/api/admin/accounts — admin account tools (seed / wipe / meta).

The router is mounted on a bare app here so these tests don't depend on
main.py's mount. The seeder, wipe and peer client are faked (the per-user lock is the real one): their own
behaviour is covered by their own suites.
"""
from __future__ import annotations

import sys
import types

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import routes.admin_accounts as admin_accounts
from services.account_ops_lock import account_op
from services.account_seed import seeder
from tests.test_account_seeder import PACK

BASE = "/api/admin/accounts"
USER = "user_target"
ADMIN = "user_admin"


@pytest.fixture
def state(monkeypatch):
    app = FastAPI()
    app.include_router(admin_accounts.router, prefix=BASE)
    st = types.SimpleNamespace(
        client=TestClient(app),
        audits=[], events=[], seeds=[], wipes=[],
        users={USER},
    )

    class _Users:
        def select(self, columns="*", filters=None, **_):
            uid = (filters or {}).get("id", "").removeprefix("eq.")
            return [{"id": uid}] if uid in st.users else []

    monkeypatch.setattr(admin_accounts, "table", lambda name: _Users())
    monkeypatch.setattr(admin_accounts, "require_admin", lambda request: None)
    monkeypatch.setattr(admin_accounts, "get_session_user_id", lambda request, **_: ADMIN)
    monkeypatch.setattr(admin_accounts, "log_admin_action",
                        lambda **kw: st.audits.append(kw))
    monkeypatch.setattr(admin_accounts, "log_event",
                        lambda event_type, **kw: st.events.append((event_type, kw)))
    monkeypatch.setattr(seeder, "packs", lambda: {PACK.key: PACK})

    def fake_seed(user_id, major, **_):
        st.seeds.append((user_id, major))
        return {"major": major, "wiped": {"notes": 2}, "created": {"notes": 8, "documents": 8}}

    monkeypatch.setattr(seeder, "seed_account", fake_seed)

    def wipe_account_data(user_id):
        st.wipes.append(user_id)
        return {"notes": 2, "documents": 1}

    monkeypatch.setattr(admin_accounts, "wipe_account_data", wipe_account_data)
    monkeypatch.setitem(sys.modules, "services.account_sync_client", types.SimpleNamespace(
        peer_status=lambda: {"configured": True, "peer_env": "production"},
    ))
    return st


def _deny(request):
    raise HTTPException(status_code=403, detail="Admin access required")


# ── gating ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("method,path,body", [
    ("get", f"{BASE}/meta", None),
    ("post", f"{BASE}/{USER}/seed", {"major": PACK.key, "confirm": "SEED"}),
    ("post", f"{BASE}/{USER}/wipe", {"confirm": "WIPE"}),
])
def test_every_endpoint_is_admin_only(state, monkeypatch, method, path, body):
    monkeypatch.setattr(admin_accounts, "require_admin", _deny)
    kw = {"json": body} if body is not None else {}
    assert getattr(state.client, method)(path, **kw).status_code == 403
    assert state.seeds == [] and state.wipes == [] and state.audits == []


# ── /meta ────────────────────────────────────────────────────────────────────


def test_meta_shape(state, monkeypatch):
    monkeypatch.setattr(admin_accounts.config, "APP_ENV", "staging")
    body = state.client.get(f"{BASE}/meta").json()
    assert body["env"] == "staging"
    assert body["sync"] == {"configured": True, "peer_env": "production"}
    [major] = body["majors"]
    assert major["key"] == PACK.key and major["label"] == PACK.label
    assert major["courses"] == [{"code": c.code, "name": c.name} for c in PACK.courses]


def test_meta_without_a_sync_client_reports_unconfigured(state, monkeypatch):
    monkeypatch.setitem(sys.modules, "services.account_sync_client", None)  # ImportError
    body = state.client.get(f"{BASE}/meta").json()
    assert body["sync"] == {"configured": False, "peer_env": None}


def test_meta_survives_a_broken_peer_probe(state, monkeypatch):
    def boom():
        raise RuntimeError("peer down")

    monkeypatch.setitem(sys.modules, "services.account_sync_client",
                        types.SimpleNamespace(peer_status=boom))
    body = state.client.get(f"{BASE}/meta").json()
    assert body["sync"] == {"configured": False, "peer_env": None}


# ── seed ─────────────────────────────────────────────────────────────────────


def test_seed_runs_and_audits(state):
    r = state.client.post(f"{BASE}/{USER}/seed", json={"major": PACK.key, "confirm": "SEED"})
    assert r.status_code == 200
    assert r.json() == {"major": PACK.key, "wiped": {"notes": 2},
                        "created": {"notes": 8, "documents": 8}}
    assert state.seeds == [(USER, PACK.key)]
    [audit] = state.audits
    assert audit["actor_id"] == ADMIN and audit["action"] == "account.seed"
    assert audit["target_type"] == "user" and audit["target_id"] == USER
    assert audit["payload"]["major"] == PACK.key
    assert audit["payload"]["created"] == {"notes": 8, "documents": 8}
    [(event_type, kw)] = state.events
    assert event_type == "account.seed" and kw["category"] == "audit"
    assert kw["user_id"] == ADMIN
    assert kw["payload"]["target_user_id"] == USER


@pytest.mark.parametrize("body", [
    {"major": PACK.key, "confirm": "seed"},
    {"major": PACK.key, "confirm": "WIPE"},
    {"major": PACK.key},
])
def test_seed_requires_the_literal_confirm(state, body):
    r = state.client.post(f"{BASE}/{USER}/seed", json=body)
    assert r.status_code == 400
    assert state.seeds == [] and state.audits == []


@pytest.mark.parametrize("body", [
    {"major": "astrology", "confirm": "SEED"},
    {"confirm": "SEED"},
])
def test_seed_rejects_an_unknown_major(state, body):
    r = state.client.post(f"{BASE}/{USER}/seed", json=body)
    assert r.status_code == 400
    assert state.seeds == []


def test_seed_unknown_user_is_404(state):
    r = state.client.post(f"{BASE}/user_nobody/seed",
                          json={"major": PACK.key, "confirm": "SEED"})
    assert r.status_code == 404
    assert state.seeds == [] and state.audits == []


def test_seed_while_busy_is_409(state):
    with account_op(USER):  # the real per-user lock, held by "another request"
        r = state.client.post(f"{BASE}/{USER}/seed",
                              json={"major": PACK.key, "confirm": "SEED"})
    assert r.status_code == 409
    assert state.seeds == [] and state.audits == []


def test_seed_releases_the_lock(state):
    for _ in range(2):
        r = state.client.post(f"{BASE}/{USER}/seed",
                              json={"major": PACK.key, "confirm": "SEED"})
        assert r.status_code == 200
    from services.account_ops_lock import is_busy

    assert not is_busy(USER)


def test_seed_user_vanishing_mid_request_is_404(state, monkeypatch):
    def gone(user_id, major, **_):
        raise LookupError(user_id)

    monkeypatch.setattr(seeder, "seed_account", gone)
    r = state.client.post(f"{BASE}/{USER}/seed", json={"major": PACK.key, "confirm": "SEED"})
    assert r.status_code == 404
    assert state.audits == []


# ── wipe ─────────────────────────────────────────────────────────────────────


def test_wipe_runs_and_audits(state):
    r = state.client.post(f"{BASE}/{USER}/wipe", json={"confirm": "WIPE"})
    assert r.status_code == 200
    assert r.json() == {"wiped": {"notes": 2, "documents": 1}}
    assert state.wipes == [USER]
    [audit] = state.audits
    assert audit["action"] == "account.wipe" and audit["target_id"] == USER
    assert audit["payload"] == {"wiped": {"notes": 2, "documents": 1}}
    [(event_type, kw)] = state.events
    assert event_type == "account.wipe" and kw["category"] == "audit"


@pytest.mark.parametrize("body", [{"confirm": "SEED"}, {"confirm": "wipe"}, {}])
def test_wipe_requires_the_literal_confirm(state, body):
    r = state.client.post(f"{BASE}/{USER}/wipe", json=body)
    assert r.status_code == 400
    assert state.wipes == []


def test_wipe_unknown_user_is_404(state):
    r = state.client.post(f"{BASE}/user_nobody/wipe", json={"confirm": "WIPE"})
    assert r.status_code == 404
    assert state.wipes == []


def test_wipe_while_busy_is_409(state):
    with account_op(USER):
        r = state.client.post(f"{BASE}/{USER}/wipe", json={"confirm": "WIPE"})
    assert r.status_code == 409
    assert state.wipes == [] and state.audits == []
