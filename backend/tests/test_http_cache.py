"""Tests for HTTP conditional-GET caching (#99): the http_cache helper and the
two instrumented endpoints (notes list, profile settings)."""
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from services import http_cache

client = TestClient(app)


def _req(if_none_match=None):
    headers = {}
    if if_none_match is not None:
        headers["if-none-match"] = if_none_match
    return SimpleNamespace(headers=headers)


# ── helper unit tests ────────────────────────────────────────────────────────

class TestHelper:
    def test_make_etag_deterministic_and_quoted(self):
        a = http_cache.make_etag("x", 1, "2026")
        b = http_cache.make_etag("x", 1, "2026")
        assert a == b
        assert a.startswith('"') and a.endswith('"')

    def test_make_etag_changes_with_input(self):
        assert http_cache.make_etag("x", 1) != http_cache.make_etag("x", 2)
        # unit-separator join → no collision between (["a","b"]) and (["a b"]).
        assert http_cache.make_etag("a", "b") != http_cache.make_etag("a b")

    def test_conditional_returns_304_on_match(self):
        etag = http_cache.make_etag("v1")
        resp = http_cache.conditional(_req(if_none_match=etag), etag)
        assert resp is not None and resp.status_code == 304
        assert resp.headers["etag"] == etag
        assert resp.headers["cache-control"].startswith("private")

    def test_conditional_none_on_mismatch_or_absent(self):
        etag = http_cache.make_etag("v1")
        assert http_cache.conditional(_req(if_none_match='"other"'), etag) is None
        assert http_cache.conditional(_req(), etag) is None

    def test_conditional_matches_weak_prefix_and_list(self):
        etag = http_cache.make_etag("v1")
        assert http_cache.conditional(_req(if_none_match=f'W/{etag}'), etag) is not None
        assert http_cache.conditional(_req(if_none_match=f'"a", {etag}, "b"'), etag) is not None
        assert http_cache.conditional(_req(if_none_match="*"), etag) is not None


# ── GET /api/notes/user/{user_id} ────────────────────────────────────────────

class TestNotesListETag:
    def _notes(self, updated_at="2026-04-01T00:00:00Z"):
        return [{"id": "n1", "title": "T", "body": "B", "updated_at": updated_at}]

    def test_etag_304_and_change(self):
        async def fake_list(user_id, offering_id=None):
            return self._notes()
        with patch("routes.notes.list_notes", side_effect=fake_list):
            r1 = client.get("/api/notes/user/u1")
            assert r1.status_code == 200
            assert r1.headers["cache-control"].startswith("private")
            etag = r1.headers["etag"]
            r2 = client.get("/api/notes/user/u1", headers={"If-None-Match": etag})
        assert r2.status_code == 304

        async def fake_list_changed(user_id, offering_id=None):
            return self._notes("2026-06-01T00:00:00Z")
        with patch("routes.notes.list_notes", side_effect=fake_list_changed):
            r3 = client.get("/api/notes/user/u1", headers={"If-None-Match": etag})
        assert r3.status_code == 200
        assert r3.headers["etag"] != etag


# ── GET /api/profile/{user_id}/settings ──────────────────────────────────────

class TestSettingsETag:
    def test_etag_304_and_change(self):
        with patch("routes.profile._get_or_create_settings",
                   return_value={"user_id": "u1", "theme": "light", "updated_at": "2026-04-01T00:00:00Z"}):
            r1 = client.get("/api/profile/u1/settings")
            assert r1.status_code == 200
            assert r1.headers["cache-control"].startswith("private")
            etag = r1.headers["etag"]
            r2 = client.get("/api/profile/u1/settings", headers={"If-None-Match": etag})
        assert r2.status_code == 304

        with patch("routes.profile._get_or_create_settings",
                   return_value={"user_id": "u1", "theme": "dark", "updated_at": "2026-06-01T00:00:00Z"}):
            r3 = client.get("/api/profile/u1/settings", headers={"If-None-Match": etag})
        assert r3.status_code == 200
        assert r3.headers["etag"] != etag
