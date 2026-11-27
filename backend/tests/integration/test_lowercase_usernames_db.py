"""The lowercase-usernames migration, against real Postgres.

Handles stored before writes were lowercased keep their case; the migration
lowercases each one EXCEPT where another row already holds the same name in a
different case (`user_profiles.username` is UNIQUE case-sensitively, so such
twins can exist, and lowercasing either would violate that constraint or merge
two people's handles). Run inside a rolled-back transaction: nothing persists.
"""
import pathlib

import pytest

pytestmark = pytest.mark.integration

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[2]
    / "db" / "migrations" / "20261115031302_lowercase_usernames.sql"
)

_PROFILES = {
    "itest-un-1": "ItestAlice",   # twin of -2: both left alone
    "itest-un-2": "itestalice",
    "itest-un-3": "ItestBob",     # no twin: lowercased
    "itest-un-4": "itestcarol",   # already lowercase: untouched
    "itest-un-5": None,           # no handle: untouched
    "itest-un-6": "ITESTDAVE",    # twins, neither lowercase: both left alone
    "itest-un-7": "ItestDave",
}


def _usernames(db_conn) -> dict:
    rows = db_conn.execute(
        "SELECT user_id, username FROM user_profiles WHERE user_id LIKE 'itest-un-%'"
    ).fetchall()
    return {r["user_id"]: r["username"] for r in rows}


def test_lowercases_every_handle_that_has_no_case_twin(db_conn):
    with db_conn.transaction(force_rollback=True):
        for user_id, username in _PROFILES.items():
            db_conn.execute(
                "INSERT INTO users (id, email) VALUES (%s, %s)",
                (user_id, f"{user_id}@example.com"),
            )
            db_conn.execute(
                "INSERT INTO user_profiles (user_id, username) VALUES (%s, %s)",
                (user_id, username),
            )

        db_conn.execute(MIGRATION.read_text(encoding="utf-8"))

        assert _usernames(db_conn) == {
            "itest-un-1": "ItestAlice",
            "itest-un-2": "itestalice",
            "itest-un-3": "itestbob",
            "itest-un-4": "itestcarol",
            "itest-un-5": None,
            "itest-un-6": "ITESTDAVE",
            "itest-un-7": "ItestDave",
        }

        db_conn.execute(MIGRATION.read_text(encoding="utf-8"))      # re-runnable on its own result
        assert _usernames(db_conn)["itest-un-3"] == "itestbob"
