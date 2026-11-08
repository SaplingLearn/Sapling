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

Step 2a (20261108092633_rls_app_auth_helpers.sql) is pinned at the bottom:
function EXECUTE hygiene (no public function callable by anon/authenticated,
every backend RPC callable by service_role, the default privileges that keep
it that way for future functions), the `app_auth.uid()` claim contract, and
the narrowed room_messages privileges.
"""
import os
import re
from pathlib import Path

import httpx
import psycopg
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


# ── Step 2a: function EXECUTE, app_auth, room_messages ─────────────────────

# Every function the backend calls through PostgREST (`db.connection.rpc`), as
# service_role. canopy_active_users is the pre-#654 image's metric RPC, kept
# until no deployed image calls it (20260921055024_canopy_metrics.sql).
BACKEND_RPCS = frozenset({
    "apply_mastery_delta",           # services/graph_service.py
    "canopy_active_users",           # previous image, routes/internal_metrics.py
    "canopy_metrics",                # routes/internal_metrics.py (METRICS_RPC)
    "claim_documents_for_indexing",  # services/index_sweeper.py
    "match_course_chunks",           # services/rag_service.py
})

APP_AUTH_FUNCTIONS = frozenset({
    "uid", "is_room_member", "owns_room", "owns_enrollment", "enrolled_in_offering",
})

_BACKEND = Path(__file__).resolve().parents[2]

# Non-extension routines in a schema. Extension members (pg_depend deptype
# 'e', i.e. pgvector's type I/O, operators and distance functions) are left
# at their install-time ACL on purpose: they are SECURITY INVOKER C functions
# with no table access, and an authenticated `match_course_chunks` call (step
# 2c) runs `<=>` as the caller. See the migration header.
_OWN_ROUTINES = """
    SELECT p.oid, p.proname, p.oid::regprocedure::text AS sig
      FROM pg_proc p
     WHERE p.pronamespace = %s::regnamespace
       AND NOT EXISTS (SELECT 1 FROM pg_depend d
                        WHERE d.classid = 'pg_proc'::regclass
                          AND d.objid = p.oid AND d.deptype = 'e')
