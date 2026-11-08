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
from services.account_ops_lock import account_op, is_busy
from services.account_seed import seeder
from services.account_wipe import AccountWipeIncomplete
from tests.test_account_seeder import PACK

BASE = "/api/admin/accounts"
USER = "user_target"
ADMIN = "user_admin"


SUMMARY = {
    "courses": [{"code": "CAS CS 111", "name": "Intro to CS 1", "term_id": "fall-2026"}],
    "counts": {"enrollments": 1, "notes": 2},
    "total_xp": 120,
    "empty": False,
}


@pytest.fixture
def state(monkeypatch):
    app = FastAPI()
    app.include_router(admin_accounts.router, prefix=BASE)
    st = types.SimpleNamespace(
        client=TestClient(app),
        audits=[], events=[], seeds=[], wipes=[],
        users={USER},
    )

    monkeypatch.setattr(admin_accounts, "account_exists", lambda uid: uid in st.users)
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
    monkeypatch.setattr(admin_accounts, "summarize_account", lambda uid: (
        {**SUMMARY, "exists": True} if uid in st.users else {**SUMMARY, "exists": False}
    ))
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
    ("get", f"{BASE}/{USER}/summary", None),
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


def test_soft_deleted_account_is_404_via_account_exists(state, monkeypatch):
    # account_exists (account_bundle's, which filters deleted_at) says no.
    seen = []

    def exists(uid):
        seen.append(uid)
        return False

    monkeypatch.setattr(admin_accounts, "account_exists", exists)
    for path, body in ((f"{BASE}/{USER}/seed", {"major": PACK.key, "confirm": "SEED"}),
                       (f"{BASE}/{USER}/wipe", {"confirm": "WIPE"})):
        assert state.client.post(path, json=body).status_code == 404
    assert seen == [USER, USER]
    assert state.seeds == [] and state.wipes == []


def test_route_uses_the_deleted_at_aware_lookup():
    from services import account_bundle

    assert admin_accounts.account_exists is account_bundle.account_exists
    assert seeder.account_exists is account_bundle.account_exists


def test_seed_user_vanishing_mid_request_is_404_and_audited(state, monkeypatch):
    def gone(user_id, major, **_):
        raise seeder.UnknownAccount(user_id)

    monkeypatch.setattr(seeder, "seed_account", gone)
    r = state.client.post(f"{BASE}/{USER}/seed", json={"major": PACK.key, "confirm": "SEED"})
    assert r.status_code == 404
    [audit] = state.audits
    assert audit["payload"] == {"outcome": "failed", "reason": "user_not_found",
                                "major": PACK.key}


def test_seed_no_current_term_is_503_audited(state, monkeypatch):
    def no_term(user_id, major, **_):
        raise seeder.NoCurrentTerm("no current term")

    monkeypatch.setattr(seeder, "seed_account", no_term)
    r = state.client.post(f"{BASE}/{USER}/seed", json={"major": PACK.key, "confirm": "SEED"})
    assert r.status_code == 503
    assert "term" in r.json()["detail"]
    [audit] = state.audits
    assert audit["action"] == "account.seed"
    assert audit["payload"]["outcome"] == "failed"
    assert audit["payload"]["reason"] == "no_current_term"


def test_seed_wipe_incomplete_is_503_and_audited(state, monkeypatch):
    def stuck(user_id, major, **_):
        raise AccountWipeIncomplete("withdrawal failed for doc-secret-name")

    monkeypatch.setattr(seeder, "seed_account", stuck)
    r = state.client.post(f"{BASE}/{USER}/seed", json={"major": PACK.key, "confirm": "SEED"})
    assert r.status_code == 503
    assert r.json()["detail"] == "wipe incomplete — re-run"
    [audit] = state.audits
    assert audit["payload"] == {"outcome": "failed", "reason": "wipe_incomplete",
                                "major": PACK.key}
    [(event_type, kw)] = state.events
    assert event_type == "account.seed" and kw["payload"]["outcome"] == "failed"
    # ids/enums only: the exception text never reaches the audit trail.
    assert "doc-secret-name" not in repr(state.audits) + repr(state.events)
    assert not is_busy(USER)


def test_seed_unexpected_error_is_audited_and_reraised(state, monkeypatch):
    def boom(user_id, major, **_):
        raise KeyError("Idea A1")  # a LookupError that must NOT become a 404

    monkeypatch.setattr(seeder, "seed_account", boom)
    client = TestClient(state.client.app, raise_server_exceptions=False)
    r = client.post(f"{BASE}/{USER}/seed", json={"major": PACK.key, "confirm": "SEED"})
    assert r.status_code == 500
    [audit] = state.audits
    assert audit["payload"] == {"outcome": "failed", "reason": "error", "major": PACK.key}
    assert not is_busy(USER)


# ── wipe ─────────────────────────────────────────────────────────────────────


def test_wipe_runs_and_audits(state):
    r = state.client.post(f"{BASE}/{USER}/wipe", json={"confirm": "WIPE"})
    assert r.status_code == 200
    assert r.json() == {"wiped": {"notes": 2, "documents": 1}}
    assert state.wipes == [USER]
    [audit] = state.audits
    assert audit["action"] == "account.wipe" and audit["target_id"] == USER
    assert audit["payload"] == {"outcome": "ok", "wiped": {"notes": 2, "documents": 1}}
    [(event_type, kw)] = state.events
    assert event_type == "account.wipe" and kw["category"] == "audit"
    assert kw["payload"]["outcome"] == "ok"


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


def test_wipe_incomplete_is_503_and_audited(state, monkeypatch):
    def stuck(user_id):
        raise AccountWipeIncomplete("chunk withdrawal failed")

    monkeypatch.setattr(admin_accounts, "wipe_account_data", stuck)
    r = state.client.post(f"{BASE}/{USER}/wipe", json={"confirm": "WIPE"})
    assert r.status_code == 503 and r.json()["detail"] == "wipe incomplete — re-run"
    [audit] = state.audits
    assert audit["action"] == "account.wipe"
    assert audit["payload"] == {"outcome": "failed", "reason": "wipe_incomplete"}
    [(event_type, kw)] = state.events
    assert kw["payload"] == {"target_user_id": USER, "outcome": "failed",
                             "reason": "wipe_incomplete"}
    assert not is_busy(USER)


def test_wipe_unexpected_error_is_audited_and_reraised(state, monkeypatch):
    def boom(user_id):
        raise RuntimeError("postgrest 500")

    monkeypatch.setattr(admin_accounts, "wipe_account_data", boom)
    with pytest.raises(RuntimeError):
        state.client.post(f"{BASE}/{USER}/wipe", json={"confirm": "WIPE"})
    [audit] = state.audits
    assert audit["payload"] == {"outcome": "failed", "reason": "error"}
    assert not is_busy(USER)


# ── summary (the review step) ────────────────────────────────────────────────


def test_summary_returns_the_account_summary(state):
    r = state.client.get(f"{BASE}/{USER}/summary")
    assert r.status_code == 200
    assert r.json() == {**SUMMARY, "exists": True}
    # Read-only: nothing ran, nothing audited, no lock left behind.
    assert state.seeds == [] and state.wipes == []
    assert state.audits == [] and state.events == []


def test_summary_unknown_or_soft_deleted_is_404(state):
    r = state.client.get(f"{BASE}/user_nobody/summary")
    assert r.status_code == 404


def test_summary_is_not_refused_while_an_operation_runs(state):
    with account_op(USER):
        assert state.client.get(f"{BASE}/{USER}/summary").status_code == 200
