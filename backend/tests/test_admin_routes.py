"""
Unit tests for routes/admin.py

Tests cover:
  - POST   /api/admin/roles              → create_role
  - POST   /api/admin/roles/assign       → assign_role
  - DELETE /api/admin/roles/revoke       → revoke_role
  - POST   /api/admin/achievements       → create_achievement
  - POST   /api/admin/achievements/grant → grant_achievement
  - POST   /api/admin/cosmetics          → create_cosmetic
  - GET    /api/admin/users              → list_users
  - PATCH  /api/admin/users/{id}/approve → approve_user

All DB access and admin auth are mocked.
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _mock_admin():
    return patch("routes.admin.require_admin", return_value=None)


# ── POST /api/admin/roles ──────────────────────────────────────────────────

class TestCreateRole:
    def test_creates_role(self):
        role_row = {"id": "r1", "name": "VIP", "slug": "vip"}

        with _mock_admin(), patch("routes.admin.table") as t:
            t.return_value.insert.return_value = [role_row]
            r = client.post("/api/admin/roles", json={
                "name": "VIP", "slug": "vip", "color": "#gold",
                "description": "VIP role",
            })

        assert r.status_code == 200
        assert r.json()["role"]["slug"] == "vip"


# ── POST /api/admin/roles/assign ───────────────────────────────────────────

class TestAssignRole:
    def test_assigns_role_to_user(self):
        with _mock_admin(), patch("routes.admin.table") as t:
            t.return_value.insert.return_value = [{}]
            r = client.post("/api/admin/roles/assign", json={
                "user_id": "u1", "role_id": "r1", "granted_by": "admin1",
            })

        assert r.status_code == 200
        assert r.json()["assigned"] is True


# ── DELETE /api/admin/roles/revoke ─────────────────────────────────────────

class TestRevokeRole:
    def test_revokes_role(self):
        with _mock_admin(), patch("routes.admin.table") as t:
            t.return_value.delete.return_value = None
            r = client.request("DELETE", "/api/admin/roles/revoke", json={
                "user_id": "u1", "role_id": "r1",
            })

        assert r.status_code == 200
        assert r.json()["revoked"] is True


# ── POST /api/admin/achievements ───────────────────────────────────────────

class TestCreateAchievement:
    def test_creates_achievement(self):
        ach = {"id": "a1", "name": "First Login", "slug": "first_login"}

        with _mock_admin(), patch("routes.admin.table") as t:
            t.return_value.insert.return_value = [ach]
            r = client.post("/api/admin/achievements", json={
                "name": "First Login", "slug": "first_login",
                "description": "Log in for the first time",
                "category": "general", "rarity": "common",
            })

        assert r.status_code == 200
        assert r.json()["achievement"]["slug"] == "first_login"


# ── POST /api/admin/achievements/grant ─────────────────────────────────────

class TestGrantAchievement:
    def test_grants_achievement_to_user(self):
        with _mock_admin(), \
             patch("routes.admin.table") as t, \
             patch("routes.admin.check_achievements", return_value=[]):
            t.return_value.select.return_value = []
            t.return_value.insert.return_value = [{}]
            r = client.post("/api/admin/achievements/grant", json={
                "user_id": "u1", "achievement_id": "a1",
            })

        assert r.status_code == 200
        assert r.json()["granted"] is True

    def test_409_if_already_earned(self):
        with _mock_admin(), patch("routes.admin.table") as t:
            t.return_value.select.return_value = [{"achievement_id": "a1"}]
            r = client.post("/api/admin/achievements/grant", json={
                "user_id": "u1", "achievement_id": "a1",
            })

        assert r.status_code == 409


# ── POST /api/admin/cosmetics ──────────────────────────────────────────────

class TestCreateCosmetic:
    def test_creates_cosmetic(self):
        cos = {"id": "c1", "name": "Gold Frame", "slug": "gold_frame"}

        with _mock_admin(), patch("routes.admin.table") as t:
            t.return_value.insert.return_value = [cos]
            r = client.post("/api/admin/cosmetics", json={
                "type": "avatar_frame", "name": "Gold Frame", "slug": "gold_frame",
                "rarity": "rare",
            })

        assert r.status_code == 200
        assert r.json()["cosmetic"]["slug"] == "gold_frame"


# ── GET /api/admin/users ───────────────────────────────────────────────────

class TestListUsersPaginated:
    def test_passes_query_and_page_through(self):
        with _mock_admin(), patch("routes.admin.paginate_users") as p:
            p.return_value = {"users": [], "total": 17, "page": 2, "page_size": 25}
            r = client.get("/api/admin/users?q=alice&page=2&page_size=25")
        assert r.status_code == 200
        assert r.json() == {"users": [], "total": 17, "page": 2, "page_size": 25}
        p.assert_called_once_with(q="alice", page=2, page_size=25)

    def test_defaults_when_params_missing(self):
        with _mock_admin(), patch("routes.admin.paginate_users") as p:
            p.return_value = {"users": [], "total": 0, "page": 1, "page_size": 50}
            r = client.get("/api/admin/users")
        assert r.status_code == 200
        assert r.json() == {"users": [], "total": 0, "page": 1, "page_size": 50}
        p.assert_called_once_with(q=None, page=1, page_size=50)


# ── PATCH /api/admin/users/{id}/approve ────────────────────────────────────

class TestApproveUser:
    def test_approves_user(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.get_session_user_id", return_value="admin1"), \
             patch("routes.admin.log_admin_action") as audit:
            t.return_value.update.return_value = [{}]
            r = client.patch("/api/admin/users/u1/approve?user_id=admin1")

        assert r.status_code == 200
        assert r.json()["approved"] is True
        audit.assert_called_once()
        assert audit.call_args.kwargs["action"] == "user.approve"


# ── GET /api/admin/roles ───────────────────────────────────────────────────

class TestListRoles:
    def test_returns_roles_sorted(self):
        rows = [{"id": "r1", "name": "Admin", "slug": "admin", "display_priority": 100}]
        with _mock_admin(), patch("routes.admin.table") as t:
            t.return_value.select.return_value = rows
            r = client.get("/api/admin/roles")
        assert r.status_code == 200
        assert r.json() == {"roles": rows}

    def test_empty_list(self):
        with _mock_admin(), patch("routes.admin.table") as t:
            t.return_value.select.return_value = []
            r = client.get("/api/admin/roles")
        assert r.status_code == 200
        assert r.json() == {"roles": []}


# ── GET /api/admin/achievements ────────────────────────────────────────────

class TestListAchievements:
    def test_returns_achievements(self):
        rows = [{"id": "a1", "name": "First", "slug": "first", "category": "milestone", "rarity": "common", "is_secret": False}]
        with _mock_admin(), patch("routes.admin.table") as t:
            t.return_value.select.return_value = rows
            r = client.get("/api/admin/achievements")
        assert r.status_code == 200
        assert r.json() == {"achievements": rows}


# ── GET /api/admin/cosmetics ───────────────────────────────────────────────

class TestListCosmetics:
    def test_returns_cosmetics(self):
        rows = [{"id": "c1", "type": "avatar_frame", "name": "Gold Frame", "slug": "gold", "rarity": "rare"}]
        with _mock_admin(), patch("routes.admin.table") as t:
            t.return_value.select.return_value = rows
            r = client.get("/api/admin/cosmetics")
        assert r.status_code == 200
        assert r.json() == {"cosmetics": rows}


# ── PATCH /api/admin/users/{id}/unapprove ──────────────────────────────────

class TestUnapproveUser:
    def test_unapproves_user(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.get_session_user_id", return_value="admin1"), \
             patch("routes.admin.log_admin_action") as audit:
            t.return_value.update.return_value = [{}]
            r = client.patch("/api/admin/users/u1/unapprove?user_id=admin1")
        assert r.status_code == 200
        assert r.json()["unapproved"] is True
        audit.assert_called_once()
        assert audit.call_args.kwargs["action"] == "user.unapprove"
        assert audit.call_args.kwargs["target_id"] == "u1"
        assert audit.call_args.kwargs["actor_id"] == "admin1"

    def test_cannot_unapprove_self(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.get_session_user_id", return_value="u1"):
            r = client.patch("/api/admin/users/u1/unapprove?user_id=u1")
        assert r.status_code == 409
        assert "yourself" in r.json()["detail"].lower()
        t.return_value.update.assert_not_called()


class TestAssignRoleIdempotent:
    def test_reassign_same_role_returns_200(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.get_session_user_id", return_value="admin1"), \
             patch("routes.admin.log_admin_action"):
            t.return_value.upsert.return_value = [{}]
            r = client.post("/api/admin/roles/assign", json={
                "user_id": "u1", "role_id": "r1", "granted_by": "admin1",
            })
        assert r.status_code == 200
        assert r.json()["assigned"] is True
        # Must use upsert, not insert.
        assert t.return_value.upsert.called
        assert not t.return_value.insert.called

    def test_granted_by_defaults_to_session_user(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.get_session_user_id", return_value="admin1"), \
             patch("routes.admin.log_admin_action"):
            t.return_value.upsert.return_value = [{}]
            r = client.post("/api/admin/roles/assign", json={
                "user_id": "u1", "role_id": "r1",
            })
        assert r.status_code == 200
        upsert_payload = t.return_value.upsert.call_args.args[0]
        assert upsert_payload["granted_by"] == "admin1"


class TestRevokeRoleSelfProtection:
    def test_cannot_revoke_own_admin(self):
        def by_name(name):
            m = MagicMock()
            if name == "roles":
                m.select.return_value = [{"id": "rA", "slug": "admin"}]
            elif name == "user_roles":
                m.select.return_value = []
            return m

        with patch("routes.admin.get_session_user_id", return_value="u1"), \
             _mock_admin(), \
             patch("routes.admin.table", side_effect=by_name):
            r = client.request("DELETE", "/api/admin/roles/revoke",
                               json={"user_id": "u1", "role_id": "rA"})
        assert r.status_code == 409
        assert "own admin" in r.json()["detail"].lower()

    def test_cannot_revoke_last_admin(self):
        def by_name(name):
            m = MagicMock()
            if name == "roles":
                m.select.return_value = [{"id": "rA", "slug": "admin"}]
            elif name == "user_roles":
                m.select.return_value = [{"user_id": "u2"}]
            return m

        with patch("routes.admin.get_session_user_id", return_value="u1"), \
             _mock_admin(), \
             patch("routes.admin.table", side_effect=by_name):
            r = client.request("DELETE", "/api/admin/roles/revoke",
                               json={"user_id": "u2", "role_id": "rA"})
        assert r.status_code == 409
        assert "last admin" in r.json()["detail"].lower()

    def test_revoke_non_admin_role_succeeds(self):
        def by_name(name):
            m = MagicMock()
            if name == "roles":
                m.select.return_value = [{"id": "rB", "slug": "verified"}]
            return m

        with patch("routes.admin.get_session_user_id", return_value="u1"), \
             _mock_admin(), \
             patch("routes.admin.table", side_effect=by_name), \
             patch("routes.admin.log_admin_action"):
            r = client.request("DELETE", "/api/admin/roles/revoke",
                               json={"user_id": "u2", "role_id": "rB"})
        assert r.status_code == 200
        assert r.json()["revoked"] is True


class TestDeleteRoleProtection:
    def test_cannot_delete_admin_role(self):
        def by_name(name):
            m = MagicMock()
            m.select.return_value = [{"id": "rA", "slug": "admin"}]
            return m

        with _mock_admin(), \
             patch("routes.admin.get_session_user_id", return_value="u1"), \
             patch("routes.admin.table", side_effect=by_name):
            r = client.delete("/api/admin/roles/rA")
        assert r.status_code == 409
        assert "admin role" in r.json()["detail"].lower()

    def test_delete_non_admin_role_succeeds(self):
        def by_name(name):
            m = MagicMock()
            m.select.return_value = [{"id": "rB", "slug": "verified"}]
            return m

        with _mock_admin(), \
             patch("routes.admin.get_session_user_id", return_value="u1"), \
             patch("routes.admin.table", side_effect=by_name), \
             patch("routes.admin.log_admin_action"):
            r = client.delete("/api/admin/roles/rB")
        assert r.status_code == 200
        assert r.json()["deleted"] is True


class TestRoleCreateUpdateAudits:
    def test_create_logs_audit(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.get_session_user_id", return_value="u1"), \
             patch("routes.admin.log_admin_action") as audit:
            t.return_value.insert.return_value = [{"id": "rZ"}]
            r = client.post("/api/admin/roles", json={
                "name": "Z", "slug": "z", "color": "#fff",
            })
        assert r.status_code == 200
        assert audit.call_args.kwargs["action"] == "role.create"

    def test_update_logs_audit(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.get_session_user_id", return_value="u1"), \
             patch("routes.admin.log_admin_action") as audit:
            t.return_value.update.return_value = [{}]
            r = client.patch("/api/admin/roles/rA", json={"color": "#000"})
        assert r.status_code == 200
        assert audit.call_args.kwargs["action"] == "role.update"


class TestTriggers:
    def test_list_returns_triggers_for_achievement(self):
        rows = [{"id": "t1", "achievement_id": "a1", "trigger_type": "login_streak", "trigger_threshold": 7}]
        with _mock_admin(), patch("routes.admin.table") as t:
            t.return_value.select.return_value = rows
            r = client.get("/api/admin/achievements/a1/triggers")
        assert r.status_code == 200
        assert r.json() == {"triggers": rows}

    def test_update_trigger(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.get_session_user_id", return_value="u1"), \
             patch("routes.admin.log_admin_action") as audit:
            t.return_value.update.return_value = [{}]
            r = client.patch("/api/admin/achievements/triggers/t1",
                             json={"trigger_threshold": 14})
        assert r.status_code == 200
        assert r.json()["updated"] is True
        assert audit.call_args.kwargs["action"] == "trigger.update"

    def test_update_trigger_rejects_empty(self):
        with _mock_admin(), patch("routes.admin.get_session_user_id", return_value="u1"):
            r = client.patch("/api/admin/achievements/triggers/t1", json={})
        assert r.status_code == 400

    def test_delete_trigger(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.get_session_user_id", return_value="u1"), \
             patch("routes.admin.log_admin_action") as audit:
            t.return_value.delete.return_value = [{}]
            r = client.delete("/api/admin/achievements/triggers/t1")
        assert r.status_code == 200
        assert r.json()["deleted"] is True
        assert audit.call_args.kwargs["action"] == "trigger.delete"


class TestAchievementCosmeticLinks:
    def test_list_links(self):
        rows = [{"achievement_id": "a1", "cosmetic_id": "c1"}]
        with _mock_admin(), patch("routes.admin.table") as t:
            t.return_value.select.return_value = rows
            r = client.get("/api/admin/achievements/a1/cosmetics")
        assert r.status_code == 200
        assert r.json() == {"links": rows}

    def test_link(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.get_session_user_id", return_value="u1"), \
             patch("routes.admin.log_admin_action") as audit:
            t.return_value.upsert.return_value = [{"achievement_id": "a1", "cosmetic_id": "c1"}]
            r = client.post("/api/admin/achievements/cosmetics",
                            json={"achievement_id": "a1", "cosmetic_id": "c1"})
        assert r.status_code == 200
        assert r.json()["linked"] is True
        assert audit.call_args.kwargs["action"] == "achievement_cosmetic.link"

    def test_unlink(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.get_session_user_id", return_value="u1"), \
             patch("routes.admin.log_admin_action") as audit:
            t.return_value.delete.return_value = [{}]
            r = client.request("DELETE", "/api/admin/achievements/cosmetics",
                               json={"achievement_id": "a1", "cosmetic_id": "c1"})
        assert r.status_code == 200
        assert r.json()["unlinked"] is True
        assert audit.call_args.kwargs["action"] == "achievement_cosmetic.unlink"


class TestAchievementAudits:
    def test_create_logs_audit(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.get_session_user_id", return_value="u1"), \
             patch("routes.admin.log_admin_action") as audit:
            t.return_value.insert.return_value = [{"id": "a9"}]
            r = client.post("/api/admin/achievements", json={
                "name": "Z", "slug": "z", "category": "milestone", "rarity": "common",
            })
        assert r.status_code == 200
        assert audit.call_args.kwargs["action"] == "achievement.create"

    def test_update_logs_audit(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.get_session_user_id", return_value="u1"), \
             patch("routes.admin.log_admin_action") as audit:
            t.return_value.update.return_value = [{}]
            r = client.patch("/api/admin/achievements/a1", json={"name": "Z2"})
        assert r.status_code == 200
        assert audit.call_args.kwargs["action"] == "achievement.update"

    def test_delete_logs_audit(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.get_session_user_id", return_value="u1"), \
             patch("routes.admin.log_admin_action") as audit:
            t.return_value.delete.return_value = [{}]
            r = client.delete("/api/admin/achievements/a1")
        assert r.status_code == 200
        assert audit.call_args.kwargs["action"] == "achievement.delete"

    def test_grant_logs_audit(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.get_session_user_id", return_value="u1"), \
             patch("routes.admin.log_admin_action") as audit, \
             patch("routes.admin.check_achievements", return_value=[]):
            t.return_value.select.return_value = []
            t.return_value.insert.return_value = [{}]
            r = client.post("/api/admin/achievements/grant", json={
                "user_id": "u2", "achievement_id": "a1",
            })
        assert r.status_code == 200
        assert audit.call_args.kwargs["action"] == "achievement.grant"

    def test_create_trigger_logs_audit(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.get_session_user_id", return_value="u1"), \
             patch("routes.admin.log_admin_action") as audit:
            t.return_value.insert.return_value = [{"id": "t1"}]
            r = client.post("/api/admin/achievements/triggers", json={
                "achievement_id": "a1", "trigger_type": "login_streak", "trigger_threshold": 7,
            })
        assert r.status_code == 200
        assert audit.call_args.kwargs["action"] == "trigger.create"


class TestRoleCosmeticLinks:
    def test_list_links_for_role(self):
        rows = [{"role_id": "rA", "cosmetic_id": "c1"}]
        with _mock_admin(), patch("routes.admin.table") as t:
            t.return_value.select.return_value = rows
            r = client.get("/api/admin/roles/rA/cosmetics")
        assert r.status_code == 200
        assert r.json() == {"links": rows}

    def test_link(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.get_session_user_id", return_value="u1"), \
             patch("routes.admin.log_admin_action") as audit:
            t.return_value.upsert.return_value = [{"role_id": "rA", "cosmetic_id": "c1"}]
            r = client.post("/api/admin/roles/cosmetics",
                            json={"role_id": "rA", "cosmetic_id": "c1"})
        assert r.status_code == 200
        assert r.json()["linked"] is True
        assert audit.call_args.kwargs["action"] == "role_cosmetic.link"

    def test_unlink(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.get_session_user_id", return_value="u1"), \
             patch("routes.admin.log_admin_action") as audit:
            t.return_value.delete.return_value = [{}]
            r = client.request("DELETE", "/api/admin/roles/cosmetics",
                               json={"role_id": "rA", "cosmetic_id": "c1"})
        assert r.status_code == 200
        assert r.json()["unlinked"] is True
        assert audit.call_args.kwargs["action"] == "role_cosmetic.unlink"


class TestCosmeticAudits:
    def test_create_logs_audit(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.get_session_user_id", return_value="u1"), \
             patch("routes.admin.log_admin_action") as audit:
            t.return_value.insert.return_value = [{"id": "c9"}]
            r = client.post("/api/admin/cosmetics", json={
                "type": "avatar_frame", "name": "Z", "slug": "z", "rarity": "common",
            })
        assert r.status_code == 200
        assert audit.call_args.kwargs["action"] == "cosmetic.create"

    def test_update_logs_audit(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.get_session_user_id", return_value="u1"), \
             patch("routes.admin.log_admin_action") as audit:
            t.return_value.update.return_value = [{}]
            r = client.patch("/api/admin/cosmetics/c1", json={"name": "Z2"})
        assert r.status_code == 200
        assert audit.call_args.kwargs["action"] == "cosmetic.update"

    def test_delete_logs_audit(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.get_session_user_id", return_value="u1"), \
             patch("routes.admin.log_admin_action") as audit:
            t.return_value.delete.return_value = [{}]
            r = client.delete("/api/admin/cosmetics/c1")
        assert r.status_code == 200
        assert audit.call_args.kwargs["action"] == "cosmetic.delete"


class TestAllowlistAudits:
    def test_approve_logs_audit(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.get_session_user_id", return_value="u1"), \
             patch("routes.admin.log_admin_action") as audit:
            t.return_value.upsert.return_value = [{"email": "a@b.c"}]
            r = client.post("/api/admin/allowlist/approve", json={"email": "A@B.c"})
        assert r.status_code == 200
        assert audit.call_args.kwargs["action"] == "allowlist.approve"
        assert audit.call_args.kwargs["payload"]["email"] == "A@B.c"

    def test_revoke_logs_audit(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.get_session_user_id", return_value="u1"), \
             patch("routes.admin.log_admin_action") as audit:
            t.return_value.update.return_value = [{"email": "a@b.c"}]
            r = client.post("/api/admin/allowlist/revoke", json={"email": "A@B.c"})
        assert r.status_code == 200
        assert audit.call_args.kwargs["action"] == "allowlist.revoke"
        assert r.json() == {"email": {"email": "a@b.c"}}

    def test_revoke_404_does_not_audit(self):
        with _mock_admin(), patch("routes.admin.table") as t, \
             patch("routes.admin.get_session_user_id", return_value="u1"), \
             patch("routes.admin.log_admin_action") as audit:
            t.return_value.update.return_value = []
            r = client.post("/api/admin/allowlist/revoke", json={"email": "missing@b.c"})
        assert r.status_code == 404
        audit.assert_not_called()


class TestAuditLogRead:
    def test_returns_paginated_audit_with_filters(self):
        rows = [
            {"id": "1", "actor_id": "admin1", "action": "user.approve",
             "target_type": "user", "target_id": "u1", "payload": {},
             "created_at": "2026-05-04T00:00:00Z"},
        ]
        with _mock_admin(), patch("routes.admin.table") as t:
            t.return_value.select_with_count.return_value = (rows, 1)
            r = client.get("/api/admin/audit?action=user.approve&page=1&page_size=10")
        assert r.status_code == 200
        body = r.json()
        assert body["entries"] == rows
        assert body["total"] == 1
        assert body["page"] == 1
        assert body["page_size"] == 10

    def test_caps_page_size(self):
        with _mock_admin(), patch("routes.admin.table") as t:
            t.return_value.select_with_count.return_value = ([], 0)
            r = client.get("/api/admin/audit?page_size=9999")
        assert r.status_code == 200
        assert r.json()["page_size"] == 200


class TestAnalyticsOverview:
    def test_returns_totals_and_series(self):
        users = [
            {"id": "u1", "is_approved": True,  "created_at": "2026-05-01T00:00:00Z"},
            {"id": "u2", "is_approved": True,  "created_at": "2026-05-01T00:00:00Z"},
            {"id": "u3", "is_approved": False, "created_at": "2026-05-02T00:00:00Z"},
        ]
        roles = [{"id": "rA", "slug": "admin", "name": "Admin", "color": "#dc2626"}]
        user_roles = [{"role_id": "rA"}, {"role_id": "rA"}, {"role_id": "rA"}]

        def by_name(name):
            m = MagicMock()
            if name == "users":
                m.select.return_value = users
            elif name == "roles":
                m.select.return_value = roles
            elif name == "user_roles":
                m.select.return_value = user_roles
            else:
                m.select.return_value = []
            return m

        with _mock_admin(), patch("routes.admin.table", side_effect=by_name):
            r = client.get("/api/admin/analytics/overview")

        assert r.status_code == 200
        body = r.json()
        assert body["totals"]["users"] == 3
        assert body["totals"]["approved"] == 2
        assert body["totals"]["pending"] == 1
        assert body["totals"]["admins"] == 3
        assert any(d["date"] == "2026-05-01" and d["count"] == 2 for d in body["signups_by_day"])
        assert body["role_counts"][0]["slug"] == "admin"
        assert body["role_counts"][0]["count"] == 3
