"""The integration truncate's direct-Postgres safety gate (#397), proven in the
DEFAULT hermetic lane.

This is pure URL logic with no database, so it runs in normal CI (not the opt-in
integration lane) — which is exactly where we want the guard proven: the autouse
truncate fixture opens a psycopg connection on SUPABASE_DB_URL that bypasses
PostgREST, and `_require_local_stack` only checks the *independent* SUPABASE_URL.
`backend/.env.staging` / `.env.production` both carry live direct-Postgres
strings, so a misconfigured SUPABASE_DB_URL would TRUNCATE real data. The gate
must RAISE (never skip) on anything non-local. A skip would read as "safe".
"""
import pytest

from tests.integration.conftest import _db_url_is_local, _require_local_db_url

_LOCAL_URLS = [
    "postgresql://postgres:postgres@127.0.0.1:54322/postgres",
    "postgresql://postgres:postgres@localhost:54322/postgres",
    "postgres://postgres:postgres@[::1]:54322/postgres",
]

_NON_LOCAL_URLS = [
    "postgresql://postgres:pw@db.abcdefgh.supabase.co:5432/postgres",
    "postgresql://postgres:pw@aws-0-us-east-1.pooler.supabase.com:6543/postgres",
    # The substring trap: contains "127.0.0.1"/"localhost" but resolves elsewhere.
    "postgresql://postgres:pw@127.0.0.1.evil.com:5432/postgres",
    "postgresql://postgres:pw@localhost.attacker.net:5432/postgres",
    "",
]


@pytest.mark.parametrize("url", _LOCAL_URLS)
def test_local_db_urls_are_accepted(url):
    assert _db_url_is_local(url) is True
    _require_local_db_url(url)  # must not raise


@pytest.mark.parametrize("url", _NON_LOCAL_URLS)
def test_non_local_db_urls_are_classified_non_local(url):
    assert _db_url_is_local(url) is False


@pytest.mark.parametrize("url", _NON_LOCAL_URLS)
def test_guard_raises_not_skips_on_non_local_url(url):
    """The AC: refuses a non-local SUPABASE_DB_URL by RAISING (a skip would be a
    silent false-safe). RuntimeError, not pytest.skip.Exception."""
    with pytest.raises(RuntimeError, match="SUPABASE_DB_URL"):
        _require_local_db_url(url)