"""


def _existing_roles(db_conn, names) -> list[str]:
    return [
        r["rolname"]
        for r in db_conn.execute(
            "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)", (list(names),)
        ).fetchall()
    ]


def _backend_rpc_call_sites() -> set[str]:
    """Function names the backend passes to `rpc(...)`, by source scan.

    Literal first arguments, plus a module-level `NAME = "fn"` constant used as
    the argument (routes/internal_metrics.py's METRICS_RPC)."""
    names: set[str] = set()
    for path in _BACKEND.rglob("*.py"):
        rel = path.relative_to(_BACKEND).parts
        if rel[0] in {"venv", ".venv", "tests"} or "site-packages" in rel:
            continue
        src = path.read_text(encoding="utf-8", errors="replace")
        if "rpc(" not in src:
            continue
        names.update(re.findall(r"\brpc\(\s*[\"'](\w+)[\"']", src))
        for const in re.findall(r"\brpc\(\s*([A-Z][A-Z0-9_]*)\b", src):
            m = re.search(rf"^{const}\s*=\s*[\"'](\w+)[\"']", src, re.MULTILINE)
            if m:
                names.add(m.group(1))
    return names


def test_backend_rpc_list_matches_the_call_sites():
    # The DB checks below are only as good as BACKEND_RPCS. A new rpc("x")
    # call must be listed (and granted to service_role) or this fails.
    found = _backend_rpc_call_sites()
    assert found, "found no rpc( call sites; did db.connection.rpc move?"
    missing = sorted(found - BACKEND_RPCS)
    assert not missing, f"backend calls RPCs this test does not pin: {missing}"


def test_anon_and_authenticated_cannot_execute_public_functions(db_conn):
    roles = _existing_roles(db_conn, UNPRIVILEGED)
    assert roles, "local stack has no anon/authenticated roles; is this Supabase?"
    rows = db_conn.execute(_OWN_ROUTINES, ("public",)).fetchall()
    assert rows, "no functions in public; the catalog looks empty"
    leaks = sorted(
        f"{role}:{r['sig']}"
        for r in rows
        for role in roles
        if db_conn.execute(
            "SELECT has_function_privilege(%s, %s::oid, 'EXECUTE') AS ok",
            (role, r["oid"]),
        ).fetchone()["ok"]
    )
    assert not leaks, (
        f"public functions callable with the anon key (/rest/v1/rpc): {leaks}. "
        "A new function needs REVOKE ALL ... FROM PUBLIC, anon, authenticated "
        "(pattern: 20261108092633_rls_app_auth_helpers.sql)."
    )


def test_service_role_can_execute_every_backend_rpc(db_conn):
    if not _existing_roles(db_conn, ["service_role"]):
        pytest.skip("no service_role on this stack")
    rows = db_conn.execute(
        """
        SELECT p.proname,
               bool_and(has_function_privilege('service_role', p.oid, 'EXECUTE')) AS ok
          FROM pg_proc p
         WHERE p.pronamespace = 'public'::regnamespace
           AND p.proname = ANY(%s)
         GROUP BY p.proname
        """,
        (sorted(BACKEND_RPCS),),
    ).fetchall()
    present = {r["proname"]: r["ok"] for r in rows}
    absent = sorted(BACKEND_RPCS - present.keys())
    assert not absent, f"backend RPCs missing from the schema: {absent}"
    denied = sorted(name for name, ok in present.items() if not ok)
    assert not denied, f"service_role cannot execute backend RPCs: {denied}"


def test_service_role_can_execute_every_own_public_function(db_conn):
    # Broader than the RPC list: an RPC added without updating BACKEND_RPCS is
    # still caught here, because the backend only ever runs as service_role.
    if not _existing_roles(db_conn, ["service_role"]):
        pytest.skip("no service_role on this stack")
    rows = db_conn.execute(_OWN_ROUTINES, ("public",)).fetchall()
    denied = sorted(
        r["sig"]
        for r in rows
        if not db_conn.execute(
            "SELECT has_function_privilege('service_role', %s::oid, 'EXECUTE') AS ok",
            (r["oid"],),
        ).fetchone()["ok"]
    )
    assert not denied, f"service_role cannot execute: {denied}"


def test_new_functions_default_to_service_role_only(db_conn):
    # The default privileges are what keep the next migration's function off
    # /rest/v1/rpc for anon. db_conn is the migration role (postgres), so a
    # function created here gets exactly what a migration's would. Rolled back.
    roles = _existing_roles(db_conn, ("anon", "authenticated", "service_role"))
    if set(roles) != {"anon", "authenticated", "service_role"}:
        pytest.skip("needs the Supabase roles")
    with db_conn.transaction() as tx:
        db_conn.execute(
            "CREATE FUNCTION public._rls_2a_probe() RETURNS int "
            "LANGUAGE sql AS 'SELECT 1'"
        )
        db_conn.execute(
            "CREATE FUNCTION app_auth._rls_2a_probe() RETURNS int "
            "LANGUAGE sql AS 'SELECT 1'"
        )
        got = db_conn.execute(
            """
            SELECT r.role, s.schema,
                   has_function_privilege(r.role, s.schema || '._rls_2a_probe()',
                                          'EXECUTE') AS ok
              FROM unnest(ARRAY['anon','authenticated','service_role']) r(role)
             CROSS JOIN unnest(ARRAY['public','app_auth']) s(schema)
            """
        ).fetchall()
        raise psycopg.Rollback(tx)
    privs = {(r["schema"], r["role"]): r["ok"] for r in got}
    assert privs == {
        ("public", "anon"): False,
        ("public", "authenticated"): False,
        ("public", "service_role"): True,
        ("app_auth", "anon"): False,
        ("app_auth", "authenticated"): True,
        ("app_auth", "service_role"): True,
    }


def test_app_auth_helpers_are_executable_by_authenticated_and_service_only(db_conn):
    roles = _existing_roles(db_conn, ("anon", "authenticated", "service_role"))
    rows = db_conn.execute(_OWN_ROUTINES, ("app_auth",)).fetchall()
    assert {r["proname"] for r in rows} >= APP_AUTH_FUNCTIONS
    expect = {"anon": False, "authenticated": True, "service_role": True}
    wrong = sorted(
        f"{role}:{r['sig']}"
        for r in rows
        if r["proname"] in APP_AUTH_FUNCTIONS
        for role in roles
        if db_conn.execute(
            "SELECT has_function_privilege(%s, %s::oid, 'EXECUTE') AS ok",
            (role, r["oid"]),
        ).fetchone()["ok"] != expect[role]
    )
    assert not wrong, f"app_auth EXECUTE is wrong for: {wrong}"
    # app_auth must not be a PostgREST-exposed schema: config.toml lists
    # public and graphql_public only, and the helpers are not RPCs.
    config = (_BACKEND.parent / "supabase" / "config.toml").read_text()
    exposed = re.search(r"^schemas\s*=\s*\[(.*?)\]", config, re.MULTILINE)
    assert exposed and "app_auth" not in exposed.group(1)


@pytest.mark.parametrize(
    ("claims", "expected"),
    [
        (None, None),                                              # no request
        ("", None),                                                # empty setting
        ('{"iss": "supabase-demo", "sub": "user_1", "role": "authenticated"}', None),
        ('{"sub": "user_1", "role": "authenticated"}', None),      # no issuer
        ('{"iss": "sapling-realtime", "sub": "user_1"}', None),    # 2e's token
        ('{"iss": "sapling-api", "sub": ""}', None),               # empty sub
        ('{"iss": "sapling-api"}', None),                          # no sub
        ('{"iss": "sapling-api", "sub": "user_1", "role": "authenticated"}', "user_1"),
    ],
)
def test_app_auth_uid_only_trusts_backend_minted_claims(db_conn, claims, expected):
    # set_config(..., is_local => true) is what PostgREST does per request; the
    # transaction keeps it off the shared session connection.
    with db_conn.transaction() as tx:
        if claims is not None:
            db_conn.execute("SELECT set_config('request.jwt.claims', %s, true)", (claims,))
        got = db_conn.execute("SELECT app_auth.uid() AS uid").fetchone()["uid"]
        raise psycopg.Rollback(tx)
    assert got == expected


def test_room_messages_keeps_only_anon_select(db_conn):
    # anon SELECT stays until the step-2e JWT bridge: local/CI live chat rides
    # Realtime postgres_changes as anon, and Realtime needs SELECT. Nothing
    # else is needed by anyone but the backend (service_role).
    roles = _existing_roles(db_conn, UNPRIVILEGED)
    if not roles:
        pytest.skip("needs the Supabase roles")
    forbidden = {
        "anon": ["INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"],
        "authenticated": ["INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"],
    }
    leaks = sorted(
        f"{role}:{priv}"
        for role in roles
        for priv in forbidden[role]
        if db_conn.execute(
            "SELECT has_table_privilege(%s, 'public.room_messages', %s) AS ok",
            (role, priv),
        ).fetchone()["ok"]
    )
    assert not leaks, f"room_messages privileges still held: {leaks}"
    if "anon" in roles:
        assert db_conn.execute(
            "SELECT has_table_privilege('anon', 'public.room_messages', 'SELECT') AS ok"
        ).fetchone()["ok"], (
            "anon lost SELECT on room_messages: study-room live chat (Realtime "
            "postgres_changes as anon, frontend/e2e/study-room.spec.ts) needs it "
            "until the step-2e JWT bridge replaces it"
        )


def test_updated_at_triggers_still_fire_after_the_execute_revoke(db_conn):
    # Trigger functions are permission-checked at CREATE TRIGGER, not at fire
    # time, so revoking EXECUTE on set_updated_at must not stop it. Run the
    # UPDATE as service_role (the backend's role) and roll it back.
    if not _existing_roles(db_conn, ["service_role"]):
        pytest.skip("no service_role on this stack")
    row = db_conn.execute("SELECT id FROM courses LIMIT 1").fetchone()
    if row is None:
        pytest.skip("no courses row to update")
    with db_conn.transaction() as tx:
        db_conn.execute("SET LOCAL ROLE service_role")
        db_conn.execute("UPDATE courses SET id = id WHERE id = %s", (row["id"],))
        # The trigger stamps now(), the transaction's start time; the row's
        # previous updated_at came from an earlier transaction.
        fired = db_conn.execute(
            "SELECT updated_at = now() AS fired FROM courses WHERE id = %s", (row["id"],)
        ).fetchone()["fired"]
        raise psycopg.Rollback(tx)
    assert fired, "set_updated_at did not fire"
