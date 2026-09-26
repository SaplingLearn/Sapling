"""PKG-00: user_settings.learning_loop_beta is readable and patchable through
the existing settings endpoints (spec §7). Mirrors the #72 share_class_context
tests in test_profile_routes.py: the per-user half of the learning-loop gate
must be a real, whitelisted setting, and an unknown key must never reach the
database write."""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app
from models import SettingsResponse, UpdateSettingsBody
from routes.profile import _SETTINGS_COLS

client = TestClient(app)

USER_ID = "user_test_1"


def _mock_self():
    return patch("routes.profile.require_self", return_value=None)


def _tables(row=None):
    captured = {"updates": []}
    row = row if row is not None else {"user_id": USER_ID, "learning_loop_beta": False}

    def table_side_effect(name):
        m = MagicMock()
        if name == "user_settings":
            m.select.return_value = [row]
            m.update.side_effect = lambda data, filters: captured["updates"].append(data) or [{}]
        else:
            m.select.return_value = []
        return m

    return table_side_effect, captured


def test_learning_loop_beta_is_a_selected_settings_column():
    cols = {c.strip() for c in _SETTINGS_COLS.split(",")}
    assert "learning_loop_beta" in cols, "'learning_loop_beta' not in _SETTINGS_COLS"


def test_get_settings_returns_learning_loop_beta():
    table_side_effect, _ = _tables({"user_id": USER_ID, "learning_loop_beta": True})
    with _mock_self(), patch("routes.profile.table", side_effect=table_side_effect):
        r = client.get(f"/api/profile/{USER_ID}/settings")
    assert r.status_code == 200
    assert r.json()["learning_loop_beta"] is True


def test_learning_loop_beta_is_patchable():
    table_side_effect, captured = _tables()
    with _mock_self(), patch("routes.profile.table", side_effect=table_side_effect):
        r = client.patch(f"/api/profile/{USER_ID}/settings", json={"learning_loop_beta": True})
    assert r.status_code == 200
    assert len(captured["updates"]) == 1
    assert captured["updates"][0]["learning_loop_beta"] is True


def test_learning_loop_beta_can_be_turned_off():
    table_side_effect, captured = _tables({"user_id": USER_ID, "learning_loop_beta": True})
    with _mock_self(), patch("routes.profile.table", side_effect=table_side_effect):
        r = client.patch(f"/api/profile/{USER_ID}/settings", json={"learning_loop_beta": False})
    assert r.status_code == 200
    assert captured["updates"][0]["learning_loop_beta"] is False


def test_unknown_key_never_reaches_the_update():
    table_side_effect, captured = _tables()
    with _mock_self(), patch("routes.profile.table", side_effect=table_side_effect):
        r = client.patch(
            f"/api/profile/{USER_ID}/settings", json={"learning_loop_beta_override": True}
        )
    assert r.status_code == 200
    assert captured["updates"] == [], "an unknown settings key reached table().update"


def test_toggling_the_loop_flag_does_not_resync_class_context():
    """The loop opt-in is not a consent change: it must not schedule the #72
    class-context refresh or the #629 chunk-visibility resync."""
    table_side_effect, _ = _tables()
    with (
        _mock_self(),
        patch("routes.profile.table", side_effect=table_side_effect),
        patch("routes.profile.update_course_context") as refresh,
        patch("routes.profile.resync_user_chunk_visibility") as resync,
    ):
        r = client.patch(f"/api/profile/{USER_ID}/settings", json={"learning_loop_beta": True})
    assert r.status_code == 200
    refresh.assert_not_called()
    resync.assert_not_called()


def test_models_default_to_opted_out():
    assert UpdateSettingsBody().learning_loop_beta is None
    assert SettingsResponse(user_id=USER_ID).learning_loop_beta is False
