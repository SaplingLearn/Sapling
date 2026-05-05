"""
Unit tests for routes/profile.py

Tests cover:
  - GET  /api/profile/{user_id}                → get_public_profile
  - PATCH /api/profile/{user_id}               → update_profile
  - GET  /api/profile/{user_id}/settings       → get_settings
  - PATCH /api/profile/{user_id}/settings      → update_settings
  - POST /api/profile/{user_id}/equip          → equip_cosmetic
  - POST /api/profile/{user_id}/featured-role  → set_featured_role
  - POST /api/profile/{user_id}/featured-achievements → set_featured_achievements
  - GET  /api/profile/{user_id}/achievements   → get_achievements
  - GET  /api/profile/{user_id}/cosmetics      → get_cosmetics
  - GET  /api/profile/{user_id}/roles          → get_roles
  - DELETE /api/profile/{user_id}/account      → delete_account
  - POST /api/profile/{user_id}/export         → export_data

All DB access and auth guards are mocked.
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

USER_ID = "user_test_1"

# ── Auth mock helpers ───────────────────────────────────────────────────────

def _mock_self():
    return patch("routes.profile.require_self", return_value=None)


def _mock_session_user():
    return patch("routes.profile.get_session_user_id", return_value=USER_ID)


# ── GET /api/profile/{user_id} ─────────────────────────────────────────────

class TestGetPublicProfile:
    def test_returns_profile_for_existing_user(self):
        user_row = {"id": USER_ID, "name": "Test", "username": "tester", "avatar_url": None, "created_at": "2025-01-01", "bio": "Hi", "location": "NYC", "website": None}
        settings_row = {"user_id": USER_ID, "profile_visibility": "public"}

        def table_side_effect(name):
            m = MagicMock()
            if name == "users":
                m.select.return_value = [user_row]
            elif name == "user_settings":
                m.select.return_value = [settings_row]
            elif name == "user_roles":
                m.select.return_value = []
            elif name == "user_achievements":
                m.select.return_value = []
            elif name == "sessions":
                m.select.return_value = []
            elif name == "documents":
                m.select.return_value = []
            elif name == "cosmetics":
                m.select.return_value = []
            elif name == "roles":
                m.select.return_value = []
            else:
                m.select.return_value = []
            return m

        with patch("routes.profile.table", side_effect=table_side_effect):
            r = client.get(f"/api/profile/{USER_ID}")

        assert r.status_code == 200
        data = r.json()
        assert data["id"] == USER_ID
        assert data["name"] == "Test"
        assert data["username"] == "tester"

    def test_404_for_missing_user(self):
        def table_side_effect(name):
            m = MagicMock()
            m.select.return_value = []
            return m

        with patch("routes.profile.table", side_effect=table_side_effect):
            r = client.get("/api/profile/nonexistent")

        assert r.status_code == 404

    def test_private_profile_hides_bio_and_stats(self):
        user_row = {"id": USER_ID, "name": "Test", "username": None, "avatar_url": None, "created_at": "2025-01-01", "bio": "Secret", "location": "Hidden", "website": None}
        settings_row = {"user_id": USER_ID, "profile_visibility": "private"}

        def table_side_effect(name):
            m = MagicMock()
            if name == "users":
                m.select.return_value = [user_row]
            elif name == "user_settings":
                m.select.return_value = [settings_row]
            else:
                m.select.return_value = []
            return m

        with patch("routes.profile.table", side_effect=table_side_effect):
            r = client.get(f"/api/profile/{USER_ID}")

        assert r.status_code == 200
        data = r.json()
        assert data["bio"] is None
        assert data["location"] is None
        assert data["stats"] == {}


# ── PATCH /api/profile/{user_id} ───────────────────────────────────────────

class TestUpdateProfile:
    def test_updates_user_fields(self):
        user_row = {"id": USER_ID, "name": "Test"}
        settings_row = {"user_id": USER_ID}

        def table_side_effect(name):
            m = MagicMock()
            if name == "users":
                m.select.return_value = [user_row]
            elif name == "user_settings":
                m.select.return_value = [settings_row]
            else:
                m.select.return_value = []
            m.update.return_value = [{}]
            return m

        with _mock_self(), patch("routes.profile.table", side_effect=table_side_effect):
            r = client.patch(f"/api/profile/{USER_ID}", json={"bio": "Updated bio"})

        assert r.status_code == 200
        assert r.json()["updated"] is True

    def test_username_conflict_returns_409(self):
        user_row = {"id": USER_ID, "name": "Test"}

        def table_side_effect(name):
            m = MagicMock()
            if name == "users":
                m.select.return_value = [{"id": "other_user"}]
            elif name == "user_settings":
                m.select.return_value = [{"user_id": USER_ID}]
            else:
                m.select.return_value = []
            return m

        with _mock_self(), patch("routes.profile.table", side_effect=table_side_effect):
            r = client.patch(f"/api/profile/{USER_ID}", json={"username": "taken"})

        assert r.status_code == 409


# ── GET /api/profile/{user_id}/settings ────────────────────────────────────

class TestGetSettings:
    def test_returns_settings(self):
        settings = {"user_id": USER_ID, "theme": "light", "font_size": "md"}

        def table_side_effect(name):
            m = MagicMock()
            if name == "user_settings":
                m.select.return_value = [settings]
            else:
                m.select.return_value = []
            return m

        with _mock_self(), patch("routes.profile.table", side_effect=table_side_effect):
            r = client.get(f"/api/profile/{USER_ID}/settings?user_id={USER_ID}")

        assert r.status_code == 200
        assert r.json()["theme"] == "light"


# ── POST /api/profile/{user_id}/equip ──────────────────────────────────────

class TestEquipCosmetic:
    def test_equip_owned_cosmetic(self):
        settings = {"user_id": USER_ID}

        def table_side_effect(name):
            m = MagicMock()
            if name == "user_settings":
                m.select.return_value = [settings]
                m.update.return_value = [{}]
            elif name == "user_cosmetics":
                m.select.return_value = [{"cosmetic_id": "cos_1"}]
            else:
                m.select.return_value = []
            return m

        with _mock_self(), patch("routes.profile.table", side_effect=table_side_effect):
            r = client.post(f"/api/profile/{USER_ID}/equip", json={"slot": "avatar_frame", "cosmetic_id": "cos_1"})

        assert r.status_code == 200
        assert r.json()["equipped"] is True

    def test_equip_unowned_cosmetic_returns_403(self):
        settings = {"user_id": USER_ID}

        def table_side_effect(name):
            m = MagicMock()
            if name == "user_settings":
                m.select.return_value = [settings]
            elif name == "user_cosmetics":
                m.select.return_value = []
            else:
                m.select.return_value = []
            return m

        with _mock_self(), patch("routes.profile.table", side_effect=table_side_effect):
            r = client.post(f"/api/profile/{USER_ID}/equip", json={"slot": "avatar_frame", "cosmetic_id": "cos_1"})

        assert r.status_code == 403

    def test_invalid_slot_returns_400(self):
        settings = {"user_id": USER_ID}

        def table_side_effect(name):
            m = MagicMock()
            if name == "user_settings":
                m.select.return_value = [settings]
            else:
                m.select.return_value = []
            return m

        with _mock_self(), patch("routes.profile.table", side_effect=table_side_effect):
            r = client.post(f"/api/profile/{USER_ID}/equip", json={"slot": "invalid_slot", "cosmetic_id": "cos_1"})

        assert r.status_code == 400


# ── DELETE /api/profile/{user_id}/account ──────────────────────────────────

class TestDeleteAccount:
    def test_soft_deletes_with_confirmation(self):
        user_row = {"id": USER_ID}

        def table_side_effect(name):
            m = MagicMock()
            m.select.return_value = [user_row]
            m.update.return_value = [{}]
            return m

        with _mock_self(), patch("routes.profile.table", side_effect=table_side_effect):
            r = client.request("DELETE", f"/api/profile/{USER_ID}/account", json={"confirmation": "DELETE"})

        assert r.status_code == 200
        assert r.json()["deleted"] is True

    def test_rejects_wrong_confirmation(self):
        with _mock_self(), patch("routes.profile.table") as t:
            t.return_value.select.return_value = [{"id": USER_ID}]
            r = client.request("DELETE", f"/api/profile/{USER_ID}/account", json={"confirmation": "wrong"})

        assert r.status_code == 400


# ── GET /api/profile/{user_id}/achievements ────────────────────────────────

class TestGetAchievements:
    def test_returns_earned_and_available(self):
        all_achs = [
            {"id": "a1", "name": "First Login", "slug": "first_login", "description": "Log in", "icon": None, "category": "general", "rarity": "common", "is_secret": False},
            {"id": "a2", "name": "Secret One", "slug": "secret", "description": "Hidden", "icon": None, "category": "general", "rarity": "rare", "is_secret": True},
        ]
        earned = [{"achievement_id": "a1", "earned_at": "2025-01-01", "is_featured": False}]

        def table_side_effect(name):
            m = MagicMock()
            if name == "achievements":
                m.select.return_value = all_achs
            elif name == "user_achievements":
                m.select.return_value = earned
            else:
                m.select.return_value = []
            return m

        with patch("routes.profile.table", side_effect=table_side_effect):
            r = client.get(f"/api/profile/{USER_ID}/achievements")

        assert r.status_code == 200
        data = r.json()
        assert len(data["earned"]) == 1
        assert len(data["available"]) == 1
        # Secret achievement should be masked
        assert data["available"][0]["name"] == "Secret Achievement"


# ── GET /api/profile/{user_id}/roles ───────────────────────────────────────

class TestGetRoles:
    def test_returns_user_roles(self):
        role_data = {"id": "r1", "name": "Admin", "slug": "admin", "color": "#f00", "icon": None, "description": "Administrator", "is_staff_assigned": True, "is_earnable": False, "display_priority": 100}

        def table_side_effect(name):
            m = MagicMock()
            if name == "user_roles":
                m.select.return_value = [{"roles": role_data, "granted_at": "2025-01-01"}]
            else:
                m.select.return_value = []
            return m

        with patch("routes.profile.table", side_effect=table_side_effect):
            r = client.get(f"/api/profile/{USER_ID}/roles")

        assert r.status_code == 200
        assert len(r.json()["roles"]) == 1
        assert r.json()["roles"][0]["role"]["slug"] == "admin"


# ── GET /api/profile/username/check ────────────────────────────────────────

class TestCheckUsername:
    def test_available_when_no_existing_row(self):
        with patch("routes.profile.table") as t:
            t.return_value.select.return_value = []
            r = client.get("/api/profile/username/check?username=freshname")
        assert r.status_code == 200
        assert r.json() == {"available": True}

    def test_taken_when_different_user_holds_it(self):
        with patch("routes.profile.table") as t:
            t.return_value.select.return_value = [{"id": "other_user"}]
            r = client.get("/api/profile/username/check?username=taken")
        assert r.status_code == 200
        body = r.json()
        assert body["available"] is False
        assert body["reason"] == "taken"

    def test_available_when_held_by_self(self):
        with patch("routes.profile.table") as t:
            t.return_value.select.return_value = [{"id": USER_ID}]
            r = client.get(f"/api/profile/username/check?username=mine&user_id={USER_ID}")
        assert r.status_code == 200
        body = r.json()
        assert body["available"] is True
        assert body["reason"] == "self"

    def test_invalid_format_short(self):
        r = client.get("/api/profile/username/check?username=ab")
        assert r.status_code == 200
        assert r.json() == {"available": False, "reason": "invalid"}

    def test_invalid_format_special_chars(self):
        r = client.get("/api/profile/username/check?username=bad-name!")
        assert r.status_code == 200
        assert r.json() == {"available": False, "reason": "invalid"}


# ── GET /api/profile/{user_id}/cosmetics/catalog ───────────────────────────

class TestGetCosmeticsCatalog:
    def test_groups_by_type_with_owned_flag(self):
        all_cosmetics = [
            {"id": "c1", "type": "avatar_frame", "name": "Gold",   "slug": "gold",   "rarity": "rare",   "unlock_source": "achievement:streak_7"},
            {"id": "c2", "type": "avatar_frame", "name": "Silver", "slug": "silver", "rarity": "common", "unlock_source": None},
            {"id": "c3", "type": "title",        "name": "MVP",    "slug": "mvp",    "rarity": "epic",   "unlock_source": "shop"},
        ]
        owned = [{"cosmetic_id": "c1"}]

        def table_side_effect(name):
            m = MagicMock()
            if name == "cosmetics":
                m.select.return_value = all_cosmetics
            elif name == "user_cosmetics":
                m.select.return_value = owned
            elif name == "user_settings":
                m.select.return_value = [{"user_id": USER_ID}]
            else:
                m.select.return_value = []
            return m

        with _mock_self(), patch("routes.profile.table", side_effect=table_side_effect):
            r = client.get(f"/api/profile/{USER_ID}/cosmetics/catalog?user_id={USER_ID}")

        assert r.status_code == 200
        catalog = r.json()["catalog"]
        frames = catalog["avatar_frame"]
        by_slug = {c["slug"]: c for c in frames}
        assert by_slug["gold"]["owned"] is True
        assert by_slug["silver"]["owned"] is False
        assert catalog["title"][0]["owned"] is False
        # Buckets missing items should still be present as empty arrays.
        assert catalog["banner"] == []
        assert catalog["name_color"] == []


# ── GET /api/profile/{user_id}/achievements (progress enrichment) ──────────

class TestAchievementProgress:
    def test_locked_achievement_carries_progress(self):
        all_achs = [{
            "id": "a1", "name": "Streak 7", "slug": "streak_7",
            "description": "7 day streak", "icon": None,
            "category": "activity", "rarity": "uncommon", "is_secret": False,
        }]
        triggers = [{"achievement_id": "a1", "trigger_type": "login_streak", "trigger_threshold": 7}]

        def table_side_effect(name):
            m = MagicMock()
            if name == "achievements":
                m.select.return_value = all_achs
            elif name == "user_achievements":
                m.select.return_value = []  # nothing earned yet
            elif name == "achievement_triggers":
                m.select.return_value = triggers
            else:
                m.select.return_value = []
            return m

        with patch("routes.profile.table", side_effect=table_side_effect), \
             patch("routes.profile.get_user_stat", return_value=3):
            r = client.get(f"/api/profile/{USER_ID}/achievements")

        assert r.status_code == 200
        available = r.json()["available"]
        assert len(available) == 1
        assert available[0]["progress"] == {"current": 3, "target": 7}

    def test_progress_clamps_to_target(self):
        all_achs = [{
            "id": "a1", "name": "Docs 5", "slug": "documents_5",
            "description": "5 docs", "icon": None,
            "category": "milestone", "rarity": "common", "is_secret": False,
        }]
        triggers = [{"achievement_id": "a1", "trigger_type": "documents_uploaded", "trigger_threshold": 5}]

        def table_side_effect(name):
            m = MagicMock()
            if name == "achievements":
                m.select.return_value = all_achs
            elif name == "user_achievements":
                m.select.return_value = []
            elif name == "achievement_triggers":
                m.select.return_value = triggers
            else:
                m.select.return_value = []
            return m

        with patch("routes.profile.table", side_effect=table_side_effect), \
             patch("routes.profile.get_user_stat", return_value=42):
            r = client.get(f"/api/profile/{USER_ID}/achievements")

        assert r.status_code == 200
        assert r.json()["available"][0]["progress"] == {"current": 5, "target": 5}

    def test_secret_locked_has_no_progress(self):
        all_achs = [{
            "id": "a1", "name": "Hidden", "slug": "hidden",
            "description": "Secret", "icon": None,
            "category": "special", "rarity": "rare", "is_secret": True,
        }]
        triggers = [{"achievement_id": "a1", "trigger_type": "login_streak", "trigger_threshold": 100}]

        def table_side_effect(name):
            m = MagicMock()
            if name == "achievements":
                m.select.return_value = all_achs
            elif name == "user_achievements":
                m.select.return_value = []
            elif name == "achievement_triggers":
                m.select.return_value = triggers
            else:
                m.select.return_value = []
            return m

        with patch("routes.profile.table", side_effect=table_side_effect), \
             patch("routes.profile.get_user_stat", return_value=1):
            r = client.get(f"/api/profile/{USER_ID}/achievements")

        assert r.status_code == 200
        out = r.json()["available"][0]
        assert out["name"] == "Secret Achievement"
        assert out["progress"] is None


# ── POST /api/profile/{user_id}/avatar (JSON+base64) ──────────────────────


class TestUploadAvatar:
    """The avatar route accepts a JSON body with a base64-encoded file
    instead of multipart/form-data. Multipart was silently failing in
    some browser configs with `TypeError: Failed to fetch` — JSON
    avoids the failure class. See routes/profile.py:_AvatarUploadBody."""

    USER_ROW = {"id": USER_ID, "name": "Test", "username": None, "avatar_url": None, "created_at": "2025-01-01"}

    def _table_factory(self, *, captured_update=None):
        def factory(name):
            m = MagicMock()
            if name == "users":
                m.select.return_value = [self.USER_ROW]
                if captured_update is not None:
                    def _capture(payload, filters):
                        captured_update.append({"payload": payload, "filters": filters})
                        return [{}]
                    m.update.side_effect = _capture
                else:
                    m.update.return_value = [{}]
            else:
                m.select.return_value = []
                m.update.return_value = []
            return m
        return factory

    def test_accepts_base64_body_and_uploads(self):
        captured = []
        with _mock_self(), \
             patch("routes.profile.table", side_effect=self._table_factory(captured_update=captured)), \
             patch("routes.profile.upload_avatar", return_value="https://cdn/avatar.png") as up:
            r = client.post(
                f"/api/profile/{USER_ID}/avatar",
                json={
                    # Base64 of the bytes "PNG-bytes"
                    "file_b64": "UE5HLWJ5dGVz",
                    "content_type": "image/png",
                },
            )

        assert r.status_code == 200
        assert r.json()["avatar_url"] == "https://cdn/avatar.png"
        # Ensure decoded bytes (not the base64 string) reach the storage layer.
        up.assert_called_once_with(USER_ID, b"PNG-bytes", "image/png")
        # Ensure the avatar_url is persisted to users.
        assert captured == [{"payload": {"avatar_url": "https://cdn/avatar.png"}, "filters": {"id": f"eq.{USER_ID}"}}]

    def test_accepts_data_url_prefix(self):
        """Frontend's readFileAsBase64 strips the prefix, but a future
        client that forgets must also work — accept either shape."""
        with _mock_self(), \
             patch("routes.profile.table", side_effect=self._table_factory()), \
             patch("routes.profile.upload_avatar", return_value="https://cdn/avatar.png") as up:
            r = client.post(
                f"/api/profile/{USER_ID}/avatar",
                json={
                    "file_b64": "data:image/png;base64,UE5HLWJ5dGVz",
                    "content_type": "image/png",
                },
            )

        assert r.status_code == 200
        up.assert_called_once_with(USER_ID, b"PNG-bytes", "image/png")

    def test_invalid_base64_returns_400(self):
        with _mock_self(), \
             patch("routes.profile.table", side_effect=self._table_factory()), \
             patch("routes.profile.upload_avatar") as up:
            r = client.post(
                f"/api/profile/{USER_ID}/avatar",
                json={"file_b64": "!!!not-base64!!!", "content_type": "image/png"},
            )

        assert r.status_code == 400
        assert "Invalid base64" in r.json()["detail"]
        up.assert_not_called()

    def test_missing_file_b64_returns_422(self):
        """Pydantic body validation rejects missing required field."""
        with _mock_self(), patch("routes.profile.table", side_effect=self._table_factory()):
            r = client.post(
                f"/api/profile/{USER_ID}/avatar",
                json={"content_type": "image/png"},
            )
        assert r.status_code == 422


# ── _get_user_or_404 column contract (issue #75) ────────────────────────────

class TestGetUserOr404SelectColumns:
    """Pin the column list used by `_get_user_or_404`'s SELECT against the
    actual `users` schema. Issue #75 was caused by `school` and `major` being
    SELECTed despite never being added by any migration; PostgREST returned
    HTTP 400, the route 500'd, and three endpoints (PATCH, GET, avatar POST)
    failed simultaneously. Existing MagicMock-based tests didn't catch it
    because the mock returns success for any column.
    """

    # Columns that actually exist on `users` per
    # `backend/db/supabase_schema.sql:7` + `migration_profile_settings.sql`
    # + `migration_google_auth.sql` + `migration_add_is_approved.sql` +
    # `migration_onboarding_fields.sql`. If a future migration adds a column
    # to `users`, update this set in the same PR that introduces the
    # migration so the test stays the source of truth.
    USERS_SCHEMA_COLUMNS = {
        "id", "name", "email", "first_name", "last_name", "year",
        "majors", "minors", "learning_style", "onboarding_completed",
        "streak_count", "last_active_date", "room_id", "created_at",
        "google_id", "avatar_url", "auth_provider", "is_approved",
        "username", "bio", "location", "website", "deleted_at",
    }

    def test_select_columns_all_exist_on_users_schema(self):
        """Every column in `_get_user_or_404`'s SELECT must exist on
        `users`. The column string is the second positional arg to
        `table('users').select(...)`; we capture it and compare against
        the schema set above."""
        captured = {}

        def table_side_effect(name):
            m = MagicMock()
            if name == "users":
                def _capture_select(columns, **kwargs):
                    captured["users_columns"] = columns
                    # Return a row with every encrypted column set to
                    # None so `decrypt_if_present` returns early without
                    # trying to base64-decode a plaintext fixture (which
                    # logs a noisy "Nonce must be between..." warning).
                    # The non-encrypted scalars stay populated since
                    # the route accesses them by `.get(...)`.
                    return [{
                        "id": USER_ID,
                        "name": None,
                        "email": None,
                        "first_name": None,
                        "last_name": None,
                        "username": "tester",
                        "avatar_url": None,
                        "year": None,
                        "majors": [],
                        "minors": [],
                        "bio": None,
                        "location": None,
                        "website": None,
                        "streak_count": 0,
                        "created_at": "2026-01-01",
                    }]
                m.select.side_effect = _capture_select
            else:
                m.select.return_value = []
            return m

        with patch("routes.profile.table", side_effect=table_side_effect):
            from routes.profile import _get_user_or_404
            _get_user_or_404(USER_ID)

        assert "users_columns" in captured, "table('users').select(...) was not called"
        selected = {c.strip() for c in captured["users_columns"].split(",")}
        unknown = selected - self.USERS_SCHEMA_COLUMNS
        assert not unknown, (
            f"_get_user_or_404 SELECTs columns that don't exist on `users`: "
            f"{sorted(unknown)}. This is the root cause of issue #75 — "
            f"PostgREST returns HTTP 400 for unknown columns and the route "
            f"500s. Fix: remove these columns from the SELECT in "
            f"backend/routes/profile.py:_get_user_or_404."
        )
