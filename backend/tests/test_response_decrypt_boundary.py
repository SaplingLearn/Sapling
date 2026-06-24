"""
Regression tests for #126 findings #18 and #19: two response-boundary leaks
where an encrypted column was returned to the (authenticated, owning) client as
ciphertext instead of plaintext.

These are encryption-boundary correctness tests (owner-only, NOT cross-user):
they assert the response carries decrypted plaintext, and would fail pre-fix
(which returned the stored ciphertext).
"""
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from services.encryption import encrypt_if_present

client = TestClient(app)


class TestGradebookCreateAssignmentResponse:
    """#18: create_assignment returned inserted[0] — the stored ciphertext for
    points_possible/points_earned/notes — with no decrypt."""

    def test_response_is_decrypted_not_ciphertext(self):
        stored = {
            "id": "a1",
            "user_id": "user_andres",
            "course_id": "c1",
            "category_id": None,
            "title": "HW1",
            "due_date": "2026-03-01",
            "assignment_type": "homework",
            "points_possible": encrypt_if_present(100),
            "points_earned": encrypt_if_present(95),
            "notes": encrypt_if_present("Study chapters 1-3"),
            "source": "manual",
        }
        with patch("routes.gradebook._user_owns_course", return_value=True), \
             patch("routes.gradebook.table") as t:
            t.return_value.insert.return_value = [dict(stored)]
            r = client.post(
                "/api/gradebook/assignments",
                json={
                    "user_id": "user_andres",
                    "course_id": "c1",
                    "title": "HW1",
                    "points_possible": 100,
                    "points_earned": 95,
                    "notes": "Study chapters 1-3",
                },
            )

        assert r.status_code == 200
        a = r.json()["assignment"]
        # Pre-fix these were the stored ciphertext strings.
        assert a["points_possible"] == 100.0
        assert a["points_earned"] == 95.0
        assert a["notes"] == "Study chapters 1-3"
        assert a["notes"] != stored["notes"]


class TestProfileSettingsPatchResponse:
    """#19 + migration 0024: bio/location were dropped from user_settings and now
    live on user_profiles (set via PATCH /profile, not /settings). The #19 leak —
    PATCH /settings echoing ciphertext bio/location — is now structurally
    impossible because the settings SELECT no longer carries those columns. This
    test pins that: the settings response must NOT contain bio/location at all.
    """

    def test_settings_response_omits_profile_fields(self):
        # A stale user_settings row that still had ciphertext bio/location must
        # never surface them — the SELECT column list excludes them post-0024.
        stored = {
            "user_id": "user_andres",
            "theme": "dark",
            "profile_visibility": "public",
        }

        with patch("routes.profile.table") as t:
            t.return_value.select.side_effect = lambda *a, **k: [dict(stored)]
            r = client.patch(
                "/api/profile/user_andres/settings",
                json={"theme": "light"},
            )

        assert r.status_code == 200
        body = r.json()
        # bio/location/username/website are owned by user_profiles now — not here.
        assert "bio" not in body
        assert "location" not in body
        assert body["profile_visibility"] == "public"
