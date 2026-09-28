"""#620 admin flags API: auth, validation, audit + event, cache clear."""
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)
ADMIN = "admin_1"


class _DB:
    """In-memory feature_flags / feature_flag_targets / users / roles."""

    def __init__(self):
        self.flags: dict[str, dict] = {}
        self.targets: dict[tuple, dict] = {}
        self.users = {"u1"}
        self.roles = {"r-admin": {"id": "r-admin", "name": "Admin", "display_priority": 100}}

    def table(self, name):
        db = self
        m = MagicMock()
        if name == "feature_flags":
            m.select.side_effect = lambda *a, **k: (
                [] if k.get("offset") else
                [dict(v) for v in db.flags.values()
                 if not (k.get("filters") or {}).get("key")
                 or v["key"] == k["filters"]["key"].removeprefix("eq.")])

            def upsert(row, on_conflict="id", ignore_duplicates=False):
                if ignore_duplicates and row["key"] in db.flags:
                    return []
                cur = db.flags.get(row["key"], {"rollout_percent": 0, "rollout_variant": None,
                                               "updated_at": None, "updated_by": None})
                db.flags[row["key"]] = {**cur, **row}
                return [db.flags[row["key"]]]
            m.upsert.side_effect = upsert
        elif name == "feature_flag_targets":
            m.select.side_effect = lambda *a, **k: [] if k.get("offset") else [dict(v) for v in db.targets.values()]
            m.upsert.side_effect = lambda row, **k: db.targets.__setitem__(
                (row["flag_key"], row["target_type"], row["target_id"]), row) or [row]

            def delete(filters):
                key = (filters["flag_key"].removeprefix("eq."), filters["target_type"].removeprefix("eq."),
                       filters["target_id"].removeprefix("eq."))
                return [db.targets.pop(key)] if key in db.targets else []
            m.delete.side_effect = delete
        elif name == "users":
            m.select.side_effect = lambda *a, **k: (
                [{"id": k["filters"]["id"].removeprefix("eq.")}]
                if k["filters"]["id"].removeprefix("eq.") in db.users else [])
        elif name == "roles":
            m.select.side_effect = lambda *a, **k: (
                [r for r in db.roles.values()
                 if not (k.get("filters") or {}).get("id") or r["id"] == k["filters"]["id"].removeprefix("eq.")])
        elif name == "user_roles":
            m.select.return_value = []
        return m


def _admin(db):
    return [
        patch("routes.admin_flags.require_admin", return_value=None),
        patch("routes.admin_flags.get_session_user_id", return_value=ADMIN),
        patch("routes.admin_flags.table", side_effect=db.table),
        patch("services.feature_flags.table", side_effect=db.table),
        patch("routes.admin_flags.get_display_names", return_value={"u1": "Student One"}),
        patch("routes.admin_flags.log_admin_action"),
        patch("routes.admin_flags.log_event"),
    ]


def _run(db, fn):
    ps = _admin(db)
    mocks = [p.start() for p in ps]
    try:
        return fn(), mocks
    finally:
        for p in ps:
            p.stop()


def test_non_admin_forbidden():
    with patch("routes.admin_flags.require_admin",
               side_effect=HTTPException(status_code=403, detail="Forbidden")):
        assert client.get("/api/admin/flags").status_code == 403


def test_list_includes_every_registered_flag():
    db = _DB()
    r, _ = _run(db, lambda: client.get("/api/admin/flags"))
    assert r.status_code == 200
    keys = {f["key"] for f in r.json()["flags"]}
    assert keys == {"decision_router", "learning_loop", "product_analytics"}
    ll = next(f for f in r.json()["flags"] if f["key"] == "learning_loop")
    assert ll["default_variant"] == "off" and ll["variants"] == ["off", "on"]


def test_patch_validates_and_audits():
    db = _DB()
    r, mocks = _run(db, lambda: client.patch("/api/admin/flags/learning_loop",
                                            json={"default_variant": "banana"}))
    assert r.status_code == 422 and "learning_loop" not in db.flags
    r, mocks = _run(db, lambda: client.patch("/api/admin/flags/learning_loop",
                                            json={"rollout_percent": 20}))
    assert r.status_code == 422  # rollout_variant required when percent > 0
    r, mocks = _run(db, lambda: client.patch("/api/admin/flags/learning_loop",
                                            json={"rollout_percent": 20, "rollout_variant": "on"}))
    assert r.status_code == 200
    assert db.flags["learning_loop"]["rollout_percent"] == 20
    assert db.flags["learning_loop"]["updated_by"] == ADMIN
    audit, event = mocks[5], mocks[6]
    assert audit.call_args.kwargs["action"] == "flag.update"
    assert event.call_args.args[0] == "flag.changed"
    assert event.call_args.kwargs["category"] == "audit"


def test_unknown_flag_404():
    db = _DB()
    r, _ = _run(db, lambda: client.patch("/api/admin/flags/nope", json={"default_variant": "on"}))
    assert r.status_code == 404


def test_target_upsert_requires_existing_user_and_valid_variant():
    db = _DB()
    r, _ = _run(db, lambda: client.put("/api/admin/flags/learning_loop/targets",
                                      json={"target_type": "user", "target_id": "ghost", "variant": "on"}))
    assert r.status_code == 404 and not db.targets
    r, _ = _run(db, lambda: client.put("/api/admin/flags/learning_loop/targets",
                                      json={"target_type": "user", "target_id": "u1", "variant": "maybe"}))
    assert r.status_code == 422 and not db.targets
    r, _ = _run(db, lambda: client.put("/api/admin/flags/learning_loop/targets",
                                      json={"target_type": "user", "target_id": "u1", "variant": "on"}))
    assert r.status_code == 200
    assert "learning_loop" in db.flags  # parent row created for the FK, default off
    assert db.flags["learning_loop"]["default_variant"] == "off"
    view = r.json()["flag"]
    assert view["targets"] == [{"target_type": "user", "target_id": "u1",
                                "label": "Student One", "variant": "on"}]


def test_target_delete_and_explain():
    db = _DB()
    _run(db, lambda: client.put("/api/admin/flags/learning_loop/targets",
                               json={"target_type": "role", "target_id": "r-admin", "variant": "on"}))
    r, _ = _run(db, lambda: client.get("/api/admin/flags/learning_loop/explain?user_id=u1"))
    assert r.json() == {"variant": "off", "step": "default", "detail": "stored default"}
    r, _ = _run(db, lambda: client.delete("/api/admin/flags/learning_loop/targets/role/r-admin"))
    assert r.status_code == 200 and not db.targets


def test_writes_clear_the_resolver_cache():
    db = _DB()
    with patch("services.feature_flags.clear_feature_flags_cache") as clear:
        _run(db, lambda: client.patch("/api/admin/flags/learning_loop", json={"default_variant": "on"}))
    assert clear.called
