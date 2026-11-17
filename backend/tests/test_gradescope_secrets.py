"""Gradescope secrets (M18 option B): a password is used for one login and never
stored; legacy password rows convert to their session; no secret is echoed
in a 422 or shown by a model's repr."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests
from fastapi.testclient import TestClient

from main import app
from services import gradescope_service as gs
from services import request_limits
from services.encryption import bind, decrypt, encrypt
from tests.split_patches import patch_gradescope

client = TestClient(app)


def _cookies_bind(user_id="u1"):
    """The AAD binding of gradescope_credentials.cookies_encrypted (keyed on user_id)."""
    return bind("gradescope_credentials", "cookies_encrypted", user_id)

PASSWORD = "Sup3r-Secret-Pa55word"
BU_PASSWORD = "Bu-Secret-Pa55word"


@pytest.fixture(autouse=True)
def _clear_rate_state():
    request_limits._rate_state.clear()
    yield
    request_limits._rate_state.clear()


def _logged_in_conn(*, session_cookie="sess-value", signed="remember-value", domain="www.gradescope.com"):
    jar = requests.cookies.RequestsCookieJar()
    if session_cookie:
        jar.set("_gradescope_session", session_cookie, domain=domain, path="/")
    if signed:
        jar.set("signed_token", signed, domain=domain, path="/")
    jar.set("_gradescope_session", "other-site", domain="evil.example", path="/")
    return SimpleNamespace(session=SimpleNamespace(cookies=jar, close=MagicMock()))


# ── A password connect stores the session, never the password ───────────────


def test_password_connect_persists_no_password():
    saved = MagicMock()
    conn = _logged_in_conn()
    with (
        patch_gradescope("table", return_value=saved),
        patch.object(gs, "login", return_value=conn) as login,
    ):
        r = client.post("/api/gradescope/credentials", json={
            "user_id": "u1", "email": "student@example.edu", "password": PASSWORD,
        })
    assert r.status_code == 200
    login.assert_called_once_with("student@example.edu", PASSWORD, remember_me=True)
    conn.session.close.assert_called_once()
    payload = saved.upsert.call_args.args[0]
    assert payload["auth_mode"] == "cookies"
    assert payload["password_encrypted"] is None and payload["email_encrypted"] is None
    assert PASSWORD not in str(payload)
    blob = json.loads(decrypt(payload["cookies_encrypted"], bind=_cookies_bind()))
    assert blob == {"_gradescope_session": "sess-value", "signed_token": "remember-value", "via": "password"}
    assert PASSWORD not in json.dumps(blob)


def test_a_login_without_a_session_cookie_saves_nothing():
    saved = MagicMock()
    with (
        patch_gradescope("table", return_value=saved),
        patch.object(gs, "login", return_value=_logged_in_conn(session_cookie=None)),
    ):
        r = client.post("/api/gradescope/credentials", json={
            "user_id": "u1", "email": "student@example.edu", "password": PASSWORD,
        })
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "gradescope_auth_failed"
    saved.upsert.assert_not_called()


def test_remember_me_is_ticked_only_when_asked():
    session = MagicMock()
    session.get.side_effect = [
        SimpleNamespace(text='<form action="/login"><input name="authenticity_token" value="csrf"></form>',
                        raise_for_status=lambda: None),
    ]
    session.post.return_value = SimpleNamespace(
        status_code=200, history=[SimpleNamespace(status_code=302)],
        url="https://www.gradescope.com/account", text="",
    )
    with patch.object(gs, "_new_session", return_value=session):
        gs.login("student@example.edu", PASSWORD, remember_me=True)
    assert session.post.call_args.kwargs["data"]["session[remember_me]"] == "1"


# ── Legacy password rows convert on their next login ────────────────────────


def _legacy_creds():
    from services.gradescope.credentials import StoredCreds

    return StoredCreds(auth_mode="password", email="student@example.edu", password=PASSWORD,
                       connected_via="password", updated_at="2026-11-01T00:00:00+00:00")


def test_legacy_password_row_is_converted_on_its_next_login():
    creds_table = MagicMock()
    creds_table.update.return_value = [{"user_id": "u1"}]
    with (
        patch_gradescope("table", return_value=creds_table),
        patch_gradescope("_load_creds", return_value=_legacy_creds()),
        patch.object(gs, "login", return_value=_logged_in_conn()) as login,
        patch.object(gs, "list_student_courses", return_value=[]),
    ):
        r = client.get("/api/gradescope/courses", params={"user_id": "u1"})
    assert r.status_code == 200
    login.assert_called_once_with("student@example.edu", PASSWORD, remember_me=True)
    conversion = creds_table.update.call_args_list[0]
    fields = conversion.args[0]
    assert fields["auth_mode"] == "cookies"
    assert fields["password_encrypted"] is None and fields["email_encrypted"] is None
    assert json.loads(decrypt(fields["cookies_encrypted"], bind=_cookies_bind()))["via"] == "password"
    assert PASSWORD not in str(fields)
    # Only that password version: never a row the student re-saved meanwhile.
    assert conversion.kwargs["filters"] == {
        "user_id": "eq.u1", "auth_mode": "eq.password", "updated_at": "eq.2026-11-01T00:00:00+00:00",
    }


def test_sync_converts_a_legacy_row():
    from services.gradescope import sync as gs_sync

    creds_table = MagicMock()
    creds_table.update.return_value = [{"user_id": "u1"}]
    tables = {"gradescope_credentials": creds_table}
    with (
        patch("services.gradescope.credentials.table", side_effect=lambda n: tables[n]),
        patch.object(gs_sync, "_load_creds", return_value=_legacy_creds()),
        patch.object(gs, "login", return_value=_logged_in_conn()),
        patch.object(gs, "list_assignments", side_effect=gs.GradescopeFetchError("stop here")),
    ):
        outcome = gs_sync._run_linked_sync("u1", "gs1", "e1", "link")
    assert outcome.error_code  # stopped at the fetch, after the login
    fields = creds_table.update.call_args_list[0].args[0]
    assert fields["auth_mode"] == "cookies" and fields["password_encrypted"] is None


def test_a_failed_conversion_never_breaks_the_login():
    creds_table = MagicMock()
    creds_table.update.side_effect = RuntimeError("db down")
    with (
        patch_gradescope("table", return_value=creds_table),
        patch_gradescope("_load_creds", return_value=_legacy_creds()),
        patch.object(gs, "login", return_value=_logged_in_conn()),
        patch.object(gs, "list_student_courses", return_value=[{"id": "1"}]),
    ):
        r = client.get("/api/gradescope/courses", params={"user_id": "u1"})
    assert r.status_code == 200
    assert r.json()["courses"] == [{"id": "1"}]


@pytest.mark.parametrize(("login", "expected"), [
    ({"return_value": None}, "converted"),
    ({"side_effect": gs.GradescopeAuthError("bad password")}, "rejected"),
    ({"side_effect": gs.GradescopeFetchError("down")}, "unreachable"),
])
def test_retire_stored_password_outcomes(login, expected):
    from services.gradescope import credentials

    creds_table = MagicMock()
    creds_table.update.return_value = [{"user_id": "u1"}]
    if "return_value" in login:
        login = {"return_value": _logged_in_conn()}
    with (
        patch.object(credentials, "table", return_value=creds_table),
        patch.object(credentials, "_load_creds", return_value=_legacy_creds()),
        patch.object(gs, "login", **login),
    ):
        assert credentials.retire_stored_password("u1") == expected
    if expected == "converted":
        assert creds_table.update.call_args.args[0]["password_encrypted"] is None
    else:
        creds_table.update.assert_not_called()


def test_retire_script_dry_run_logs_in_to_nothing(capsys):
    import scripts.retire_gradescope_passwords as script

    with (
        patch.object(script, "_password_rows", return_value=[{"user_id": "u1"}, {"user_id": "u2"}]),
        patch.object(script, "retire_stored_password") as retire,
    ):
        summary = script.main([])
    retire.assert_not_called()
    assert summary["password_rows"] == 2
    assert "DRY RUN" in capsys.readouterr().out


def test_retire_script_apply_converts_and_can_drop_rejected():
    import scripts.retire_gradescope_passwords as script

    deleted = MagicMock()
    with (
        patch.object(script, "_password_rows", side_effect=[[{"user_id": "u1"}, {"user_id": "u2"}], []]),
        patch.object(script, "retire_stored_password", side_effect=["converted", "rejected"]),
        patch.object(script, "table", return_value=deleted),
    ):
        summary = script.main(["--apply", "--drop-rejected", "--pause", "0"])
    assert summary["converted"] == 1 and summary["rejected"] == 1 and summary["dropped"] == 1
    deleted.delete.assert_called_once_with({"user_id": "eq.u2", "auth_mode": "eq.password"})


# ── /status says how the session was obtained ───────────────────────────────


@pytest.mark.parametrize(("row", "via"), [
    ({"auth_mode": "password"}, "password"),
    ({"auth_mode": "cookies", "cookies_encrypted": encrypt(json.dumps({"_gradescope_session": "s", "via": "password"}), bind=_cookies_bind())}, "password"),
    ({"auth_mode": "cookies", "cookies_encrypted": encrypt(json.dumps({"_gradescope_session": "s", "via": "bu_sso"}), bind=_cookies_bind())}, "bu_sso"),
    ({"auth_mode": "cookies", "cookies_encrypted": encrypt(json.dumps({"_gradescope_session": "s"}), bind=_cookies_bind())}, "cookies"),
    ({"auth_mode": "cookies", "cookies_encrypted": "not-ciphertext"}, "cookies"),
])
def test_status_reports_connected_via(row, via):
    t = MagicMock()
    t.select.return_value = [{"needs_reauth": True, **row}]
    with patch_gradescope("table", return_value=t):
        body = client.get("/api/gradescope/status", params={"user_id": "u1"}).json()
    assert body["connected_via"] == via
    assert "cookies_encrypted" not in body


# ── 422s echo nothing the client sent ───────────────────────────────────────


@pytest.mark.parametrize(("path", "body", "secret"), [
    # A missing required field puts the WHOLE body in pydantic's `input`.
    ("/api/gradescope/credentials", {"email": "s@example.edu", "password": PASSWORD}, PASSWORD),
    ("/api/gradescope/credentials", {"user_id": "u1", "password": "x" * 1024 + PASSWORD}, PASSWORD),
    ("/api/gradescope/credentials/bu-sso", {"bu_username": "student", "bu_password": BU_PASSWORD}, BU_PASSWORD),
    ("/api/gradescope/credentials/bu-sso",
     {"user_id": "u1", "bu_username": "student", "bu_password": BU_PASSWORD, "duo_timeout_seconds": 1}, BU_PASSWORD),
])
def test_validation_422_echoes_no_secret(path, body, secret):
    r = client.post(path, json=body)
    assert r.status_code == 422
    assert secret not in r.text
    for err in r.json()["detail"]:
        assert "input" not in err
        assert "msg" in err and "loc" in err  # what lib/errorMessage.ts reads


def test_validation_422_drops_validator_exception_text():
    from main import _scrub_validation_errors

    errors = [{"type": "value_error", "loc": ("body", "x"), "msg": "Value error, bad",
               "input": "SECRET", "ctx": {"error": ValueError("SECRET")}},
              {"type": "too_long", "loc": ("body", "y"), "msg": "too long",
               "input": "SECRET", "ctx": {"max_length": 5}}]
    scrubbed = _scrub_validation_errors(errors)
    assert "SECRET" not in repr(scrubbed)
    assert "ctx" not in scrubbed[0]
    assert scrubbed[1]["ctx"] == {"max_length": 5}


# ── reprs show no secret ────────────────────────────────────────────────────


def test_models_hide_their_secrets():
    from routes.gradescope import BuSsoBody, CredentialsBody
    from services.gradescope.credentials import StoredCreds

    models = [
        CredentialsBody(user_id="u1", email="s@example.edu", password=PASSWORD,
                        gradescope_session="SESSION-COOKIE", signed_token="SIGNED-TOKEN"),
        BuSsoBody(user_id="u1", bu_username="student", bu_password=BU_PASSWORD),
        StoredCreds(auth_mode="password", email="s@example.edu", password=PASSWORD),
        StoredCreds(auth_mode="cookies", gradescope_session="SESSION-COOKIE", signed_token="SIGNED-TOKEN"),
    ]
    for m in models:
        for text in (repr(m), str(m), m.model_dump_json()):
            for secret in (PASSWORD, BU_PASSWORD, "SESSION-COOKIE", "SIGNED-TOKEN"):
                assert secret not in text, (type(m).__name__, secret)


# ── An expired session asks for what the student actually has ───────────────


@pytest.mark.parametrize(("via", "expected"), [
    ("password", "Enter your Gradescope password again"),
    ("bu_sso", "Sign in with BU again"),
    ("cookies", "copy the current"),
])
def test_expired_session_409_is_worded_for_how_it_was_connected(via, expected):
    from services.gradescope.credentials import StoredCreds

    creds = StoredCreds(auth_mode="cookies", gradescope_session="s", connected_via=via,
                        updated_at="2026-11-01T00:00:00+00:00")
    expired = gs.GradescopeAuthError(
        "Your Gradescope session has expired or was signed out. Sign in to "
        "Gradescope, then copy the current _gradescope_session cookie.")
    with (
        patch_gradescope("table", return_value=MagicMock()),
        patch_gradescope("_load_creds", return_value=creds),
        patch.object(gs, "login_with_cookies", side_effect=expired),
    ):
        r = client.get("/api/gradescope/courses", params={"user_id": "u1"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "gradescope_reauth_required"
    assert expected in r.json()["error"]["message"]
