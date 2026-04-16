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

class TestListUsers:
    def test_returns_all_users(self):
        users = [
            {"id": "u1", "name": "Alice", "email": "a@b.c", "is_approved": True, "created_at": "2025-01-01"},
        ]

        call_count = 0

        def table_side_effect(name):
            nonlocal call_count
            m = MagicMock()
            if name == "users":
                m.select.return_value = users
            elif name == "user_roles":
                m.select.return_value = [{"roles": {"id": "r1", "name": "Admin", "slug": "admin", "color": "#f00"}}]
            else:
                m.select.return_value = []
            return m

        with _mock_admin(), patch("routes.admin.table", side_effect=table_side_effect):
            r = client.get("/api/admin/users?user_id=admin1")

        assert r.status_code == 200
        assert len(r.json()["users"]) == 1
        assert r.json()["users"][0]["name"] == "Alice"


# ── PATCH /api/admin/users/{id}/approve ────────────────────────────────────

class TestApproveUser:
    def test_approves_user(self):
        with _mock_admin(), patch("routes.admin.table") as t:
            t.return_value.update.return_value = [{}]
            r = client.patch("/api/admin/users/u1/approve?user_id=admin1")

        assert r.status_code == 200
        assert r.json()["approved"] is True
