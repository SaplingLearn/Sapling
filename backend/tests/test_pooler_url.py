"""Tests for scripts.pooler_url — the pure URI-assembly logic (#508).

The password round trip is the one that matters. `urlparse()` returns the
password STILL percent-encoded, so re-quoting it double-escapes, and the
resulting URI authenticates as the literal escape text rather than the real
password. Supabase generates passwords containing reserved characters, so this
is reached in practice, and it surfaces as "password authentication failed" —
indistinguishable from simply having the wrong secret, which is what makes it
expensive to diagnose.
"""
from urllib.parse import urlparse


def _env(tmp_path, db_url: str):
    p = tmp_path / ".env.test"
    p.write_text(f"SUPABASE_URL=https://ref.supabase.co\nSUPABASE_DB_URL={db_url}\n")
    return str(p)


class TestPasswordEncoding:
    def test_a_password_with_reserved_characters_survives_the_round_trip(self, tmp_path):
        """`p@ss/word` is stored percent-encoded and must come back out the same.

        Before the fix this emitted `p%2540ss%252Fword` — the escapes escaped.
        """
        from scripts.pooler_url import build

        env = _env(tmp_path, "postgresql://postgres:p%40ss%2Fword@db.abcd.supabase.co:5432/postgres")
        uri = build(env, "aws-1-us-west-2")

        assert "p%40ss%2Fword" in uri
        assert "%25" not in uri, "password was double-encoded"
        assert urlparse(uri).password == "p%40ss%2Fword"

    def test_a_plain_password_is_unchanged(self, tmp_path):
        from scripts.pooler_url import build

        env = _env(tmp_path, "postgresql://postgres:simplepw@db.abcd.supabase.co:5432/postgres")

        assert "simplepw" in build(env, "aws-1-us-west-2")


class TestUriShape:
    def test_the_username_carries_the_project_ref(self, tmp_path):
        """The pooler rejects a bare `postgres` user — this is the detail most
        easily missed when assembling the URI by hand."""
        from scripts.pooler_url import build

        env = _env(tmp_path, "postgresql://postgres:pw@db.abcd.supabase.co:5432/postgres")

        assert build(env, "aws-1-us-west-2").startswith("postgresql://postgres.abcd:")

    def test_session_mode_port(self, tmp_path):
        """5432, never 6543 — transaction mode drops the session-level
        behaviour psycopg and DDL rely on."""
        from scripts.pooler_url import build

        env = _env(tmp_path, "postgresql://postgres:pw@db.abcd.supabase.co:5432/postgres")
        uri = build(env, "aws-1-us-west-2")

        assert ":5432/postgres" in uri
        assert "6543" not in uri


class TestPoolerHost:
    def test_an_explicit_cluster_prefix_is_preserved(self):
        """The cluster number is not derivable from the region, so an explicit
        prefix must survive untouched."""
        from scripts.pooler_url import pooler_host

        assert pooler_host("aws-1-us-west-2") == "aws-1-us-west-2.pooler.supabase.com"

    def test_a_bare_region_assumes_cluster_zero(self):
        """Documented as a guess, not a derivation — kept so a bare region is
        still usable, but it is why the dashboard is the real source."""
        from scripts.pooler_url import pooler_host

        assert pooler_host("us-west-2") == "aws-0-us-west-2.pooler.supabase.com"

    def test_a_full_host_passes_through(self):
        from scripts.pooler_url import pooler_host

        host = "aws-1-us-west-2.pooler.supabase.com"
        assert pooler_host(host) == host


class TestMask:
    def test_mask_hides_the_password(self):
        """The default output is meant to be safe to paste into a chat or an
        issue, so the masking has to actually hold."""
        from scripts.pooler_url import mask

        masked = mask("postgresql://postgres.abcd:sup3rs3cret@aws-1-us-west-2.pooler.supabase.com:5432/postgres")

        assert "sup3rs3cret" not in masked
        assert "postgres.abcd" in masked
