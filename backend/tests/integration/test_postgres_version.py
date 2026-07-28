"""Postgres major-version drift guard (#441).

Local/CI Postgres is pinned to PG15 via `db.major_version` in
`supabase/config.toml`, matching staging/prod — the whole point of the
deterministic local/CI lane is that it tests what production actually runs.
PR #440 had bumped local/CI to PG17 for local-dev/CI stack consistency
(consistency is preserved here too: local and CI both still follow the same
config.toml pin, just at 15 instead of 17); #441 tracked the resulting skew
against staging/prod, which this pin closes.

This test runs against the REAL server (via the `db_conn` psycopg fixture,
never a mock), so a future edit to config.toml — or a local stack that
predates this pin and was never reset (see the "Postgres version"
troubleshooting entry in docs/local-supabase.md) — fails LOUDLY here instead
of silently reintroducing the skew.

Placement: this file lives in the opt-in integration suite
(`backend/tests/integration/`, RUN_INTEGRATION=1) rather than the browser-lane
E2E spec, because `.github/workflows/integration.yml` boots the local Supabase
stack from empty and runs `RUN_INTEGRATION=1 pytest -m integration` on every
push to main — i.e. this actually executes in CI, against the same
`supabase start` (config.toml-pinned) Postgres the browser lane
(`.github/workflows/e2e.yml`) also boots.
"""
import pytest

pytestmark = pytest.mark.integration

EXPECTED_MAJOR_VERSION = 15


def test_server_major_version_matches_config_toml_pin(db_conn):
    row = db_conn.execute("SHOW server_version_num").fetchone()
    version_num = int(row["server_version_num"])
    # server_version_num is e.g. 150008 for 15.8, 170004 for 17.4 — major
    # version is the leading two digits for every currently supported PG
    # release (10 through 18).
    major = version_num // 10000
    assert major == EXPECTED_MAJOR_VERSION, (
        f"Postgres server_version_num={version_num} (major {major}) but "
        f"supabase/config.toml pins db.major_version = {EXPECTED_MAJOR_VERSION} "
        "to match staging/prod (#441). Either config.toml drifted from this "
        "running server, or this is a stale local stack provisioned before "
        "the pin — its Postgres container doesn't get swapped just because "
        "config.toml changed. Reset it: scripts/local-db-reset.sh, or a full "
        "`supabase stop` + `supabase start` if that isn't enough (see "
        "docs/local-supabase.md's 'Postgres version' troubleshooting entry)."
    )
