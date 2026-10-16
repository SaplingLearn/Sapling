"""#620 GET /api/flags: client-visible only, signed-out defaults, no caching."""
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_signed_in_gets_client_visible_flags():
    with patch("routes.flags.get_session_user_id", return_value="u1"), \
         patch("routes.flags.feature_flags.resolved_client_flags",
               return_value={"hide_quiz": "on", "hide_tree": "on"}) as res:
        r = client.get("/api/flags")
    assert r.status_code == 200
    assert r.json() == {"flags": {"hide_quiz": "on", "hide_tree": "on"}}
    res.assert_called_once_with("u1")
    assert r.headers["cache-control"] == "private, no-store"


def test_signed_out_resolves_anonymously():
    with patch("routes.flags.get_session_user_id",
               side_effect=HTTPException(status_code=401, detail="no session")), \
         patch("routes.flags.feature_flags.resolved_client_flags", return_value={}) as res:
        r = client.get("/api/flags")
    assert r.status_code == 200
    res.assert_called_once_with(None)


def test_server_only_flags_never_leak(monkeypatch):
    from services import feature_flags as ff
    monkeypatch.setitem(ff.REGISTRY, "server_only",
                        ff.FlagDef("server_only", ("off", "on"), "test", False))
    with patch("routes.flags.get_session_user_id", return_value="u1"):
        r = client.get("/api/flags")
    assert "server_only" not in r.json()["flags"]
