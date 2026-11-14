"""Admin cosmetic image upload goes through the backend.

The admin screen used to write straight to a `cosmetic-assets` storage bucket
from the browser with the public anon key. `POST /api/admin/cosmetics/assets`
replaces it: admin-only, the service-role storage helper's type and size
checks, and an audit row.
"""
import base64
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from tests.split_patches import patch_admin

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()


def _client():
    from main import app

    return TestClient(app)


def test_stores_the_asset_and_returns_its_url():
    with patch("routes.admin.require_admin"), \
         patch("routes.admin.get_session_user_id", return_value="admin1"), \
         patch_admin("upload_cosmetic_asset",
                     return_value="https://cdn/cosmetics/k.png") as up, \
         patch_admin("log_admin_action") as audit:
        r = _client().post("/api/admin/cosmetics/assets",
                           json={"file_base64": PNG, "content_type": "image/png"})

    assert r.status_code == 200
    assert r.json() == {"asset_url": "https://cdn/cosmetics/k.png"}
    key, data, content_type = up.call_args.args
    # The key is minted server-side, never taken from the client.
    assert len(key) == 32 and all(c in "0123456789abcdef" for c in key)
    assert data == base64.b64decode(PNG)
    assert content_type == "image/png"
    assert audit.call_args.kwargs["action"] == "cosmetic.asset_upload"
    assert audit.call_args.kwargs["actor_id"] == "admin1"


def test_non_admins_are_refused_before_anything_is_stored():
    def deny(_request):
        raise HTTPException(status_code=403, detail="Admin only")

    with patch("routes.admin.require_admin", side_effect=deny), \
         patch_admin("upload_cosmetic_asset") as up:
        r = _client().post("/api/admin/cosmetics/assets",
                           json={"file_base64": PNG, "content_type": "image/png"})

    assert r.status_code == 403
    up.assert_not_called()


def test_bad_base64_is_a_400():
    with patch("routes.admin.require_admin"), \
         patch("routes.admin.get_session_user_id", return_value="admin1"), \
         patch_admin("upload_cosmetic_asset") as up:
        r = _client().post("/api/admin/cosmetics/assets",
                           json={"file_base64": "not base64!!", "content_type": "image/png"})

    assert r.status_code == 400
    up.assert_not_called()


def test_the_storage_helper_type_check_applies():
    """No mock on the helper's validation: an SVG (scriptable) is refused."""
    with patch("routes.admin.require_admin"), \
         patch("routes.admin.get_session_user_id", return_value="admin1"), \
         patch("services.storage_service.httpx.put") as put:
        r = _client().post(
            "/api/admin/cosmetics/assets",
            json={"file_base64": base64.b64encode(b"<svg/>").decode(),
                  "content_type": "image/svg+xml"},
        )

    assert r.status_code == 415
    put.assert_not_called()
