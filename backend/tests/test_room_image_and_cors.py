"""Room message ``image_url`` and the CORS allowlist (security review, 2026-11).

- a room message image is an <img> every member's browser fetches, so only
  the app's own room-image bucket is accepted, or it is a tracking pixel.
- localhost origins are on the credentialed CORS allowlist only on a
  local/test backend.
"""

from unittest.mock import patch

import pytest
from pydantic import ValidationError

import config
from models import ROOM_IMAGE_URL_MAX, SendMessageBody
from services.cors_origins import LOCAL_DEV_ORIGINS, allowed_origins


# ── room message image_url ───────────────────────────────────────────────────

SUPA = "https://abcd1234.supabase.co"
GOOD = f"{SUPA}/storage/v1/object/public/chat-images/room-1/user_1-1700000000000-cat.png"


@pytest.fixture
def supabase_url():
    with patch.object(config, "SUPABASE_URL", SUPA):
        yield


def _body(image_url):
    return SendMessageBody(user_id="u1", user_name="Alice", image_url=image_url)


def test_room_image_accepts_own_bucket(supabase_url):
    assert _body(GOOD).image_url == GOOD
    # The project origin is compared case-insensitively.
    assert _body(GOOD.replace("abcd1234", "ABCD1234")).image_url


def test_room_image_none_and_empty_pass(supabase_url):
    assert _body(None).image_url is None
    assert _body("").image_url == ""


@pytest.mark.parametrize(
    "bad",
    [
        "https://tracker.example/pixel.gif?u=1",
        "http://abcd1234.supabase.co/storage/v1/object/public/chat-images/a.png",
        "https://other.supabase.co/storage/v1/object/public/chat-images/a.png",
        "https://abcd1234.supabase.co.evil.example/storage/v1/object/public/chat-images/a.png",
        "https://abcd1234.supabase.co@evil.example/storage/v1/object/public/chat-images/a.png",
        f"{SUPA}/storage/v1/object/public/avatars/a.png",
        f"{SUPA}/storage/v1/object/public/chat-images/",
        f"{SUPA}/storage/v1/object/public/chat-images/../avatars/a.png",
        f"{SUPA}/storage/v1/object/public/chat-images/%2e%2e/avatars/a.png",
        f"{SUPA}/storage/v1/object/sign/chat-images/a.png",
        f"{SUPA}/rest/v1/users",
        "javascript:alert(1)",
        "data:image/png;base64,AAAA",
        GOOD + " ",
        GOOD + "x" * ROOM_IMAGE_URL_MAX,
    ],
)
def test_room_image_rejects_other_urls(supabase_url, bad):
    with pytest.raises(ValidationError):
        _body(bad)


def test_room_image_fails_closed_without_supabase_url():
    with patch.object(config, "SUPABASE_URL", ""):
        with pytest.raises(ValidationError):
            _body(GOOD)


def test_send_room_message_route_returns_422_for_foreign_image(supabase_url):
    from fastapi.testclient import TestClient
    from main import app

    r = TestClient(app).post(
        "/api/social/rooms/room-1/messages",
        json={"user_id": "u1", "user_name": "Alice", "image_url": "https://tracker.example/p.gif"},
    )
    assert r.status_code == 422


# ── CORS allowlist ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("env", ["production", "staging", "", "PRODUCTION"])
def test_cors_excludes_localhost_when_deployed(env):
    origins = allowed_origins("https://saplinglearn.com", env, [])
    assert not any("localhost" in o or "127.0.0.1" in o for o in origins)
    assert "https://saplinglearn.com" in origins
    assert "https://www.saplinglearn.com" in origins


@pytest.mark.parametrize("env", ["local", "test", " Local "])
def test_cors_includes_localhost_when_local(env):
    origins = allowed_origins("https://saplinglearn.com", env, [])
    for o in LOCAL_DEV_ORIGINS:
        assert o in origins


def test_cors_keeps_frontend_url_and_extras():
    origins = allowed_origins(
        "https://staging.saplinglearn.com/", "production", ["https://preview.example/", ""]
    )
    assert "https://staging.saplinglearn.com" in origins
    assert "https://preview.example" in origins
    assert "" not in origins
