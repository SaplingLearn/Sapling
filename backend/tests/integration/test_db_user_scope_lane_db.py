"""The integration lane really runs in the `db_user_scope` mode its env names (#115).

integration.yml runs this lane with the flag unset (``off``) on every PR that
touches backend/, supabase/ or scripts/ and on every push to main, and on
main (and a manual dispatch) runs it a second time with
``SAPLING_FLAG_DB_USER_SCOPE=enforce``, so every request a test
drives through the app (quiz, uploads, study days, gradescope links, …) also
runs as the student, under the RLS policies and grants. That second run is
only worth its minutes while the env var actually reaches the app and the
local PostgREST accepts the minted token. This module pins both, in whichever
mode the run is in, so a renamed variable or a broken key cannot turn the
enforce run into a silent second ``off`` run:

* a signed-in request's reads carry the student's token exactly when the
  mode is ``enforce`` (and never under ``off``);
* under ``enforce`` the local PostgREST accepts that token (a 200, not the
  503 a rejected token maps to) and the answer is the student's own rows,
  exactly what the same handler answers under ``off``.
"""
from __future__ import annotations

import os

import pytest

from tests.integration.conftest import USER_ACTIVE, USER_SECOND

pytestmark = pytest.mark.integration


def _lane_mode() -> str:
    mode = (os.getenv("SAPLING_FLAG_DB_USER_SCOPE") or "off").strip().lower()
    assert mode in ("off", "enforce"), (
        f"the integration lane runs under off or enforce, not {mode!r} (integration.yml)"
    )
    return mode


@pytest.fixture
def scoped_calls(monkeypatch):
    """Every subject a PostgREST call was user-scoped for, in call order."""
    from db import scope as db_scope
    from db import user_jwt

    user_jwt.clear_token_cache()
    seen: list[str] = []
    real = db_scope._user_headers

    def spy(subject: str) -> dict:
        seen.append(subject)
        return real(subject)

    monkeypatch.setattr(db_scope, "_user_headers", spy)
    yield seen
    user_jwt.clear_token_cache()


def test_the_lane_runs_in_the_mode_its_env_names(authed_client, scoped_calls):
    mode = _lane_mode()
    if mode == "enforce":
        from db import user_jwt

        assert not user_jwt.config_problems(), (
            f"enforce needs the local signing + anon keys: {user_jwt.config_problems()}"
        )

    r = authed_client.get("/api/auth/me")
    assert r.status_code == 200, r.text
    assert r.json()["user_id"] == USER_ACTIVE

    if mode == "enforce":
        assert scoped_calls and set(scoped_calls) == {USER_ACTIVE}, (
            "under enforce GET /api/auth/me must read as the student"
        )
    else:
        assert scoped_calls == [], "under off nothing may run user-scoped"


def test_a_scoped_read_returns_only_the_callers_rows(authed_client, other_user_client,
                                                     db_conn, scoped_calls):
    """GET /api/notes/user/{id} for each of two seeded students: the token is
    accepted (200) and each sees exactly the notes Postgres says are theirs."""
    mode = _lane_mode()
    for client, uid in ((authed_client, USER_ACTIVE), (other_user_client, USER_SECOND)):
        expected = {
            row["id"] for row in db_conn.execute(
                "SELECT id FROM notes WHERE user_id = %(u)s", {"u": uid},
            ).fetchall()
        }
        assert expected, f"precondition: the rich seed gives {uid} notes"
        r = client.get(f"/api/notes/user/{uid}")
        assert r.status_code == 200, f"[{mode}] {uid}: {r.status_code} {r.text[:200]}"
        body = r.json()
        notes = body.get("notes", body) if isinstance(body, dict) else body
        got = {n["id"] for n in notes}
        assert got == expected, f"[{mode}] {uid}: got {sorted(got)} expected {sorted(expected)}"
    if mode == "enforce":
        assert set(scoped_calls) == {USER_ACTIVE, USER_SECOND}
