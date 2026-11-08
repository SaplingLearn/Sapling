"""Every public table has RLS on, anon gets nothing, authenticated gets exactly the plan.

Pins 20261108082151_rls_on_every_table.sql against the real local stack. Two
halves, because they fail differently:

* Catalog half (psycopg): `relrowsecurity` on every table, no table or
  sequence privilege for anon, and for authenticated EXACTLY the step-2c
  grants (20261108094130_rls_authenticated_grants.sql), each covered by a
  step-2b policy (20261108094129_rls_policies.sql). A future migration that
  creates a table and forgets `ENABLE ROW LEVEL SECURITY` / the REVOKE fails
  here, which is the regression that left 35 production tables open
  (the June lockdown never became a migration). The cross-user behaviour of
  those policies is in test_rls_policies_db.py.
* Wire half (PostgREST): the actual exposure. Every table is requested with the
  local stack's public anon key, the same kind of key the frontend ships, and
  must be refused. This is what an attacker with the bundle's key would try.

`room_messages` is the single documented exemption (see the migration header:
the local Realtime lane depends on anon postgres_changes, production already
has RLS on for it). The step-2e bridge (20261108210944_rls_room_messages
_realtime.sql) adds its policy but keeps RLS off; it leaves this list with
the migration that pins the manual enable step (that migration's header).

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


_ALL_TABLE_PRIVS = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")

_SIUD = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"})
_S = frozenset({"SELECT"})

# Step 2c: the table-level privileges `authenticated` holds, and nothing else.
# Mirrors docs/security/rls-step2/gen_policies.py; a table not listed here
# (bucket E service-only, plus room_messages until step 2e) must give
# authenticated nothing at all.
AUTHENTICATED_TABLE_GRANTS: dict[str, frozenset[str]] = {
    # bucket A: owned directly
    "users": _S,
    "user_profiles": frozenset({"SELECT", "INSERT", "UPDATE"}),
    "user_settings": frozenset({"SELECT", "INSERT", "UPDATE"}),
    **{t: _SIUD for t in (
        "oauth_tokens", "gradescope_credentials", "enrollments", "notes", "flashcards",
        "sessions", "quiz_attempts", "quiz_context", "study_guides", "graph_nodes",
        "graph_edges", "friend_requests",
    )},
    "documents": frozenset({"SELECT", "INSERT", "DELETE"}),   # + column UPDATE below
    "feedback": frozenset({"SELECT", "INSERT"}),
    "issue_reports": frozenset({"SELECT", "INSERT"}),
    "user_achievements": _S,                                  # + column UPDATE below
    "user_cosmetics": _S,
    "user_roles": _S,
    "xp_events": _S,
    "friendships": frozenset({"SELECT", "INSERT", "DELETE"}),
    # bucket B: owned through a parent
    "messages": _SIUD,
    "node_mastery_events": frozenset({"SELECT", "INSERT"}),
    "note_concepts": frozenset({"SELECT", "INSERT", "DELETE"}),
    **{t: _SIUD for t in (
        "quiz_responses", "gradebook_categories", "assignments", "gradescope_course_links",
        "topic_checklists", "topic_checklist_progress",
    )},
    # bucket C: shared
    "rooms": frozenset({"SELECT", "INSERT", "UPDATE"}),
    "room_members": frozenset({"SELECT", "INSERT", "DELETE"}),
    "room_bans": _SIUD,
    "room_activity": frozenset({"SELECT", "INSERT"}),
    "room_reactions": frozenset({"SELECT", "INSERT", "DELETE"}),
    **{t: _S for t in (
        "room_summaries", "offering_concept_stats", "offering_summary", "course_chunks",
        "course_chunk_contributors", "course_chunk_sources",
    )},
    # bucket D: catalog
    **{t: _S for t in (
        "schools", "terms", "courses", "course_offerings", "achievements",
        "achievement_triggers", "achievement_cosmetics", "cosmetics", "roles",
        "role_cosmetics", "growth_stages", "xp_rules",
    )},
}

# Column-level grants on top of the table-level ones: (table, privilege) -> columns.
AUTHENTICATED_COLUMN_GRANTS: dict[tuple[str, str], frozenset[str]] = {
    # Never the index_* lease columns: document_indexing (service_role) owns them.
    ("documents", "UPDATE"): frozenset({
        "file_name", "category", "summary", "concept_notes", "flashcards", "processed_at",
        "deleted_at", "extracted_text", "shareability", "shareability_confidence",
        "offering_id",
    }),
    # Awards are server-side; the student only picks which badges to feature.
    ("user_achievements", "UPDATE"): frozenset({"is_featured"}),
}

# Public functions authenticated may execute (step 2c). Both SECURITY INVOKER,
# so RLS on course_chunks / graph_nodes still applies inside them.
AUTHENTICATED_RPCS = frozenset({"match_course_chunks", "apply_mastery_delta"})


def test_anon_holds_no_table_privileges(db_conn):
    if not _existing_roles(db_conn, ["anon"]):
        pytest.fail("local stack has no anon role; is this Supabase?")
    rows = db_conn.execute(
        """
        SELECT p.priv || ':' || t.tablename AS leak
          FROM pg_tables t
         CROSS JOIN unnest(%s::text[]) AS p(priv)
         WHERE t.schemaname = 'public'
           AND NOT (t.tablename = ANY(%s::text[]))
           AND has_table_privilege('anon', format('public.%%I', t.tablename), p.priv)
         ORDER BY 1
        """,
        (list(_ALL_TABLE_PRIVS), list(EXEMPT)),
    ).fetchall()
    leaks = [r["leak"] for r in rows]
    assert not leaks, f"anon can still touch tables: {leaks}"
    cols = db_conn.execute(
        """
        SELECT c.relname || '.' || a.attname AS col
          FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid
         WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')
           AND a.attnum > 0 AND NOT a.attisdropped
           AND NOT (c.relname = ANY(%s::text[]))
           AND has_column_privilege('anon', c.oid, a.attnum, 'SELECT,INSERT,UPDATE,REFERENCES')
        """,
        (list(EXEMPT),),
    ).fetchall()
    assert not cols, f"anon holds column privileges: {[r['col'] for r in cols]}"


def test_authenticated_holds_exactly_the_planned_table_grants(db_conn):
    if not _existing_roles(db_conn, ["authenticated"]):
        pytest.fail("local stack has no authenticated role; is this Supabase?")
    rows = db_conn.execute(
        """
        SELECT t.tablename, p.priv
          FROM pg_tables t
         CROSS JOIN unnest(%s::text[]) AS p(priv)
         WHERE t.schemaname = 'public'
           AND NOT (t.tablename = ANY(%s::text[]))
           AND has_table_privilege('authenticated', format('public.%%I', t.tablename), p.priv)
        """,
        (list(_ALL_TABLE_PRIVS), list(EXEMPT)),
    ).fetchall()
    held: dict[str, set[str]] = {}
    for r in rows:
        held.setdefault(r["tablename"], set()).add(r["priv"])
    expected = {t: set(p) for t, p in AUTHENTICATED_TABLE_GRANTS.items()}
    extra = sorted(f"{t}:{p}" for t, ps in held.items() for p in ps - expected.get(t, set()))
    missing = sorted(f"{t}:{p}" for t, ps in expected.items() for p in ps - held.get(t, set()))
    assert not extra, (
        f"authenticated holds privileges outside the step-2c plan: {extra}. A new "
        "grant needs a policy, a line in AUTHENTICATED_TABLE_GRANTS and a migration."
    )
    assert not missing, f"step-2c grants missing: {missing}"


def test_authenticated_column_grants_are_exact(db_conn):
    # has_column_privilege is true for a column when the role holds the
    # privilege on the whole table OR on that column. So the expected set is
    # "every column" for table-level privileges, plus the listed columns.
    if not _existing_roles(db_conn, ["authenticated"]):
        pytest.fail("local stack has no authenticated role; is this Supabase?")
    rows = db_conn.execute(
        """
        SELECT c.relname, a.attname, p.priv
          FROM pg_class c
          JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
         CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','REFERENCES']) AS p(priv)
         WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')
           AND NOT (c.relname = ANY(%s::text[]))
           AND has_column_privilege('authenticated', c.oid, a.attnum, p.priv)
        """,
        (list(EXEMPT),),
    ).fetchall()
    held = {(r["relname"], r["priv"], r["attname"]) for r in rows}
    columns: dict[str, set[str]] = {}
    for r in db_conn.execute(
        """
        SELECT c.relname, a.attname FROM pg_class c
          JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
         WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')
        """
    ).fetchall():
        columns.setdefault(r["relname"], set()).add(r["attname"])
    expected = set()
    for t, privs in AUTHENTICATED_TABLE_GRANTS.items():
        for p in privs & {"SELECT", "INSERT", "UPDATE"}:
            expected |= {(t, p, col) for col in columns.get(t, set())}
    for (t, p), cols in AUTHENTICATED_COLUMN_GRANTS.items():
        unknown = cols - columns.get(t, set())
        assert not unknown, f"{t} has no column(s) {sorted(unknown)}"
        expected |= {(t, p, col) for col in cols}
    extra = sorted(":".join(k) for k in held - expected)
    missing = sorted(":".join(k) for k in expected - held)
    assert not extra, f"authenticated holds column privileges outside the plan: {extra}"
    assert not missing, f"step-2c column grants missing: {missing}"


def test_every_command_granted_to_authenticated_has_a_policy(db_conn):
    # The coverage query from the plan (§6.2), extended to column-level UPDATE.
    # A grant with no policy is deny-all under RLS: safe, but the plan and the
    # database disagree.
    rows = db_conn.execute(
        """
        SELECT t.relname || ':' || p.priv AS uncovered
          FROM pg_class t
         CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE']) p(priv)
         WHERE t.relnamespace = 'public'::regnamespace AND t.relkind = 'r'
           AND NOT (t.relname = ANY(%s::text[]))
           AND (has_table_privilege('authenticated', t.oid, p.priv)
                OR (p.priv = 'UPDATE'
                    AND has_any_column_privilege('authenticated', t.oid, 'UPDATE')))
           AND NOT EXISTS (
               SELECT 1 FROM pg_policy po
                WHERE po.polrelid = t.oid
                  AND (po.polcmd = '*' OR po.polcmd = CASE p.priv
                        WHEN 'SELECT' THEN 'r' WHEN 'INSERT' THEN 'a'
                        WHEN 'UPDATE' THEN 'w' ELSE 'd' END))
         ORDER BY 1
        """,
        (list(EXEMPT),),
    ).fetchall()
    uncovered = [r["uncovered"] for r in rows]
    assert not uncovered, f"commands granted to authenticated with no policy: {uncovered}"


# (table, policy) -> the table whose own RLS the policy's subquery relies on.
_ANCHORED_VIA_NESTED_RLS = {
    ("course_chunk_sources", "course_chunk_sources_select_readable"),  # course_chunks
}


def test_policies_are_authenticated_only_and_anchored_on_app_auth(db_conn):
    rows = db_conn.execute(
        """
        SELECT tablename, policyname, roles::text[] AS roles,
               coalesce(qual, '') || ' ' || coalesce(with_check, '') AS expr
          FROM pg_policies WHERE schemaname = 'public'
        """
    ).fetchall()
    assert len(rows) >= 137, f"expected the 137 step-2b policies, found {len(rows)}"
    wrong_role = sorted(f"{r['tablename']}.{r['policyname']}:{r['roles']}"
                        for r in rows if r["roles"] != ["authenticated"])
    assert not wrong_role, f"policies not scoped TO authenticated: {wrong_role}"
    # A policy may instead rest on another table's RLS: its EXISTS subquery
    # runs as the caller, so the inner table's (app_auth-anchored) policy
    # filters it. Listed explicitly so a new one is a reviewed decision.
    unanchored = sorted(f"{r['tablename']}.{r['policyname']}" for r in rows
                        if "app_auth." not in r["expr"]
                        and (r["tablename"], r["policyname"]) not in _ANCHORED_VIA_NESTED_RLS)
    assert not unanchored, f"policies not anchored on app_auth: {unanchored}"
    # auth.uid() casts sub to uuid and raises 22P02 on `user_<google id>`;
    # bare auth.jwt() trusts every token the project signs (GoTrue signups).
    supabase_auth = sorted(f"{r['tablename']}.{r['policyname']}" for r in rows
                           if re.search(r"(^|[^_])auth\.(uid|jwt|role)\(", r["expr"]))
    assert not supabase_auth, f"policies use Supabase auth.* helpers: {supabase_auth}"


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
    "claim_jobs",                    # services/jobs.py (#116)
    "complete_job",                  # services/jobs.py (#116)
    "enqueue_job",                   # services/jobs.py (#116)
    "fail_job",                      # services/jobs.py (#116)
    "heartbeat_job",                 # services/jobs.py (#116, 20261108213623)
    "match_course_chunks",           # services/rag_service.py
    "prune_jobs",                    # services/jobs.py (#116, 20261108213623)
})

APP_AUTH_FUNCTIONS = frozenset({
    "uid", "is_room_member", "owns_room", "owns_enrollment", "enrolled_in_offering",
    # step 2e (20261108210944_rls_room_messages_realtime.sql)
    "realtime_uid", "is_room_member_realtime",
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


def test_anon_and_authenticated_execute_only_the_planned_public_functions(db_conn):
    # anon: nothing. authenticated: exactly AUTHENTICATED_RPCS (step 2c), which
    # are SECURITY INVOKER so table RLS still applies inside them.
    roles = _existing_roles(db_conn, UNPRIVILEGED)
    assert roles, "local stack has no anon/authenticated roles; is this Supabase?"
    rows = db_conn.execute(_OWN_ROUTINES, ("public",)).fetchall()
    assert rows, "no functions in public; the catalog looks empty"
    allowed = {"anon": frozenset(), "authenticated": AUTHENTICATED_RPCS}
    held = {
        (role, r["proname"], r["sig"])
        for r in rows
        for role in roles
        if db_conn.execute(
            "SELECT has_function_privilege(%s, %s::oid, 'EXECUTE') AS ok",
            (role, r["oid"]),
        ).fetchone()["ok"]
    }
    leaks = sorted(f"{role}:{sig}" for role, name, sig in held if name not in allowed[role])
    assert not leaks, (
        f"public functions callable outside the plan (/rest/v1/rpc): {leaks}. "
        "A new function needs REVOKE ALL ... FROM PUBLIC, anon, authenticated "
        "(pattern: 20261108092633_rls_app_auth_helpers.sql)."
    )
    if "authenticated" in roles:
        got = {name for role, name, _ in held if role == "authenticated"}
        assert got == AUTHENTICATED_RPCS, f"authenticated RPC grants: {sorted(got)}"
        definer = db_conn.execute(
            "SELECT proname FROM pg_proc WHERE pronamespace = 'public'::regnamespace "
            "AND proname = ANY(%s) AND prosecdef",
            (sorted(AUTHENTICATED_RPCS),),
        ).fetchall()
        assert not definer, (
            f"{[r['proname'] for r in definer]} became SECURITY DEFINER: as an "
            "authenticated RPC it would read past RLS"
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


# ── Step 2e: room_messages read policy for the Realtime JWT bridge ─────────
# 20261108210944_rls_room_messages_realtime.sql. RLS on room_messages stays
# OFF here until the manual enable step (its header); the behaviour with it
# on is pinned in test_rls_policies_db.py (chat_world).

@pytest.mark.parametrize(
    ("claims", "expected"),
    [
        (None, None),
        ("", None),
        ('{"iss": "sapling-api", "sub": "user_1", "role": "authenticated"}', None),  # backend token
        ('{"iss": "supabase-demo", "sub": "user_1", "role": "authenticated"}', None),
        ('{"iss": "http://127.0.0.1:54321/auth/v1", "sub": "user_1"}', None),        # GoTrue
        ('{"sub": "user_1", "role": "authenticated"}', None),                       # no issuer
        ('{"iss": "sapling-realtime", "sub": ""}', None),
        ('{"iss": "sapling-realtime"}', None),
        ('{"iss": "sapling-realtime", "sub": "user_1", "role": "authenticated"}', "user_1"),
    ],
)
def test_app_auth_realtime_uid_only_trusts_realtime_claims(db_conn, claims, expected):
    with db_conn.transaction() as tx:
        if claims is not None:
            db_conn.execute("SELECT set_config('request.jwt.claims', %s, true)", (claims,))
        got = db_conn.execute("SELECT app_auth.realtime_uid() AS uid").fetchone()["uid"]
        raise psycopg.Rollback(tx)
    assert got == expected


def test_new_app_auth_helpers_pin_search_path_and_definer(db_conn):
    rows = db_conn.execute(
        "SELECT proname, prosecdef, coalesce(proconfig, '{}') AS cfg FROM pg_proc "
        "WHERE pronamespace = 'app_auth'::regnamespace "
        "AND proname IN ('realtime_uid', 'is_room_member_realtime')"
    ).fetchall()
    got = {r["proname"]: (r["prosecdef"], r["cfg"]) for r in rows}
    assert set(got) == {"realtime_uid", "is_room_member_realtime"}
    # Only the membership check reads past RLS; both pin an empty search_path.
    assert got["is_room_member_realtime"][0] is True
    assert got["realtime_uid"][0] is False
    for name, (_, cfg) in got.items():
        assert 'search_path=""' in cfg, f"app_auth.{name} does not pin search_path: {cfg}"


def test_room_messages_has_exactly_the_member_read_policy(db_conn):
    rows = db_conn.execute(
        """
        SELECT policyname, cmd, roles::text[] AS roles, coalesce(qual, '') AS qual,
               with_check
          FROM pg_policies WHERE schemaname = 'public' AND tablename = 'room_messages'
        """
    ).fetchall()
    assert [r["policyname"] for r in rows] == ["room_messages_select_member"]
    (pol,) = rows
    assert pol["cmd"] == "SELECT" and pol["roles"] == ["authenticated"]
    assert pol["with_check"] is None
    # Both readers, and nothing that trusts any other issuer.
    assert "app_auth.is_room_member(" in pol["qual"]
    assert "app_auth.is_room_member_realtime(" in pol["qual"]
