"""PKG-00 (reopened, CodeRabbit PR #673): user_settings.learning_loop_beta is a
staff/QA toggle set by SQL only (spec amendment A14, landing separately: the
loop becomes the default for every student, with no opt-in). The student-facing
settings path never names the column:

- a student cannot PATCH it on or off, and
- deploying the code before migration 20260926231744_learning_loop_beta.sql
  cannot break settings GET/PATCH, because nothing on that path selects it.

learning.gate still reads the column itself, and fails closed (False, no
exception) when the read errors, including PostgREST's 400 for a missing column.
"""

import inspect
from unittest.mock import MagicMock, patch

import httpx
from fastapi.testclient import TestClient
from test_learning_loop_invariants import reload_gate

import routes.profile
from main import app
from models import SettingsResponse, UpdateSettingsBody

client = TestClient(app)

USER_ID = "user_test_1"
FLAG = "learning_loop_beta"


def _mock_self():
    return patch("routes.profile.require_self", return_value=None)


def _tables():
    """user_settings behaves like PostgREST: select returns only the columns it
    was asked for, even though the stored row also holds the loop flag."""
    stored = {c.strip(): None for c in routes.profile._SETTINGS_COLS.split(",")}
    stored.update({"user_id": USER_ID, "theme": "light", FLAG: True})
    captured = {"selects": [], "updates": []}

    def select(cols, filters=None, **_):
        captured["selects"].append(cols)
        return [{c.strip(): stored[c.strip()] for c in cols.split(",")}]

    def table_side_effect(name):
        m = MagicMock()
        if name == "user_settings":
            m.select.side_effect = select
            m.update.side_effect = lambda data, filters: captured["updates"].append(data) or [{}]
        else:
            m.select.return_value = []
        return m

    return table_side_effect, captured


def test_learning_loop_beta_is_not_a_selected_settings_column():
    cols = {c.strip() for c in routes.profile._SETTINGS_COLS.split(",")}
    assert FLAG not in cols, "the student settings select must not name the loop flag"


def test_settings_route_module_never_names_the_column():
    """The deploy-race guarantee: nothing in routes/profile.py references the
    column, so the student path works whether or not the migration has run."""
    assert FLAG not in inspect.getsource(routes.profile)


def test_get_settings_has_no_learning_loop_beta_key():
    table_side_effect, captured = _tables()
    with _mock_self(), patch("routes.profile.table", side_effect=table_side_effect):
        r = client.get(f"/api/profile/{USER_ID}/settings")
    assert r.status_code == 200
    assert FLAG not in r.json()
    assert captured["selects"], "GET did not read user_settings"
    assert all(FLAG not in cols for cols in captured["selects"])


def test_patch_learning_loop_beta_alone_writes_nothing():
    """Unknown keys are dropped by UpdateSettingsBody (pydantic's default
    extra='ignore'), so the PATCH is a 200 no-op: no write, no resync."""
    table_side_effect, captured = _tables()
    with (
        _mock_self(),
        patch("routes.profile.table", side_effect=table_side_effect),
        patch("routes.profile.update_course_context") as refresh,
        patch("routes.profile.resync_user_chunk_visibility") as resync,
    ):
        r = client.patch(f"/api/profile/{USER_ID}/settings", json={FLAG: True})
    assert r.status_code == 200
    assert captured["updates"] == [], "a student PATCH reached table().update"
    assert FLAG not in r.json()
    refresh.assert_not_called()
    resync.assert_not_called()


def test_patch_with_a_real_setting_drops_learning_loop_beta():
    table_side_effect, captured = _tables()
    with _mock_self(), patch("routes.profile.table", side_effect=table_side_effect):
        r = client.patch(f"/api/profile/{USER_ID}/settings", json={"theme": "dark", FLAG: True})
    assert r.status_code == 200
    assert len(captured["updates"]) == 1
    written = captured["updates"][0]
    assert written["theme"] == "dark"
    assert FLAG not in written, "learning_loop_beta reached table().update"


def test_allow_list_drops_learning_loop_beta_even_if_the_model_passes_it():
    """Defence in depth: the body model drops unknown JSON keys itself, so a
    request alone never reaches the ALLOWED filter. Widen model_dump so the
    flag (and other non-whitelisted keys) do reach it; they must still be
    dropped before table().update."""
    real_dump = UpdateSettingsBody.model_dump

    def dump_with_unlisted_keys(self, *args, **kwargs):
        return {**real_dump(self, *args, **kwargs), FLAG: True, "is_admin": True}

    table_side_effect, captured = _tables()
    with (
        _mock_self(),
        patch("routes.profile.table", side_effect=table_side_effect),
        patch.object(UpdateSettingsBody, "model_dump", dump_with_unlisted_keys),
    ):
        r = client.patch(f"/api/profile/{USER_ID}/settings", json={"theme": "dark"})
    assert r.status_code == 200
    assert len(captured["updates"]) == 1
    written = captured["updates"][0]
    assert written["theme"] == "dark"
    assert FLAG not in written, "learning_loop_beta passed the ALLOWED filter"
    assert "is_admin" not in written, "an unknown key reached table().update"


def test_models_have_no_learning_loop_beta_field():
    assert FLAG not in UpdateSettingsBody.model_fields
    assert FLAG not in SettingsResponse.model_fields


def test_gate_never_reads_the_column(monkeypatch):
    """PKG-14b (spec §7 "After launch"): the retired toggle is never read, so
    code deployed before (or after) the column's migration behaves the same —
    even with PostgREST answering 400 / 42703 for the column, the gate is ON
    and db.connection is never reached. (Replaces the build-phase
    test_gate_fails_closed_when_the_column_is_missing.)"""
    import db.connection as dbconn

    gate = reload_gate(monkeypatch, None)

    def missing_column(url, **kwargs):
        return httpx.Response(
            400,
            json={"code": "42703", "message": f"column user_settings.{FLAG} does not exist"},
            request=httpx.Request("GET", url),
        )

    dbconn._client.get.side_effect = missing_column
    assert gate.learning_loop_active("user_andres") is True
    assert not dbconn._client.get.called, "the post-launch gate reached db.connection"
