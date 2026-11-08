"""Every public table has RLS on and gives anon / authenticated nothing.

Pins 20261108082151_rls_on_every_table.sql against the real local stack. Two
halves, because they fail differently:

* Catalog half (psycopg): `relrowsecurity` on every table, and no table or
  sequence privilege for anon or authenticated. A future migration that
  creates a table and forgets `ENABLE ROW LEVEL SECURITY` / the REVOKE fails
  here, which is the regression that left 35 production tables open
  (the June lockdown never became a migration).
* Wire half (PostgREST): the actual exposure. Every table is requested with the
  local stack's public anon key, the same kind of key the frontend ships, and
  must be refused. This is what an attacker with the bundle's key would try.

`room_messages` is the single documented exemption (see the migration header:
the local Realtime lane depends on anon postgres_changes, production already
has RLS on for it). It leaves this list when the realtime JWT bridge lands.
"""
import os

import httpx
import pytest

pytestmark = pytest.mark.integration

EXEMPT = frozenset({"room_messages"})

# `supabase start`'s fixed demo anon key (HS256, CLI default secret), the same
# value as frontend/.env.local.example. Public by design: it only works on a
# local stack.
LOCAL_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24iLCJleHAiOjE5ODM4MTI5OTZ9."
    "CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0"
)

UNPRIVILEGED = ("anon", "authenticated")


def _public_tables(db_conn) -> list[str]:
    rows = db_conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
    ).fetchall()
    return [r["tablename"] for r in rows]


def test_the_catalog_is_not_empty(db_conn):
    # Guards the loops below from passing vacuously on a stack with no schema.
    assert len(_public_tables(db_conn)) > 50


def test_every_public_table_has_rls_enabled(db_conn):
    rows = db_conn.execute(
        """
        SELECT c.relname
          FROM pg_class c
         WHERE c.relnamespace = 'public'::regnamespace
           AND c.relkind IN ('r', 'p')
           AND NOT c.relrowsecurity
        """
    ).fetchall()
    off = sorted({r["relname"] for r in rows} - EXEMPT)
    assert not off, (
        f"RLS is OFF on {off}. A new table needs `ALTER TABLE ... ENABLE ROW LEVEL "
        "SECURITY` and a REVOKE from anon/authenticated in its migration "
        "(pattern: 20261019005643_topic_checklists.sql)."
    )


def test_anon_and_authenticated_hold_no_table_privileges(db_conn):
    roles = [
        r["rolname"]
        for r in db_conn.execute(
            "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)", (list(UNPRIVILEGED),)
        ).fetchall()
    ]
    assert roles, "local stack has no anon/authenticated roles; is this Supabase?"
    rows = db_conn.execute(
        """
        SELECT r.role || ':' || p.priv || ':' || t.tablename AS leak
          FROM pg_tables t
         CROSS JOIN unnest(%s::text[]) AS r(role)
         CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE']) AS p(priv)
         WHERE t.schemaname = 'public'
           AND NOT (t.tablename = ANY(%s::text[]))
           AND has_table_privilege(r.role, format('public.%%I', t.tablename), p.priv)
         ORDER BY 1
        """,
        (roles, list(EXEMPT)),
    ).fetchall()
    leaks = [r["leak"] for r in rows]
    assert not leaks, f"unprivileged roles can still touch tables: {leaks}"


def test_anon_and_authenticated_hold_no_sequence_privileges(db_conn):
    rows = db_conn.execute(
        """
        SELECT grantee, object_name
          FROM information_schema.usage_privileges
         WHERE object_schema = 'public'
           AND object_type = 'SEQUENCE'
           AND grantee = ANY(%s)
        """,
        (list(UNPRIVILEGED),),
    ).fetchall()
    assert not rows, f"unprivileged roles hold sequence privileges: {rows}"


def test_service_role_keeps_full_table_access(db_conn):
    # The backend authenticates as service_role. Losing a grant here would turn
    # the lockdown into an outage, so pin it alongside the revokes.
    if not db_conn.execute("SELECT 1 FROM pg_roles WHERE rolname = 'service_role'").fetchone():
        pytest.skip("no service_role on this stack")
    rows = db_conn.execute(
        """
        SELECT p.priv || ':' || t.tablename AS missing
          FROM pg_tables t
         CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE']) AS p(priv)
         WHERE t.schemaname = 'public'
           AND NOT has_table_privilege('service_role', format('public.%I', t.tablename), p.priv)
         ORDER BY 1
        """
    ).fetchall()
    missing = [r["missing"] for r in rows]
    assert not missing, f"service_role lost access: {missing}"
    bypass = db_conn.execute(
        "SELECT rolbypassrls FROM pg_roles WHERE rolname = 'service_role'"
    ).fetchone()["rolbypassrls"]
    assert bypass, "service_role must bypass RLS or every backend query returns no rows"


def test_postgrest_refuses_every_table_to_the_anon_key(db_conn):
    base = (os.getenv("SUPABASE_URL") or "http://127.0.0.1:54321").rstrip("/")
    headers = {"apikey": LOCAL_ANON_KEY, "Authorization": f"Bearer {LOCAL_ANON_KEY}"}
    exposed = []
    with httpx.Client(timeout=10.0) as http:
        for t in _public_tables(db_conn):
            if t in EXEMPT:
                continue
            r = http.get(f"{base}/rest/v1/{t}", params={"select": "*", "limit": "1"},
                         headers=headers)
            # 401/403 = permission denied. 404 = not exposed at all. A 200 is a
            # leak even when the body is [] (it means the grant is there).
            if r.status_code not in (401, 403, 404):
                exposed.append(f"{t}={r.status_code}")
    assert not exposed, f"the public anon key can still read: {exposed}"
