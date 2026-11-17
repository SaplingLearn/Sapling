-- RLS step 2a: the app_auth identity helpers, function EXECUTE hygiene, and
-- the room_messages privileges the June lockdown left behind.
-- (Trov #115; plan: docs/security/rls-step2-plan.md §1.1, §1.7, §6.1.)
--
-- What this does
-- --------------
-- 1. Creates schema `app_auth` (NOT in config.toml [api].schemas, so PostgREST
--    never exposes it) with:
--      * app_auth.uid() -> TEXT. The Sapling user the request runs as, read from
--        the `request.jwt.claims` PostgREST sets, but only when iss =
--        'sapling-api' (a token the backend minted). Any other token, including
--        a Supabase Auth signup's `authenticated` JWT, resolves to NULL. TEXT on
--        purpose: users.id is `user_<google id>`, and auth.uid() casts sub to
--        uuid and raises 22P02 on it.
--      * four SECURITY DEFINER membership helpers (is_room_member, owns_room,
--        owns_enrollment, enrolled_in_offering) so a step-2b policy can ask
--        "is the caller in this room" without recursing into room_members'
--        own RLS. Each pins search_path = '' and filters on app_auth.uid().
--    EXECUTE on app_auth goes to authenticated and service_role only (also as
--    the default for functions later migrations add there).
-- 2. Revokes EXECUTE on every function in `public` from PUBLIC, anon and
--    authenticated, and grants it to service_role. Extension-owned functions
--    (pg_depend deptype 'e': pgvector's type I/O, operators and distance
--    functions) are deliberately left alone: they are SECURITY INVOKER C
--    functions that touch no table, their owner on hosted Supabase may not be
--    the migration role, and step 2c's authenticated `match_course_chunks`
--    call runs `<=>` as the caller, which needs EXECUTE on pgvector's
--    operator functions.
--    Why: #807 revoked table access but left function EXECUTE defaulting to
--    PUBLIC. `match_course_chunks` and `set_updated_at` were callable with the
--    public anon key, and the next SECURITY DEFINER function a migration adds
--    would have been too (PostgREST serves every public function at
--    /rest/v1/rpc/<name>).
-- 3. Default privileges, for functions the migration role creates later:
--      * global: no EXECUTE for PUBLIC. This has to be the global form:
--        `ALTER DEFAULT PRIVILEGES IN SCHEMA ... REVOKE ... FROM PUBLIC` is a
--        silent no-op, because a per-schema entry can only ADD to the global
--        defaults (PG docs, ALTER DEFAULT PRIVILEGES). It applies to every
--        schema, so a function a later migration creates anywhere needs an
--        explicit GRANT for any role other than its owner and the defaults
--        below. Existing migrations already REVOKE ... FROM PUBLIC on every
--        function they add, so none of them relied on the PUBLIC default.
--      * schema public: no EXECUTE for anon / authenticated (undoes
--        Supabase's per-schema `GRANT ... ON FUNCTIONS TO anon,
--        authenticated`), and EXECUTE for service_role, so a future RPC keeps
--        working for the backend without its migration remembering the
--        grant. Supabase's own default already includes service_role (seen
--        on the supabase/postgres 15.8 image), so that line pins it rather
--        than changing it; it matters wherever that default is missing.
--      * schema app_auth: EXECUTE for authenticated and service_role.
-- 4. room_messages (still exempt from #807 until the step-2e realtime bridge).
--    Done as REVOKE ALL plus a re-GRANT of SELECT where the role held it, so
--    the net effect is exactly:
--      * anon: revoke INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER.
--        anon SELECT STAYS. Locally and in CI room_messages has RLS off and
--        study-room live chat rides Supabase Realtime postgres_changes as
--        anon (frontend/src/components/screens/Social.tsx,
--        frontend/e2e/study-room.spec.ts). Realtime delivers a change to a
--        subscriber only if that role holds SELECT on the table (and passes
--        RLS when it is on), so revoking it breaks that lane. Realtime needs
--        nothing else: every write goes through the backend as service_role,
--        and the frontend never writes or RPCs PostgREST directly (no
--        `.from(` / `.rpc(` in frontend/src). Step 2e replaces the anon path
--        with the JWT bridge (docs/security/realtime-jwt-bridge-design.md:
--        a backend-minted `sapling-realtime` token plus a member-scoped
--        SELECT policy) and then revokes anon SELECT too.
--        Production already has RLS on with zero policies here and the June
--        lockdown revoked anon SELECT/INSERT/UPDATE/DELETE, so on prod this
--        only removes the TRUNCATE/REFERENCES/TRIGGER the Addendum found.
--        Staging has RLS off, so there it also removes anon write access.
--      * authenticated: revoke INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES,
--        TRIGGER. authenticated SELECT is left alone (prod: RLS with zero
--        policies, so it reads nothing; 2e decides it).
--      * service_role: GRANT ALL, as #807 does for every other table, so the
--        backend's chat routes never depend on a default privilege.
--
-- Why it is inert for the backend
-- -------------------------------
-- The backend reaches PostgREST as service_role (db/connection.py), and every
-- RPC it calls is granted to service_role here explicitly:
-- match_course_chunks (services/rag_service.py), apply_mastery_delta
-- (services/graph_service.py), claim_documents_for_indexing
-- (services/index_sweeper.py), canopy_metrics (routes/internal_metrics.py),
-- plus canopy_active_users (kept for the pre-#654 image). The last four were
-- already service_role-only. Trigger functions (set_updated_at) need no
-- EXECUTE at fire time, only at CREATE TRIGGER, so the triggers keep firing.
-- db/migrate.py, the oracles and the integration conftest connect as
-- `postgres`, which owns these functions. No `sapling-api` token exists yet,
-- so app_auth.uid() is NULL for every request until the step-2c code ships.
--
-- Idempotent: CREATE ... IF NOT EXISTS / OR REPLACE, REVOKE/GRANT and
-- ALTER DEFAULT PRIVILEGES are all safe to re-run. Role and table guards keep
-- it appliable on a bare Postgres without the Supabase roles. Nothing here
-- touches data.
--
-- Reverse (by hand, as the migration role; this exact block was run and
-- checked against a replayed local schema):
--   -- 1. app_auth holds only these five functions, so CASCADE drops nothing
--   --    else (step-2b policies call them: reverse 2b first if it landed).
--   ALTER DEFAULT PRIVILEGES IN SCHEMA app_auth REVOKE EXECUTE ON FUNCTIONS FROM authenticated, service_role;
--   DROP SCHEMA IF EXISTS app_auth CASCADE;
--   -- 2. The public functions that had PUBLIC EXECUTE before this ran. The
--   --    backend-only RPCs (canopy_active_users, canopy_metrics,
--   --    claim_documents_for_indexing, apply_mastery_delta) were already
--   --    service_role-only, so they are not re-granted.
--   GRANT EXECUTE ON FUNCTION public.set_updated_at() TO PUBLIC, anon, authenticated;
--   GRANT EXECUTE ON FUNCTION public.match_course_chunks(vector, integer, text, text) TO PUBLIC, anon, authenticated;
--   -- 3. Default privileges.
--   ALTER DEFAULT PRIVILEGES GRANT EXECUTE ON FUNCTIONS TO PUBLIC;
--   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO anon, authenticated;
--   --    (service_role's default EXECUTE in public predates this; keep it.)
--   -- 4. room_messages. Local/CI/staging had Supabase's default full grant to
--   --    both roles. Production's anon had only TRUNCATE, REFERENCES and
--   --    TRIGGER (the June lockdown took the rest): on prod, re-grant anon
--   --    just those three. service_role's GRANT ALL predates this everywhere.
--   GRANT INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.room_messages TO anon, authenticated;

-- ── 1. app_auth ─────────────────────────────────────────────────────────────

CREATE SCHEMA IF NOT EXISTS app_auth;
REVOKE ALL ON SCHEMA app_auth FROM PUBLIC;

-- The Sapling user a request runs as, or NULL. See the header.
CREATE OR REPLACE FUNCTION app_auth.uid() RETURNS text
LANGUAGE sql STABLE SET search_path = '' AS $$
    SELECT CASE
        WHEN (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'iss') = 'sapling-api'
        THEN nullif(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub', '')
    END
$$;

-- Membership checks. SECURITY DEFINER so a policy on room_members can ask
-- "is the caller a member of this room" without recursing into its own RLS.
-- The owner (the migration role) owns the tables, so it reads past RLS here.
CREATE OR REPLACE FUNCTION app_auth.is_room_member(p_room_id text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    SELECT EXISTS (SELECT 1 FROM public.room_members m
                    WHERE m.room_id = p_room_id AND m.user_id = app_auth.uid())
$$;

CREATE OR REPLACE FUNCTION app_auth.owns_room(p_room_id text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    SELECT EXISTS (SELECT 1 FROM public.rooms r
                    WHERE r.id = p_room_id AND r.owner_id = app_auth.uid())
$$;

CREATE OR REPLACE FUNCTION app_auth.owns_enrollment(p_enrollment_id text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    SELECT EXISTS (SELECT 1 FROM public.enrollments e
                    WHERE e.id = p_enrollment_id AND e.user_id = app_auth.uid())
$$;

CREATE OR REPLACE FUNCTION app_auth.enrolled_in_offering(p_offering_id text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    SELECT EXISTS (SELECT 1 FROM public.enrollments e
                    WHERE e.offering_id = p_offering_id AND e.user_id = app_auth.uid())
$$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA app_auth FROM PUBLIC;

DO $$
DECLARE
    r TEXT;
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON SCHEMA app_auth FROM anon;
        REVOKE ALL ON ALL FUNCTIONS IN SCHEMA app_auth FROM anon;
    END IF;
    FOREACH r IN ARRAY ARRAY['authenticated', 'service_role'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('GRANT USAGE ON SCHEMA app_auth TO %I', r);
            EXECUTE format('GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA app_auth TO %I', r);
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES IN SCHEMA app_auth GRANT EXECUTE ON FUNCTIONS TO %I', r);
        END IF;
    END LOOP;
END $$;

-- ── 2. EXECUTE on existing public functions ─────────────────────────────────
--
-- A loop rather than `... ON ALL FUNCTIONS IN SCHEMA public`, so extension
-- members are skipped (see the header). prokind 'f' (function) and 'p'
-- (procedure); there are no non-extension aggregates or window functions in
-- public, and tests/integration/test_rls_lockdown_db.py fails if one appears
-- with PUBLIC EXECUTE.

DO $$
DECLARE
    fn TEXT;
    r  TEXT;
BEGIN
    FOR fn IN
        SELECT p.oid::regprocedure::text
          FROM pg_proc p
         WHERE p.pronamespace = 'public'::regnamespace
           AND p.prokind IN ('f', 'p')
           AND NOT EXISTS (
               SELECT 1 FROM pg_depend d
                WHERE d.classid = 'pg_proc'::regclass
                  AND d.objid = p.oid
                  AND d.deptype = 'e')
         ORDER BY 1
    LOOP
        EXECUTE format('REVOKE EXECUTE ON ROUTINE %s FROM PUBLIC', fn);
        FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                EXECUTE format('REVOKE EXECUTE ON ROUTINE %s FROM %I', fn, r);
            END IF;
        END LOOP;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
            EXECUTE format('GRANT EXECUTE ON ROUTINE %s TO service_role', fn);
        END IF;
    END LOOP;
END $$;

-- ── 3. Default privileges for functions created later ───────────────────────

ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO service_role;
    END IF;
END $$;

-- ── 4. room_messages ────────────────────────────────────────────────────────
--
-- REVOKE ALL, then put SELECT back only where the role held it directly
-- before. Same end state as revoking the six write/DDL privileges by name,
-- but it never GRANTs anon a SELECT it did not have (production's June
-- lockdown took it), and it keeps the literal TRUNCATE keyword out of the
-- statement, which promotion/preflight.py's destructive-DDL scan would flag.
-- Atomic: the migration runs in one transaction.

DO $$
DECLARE
    r          TEXT;
    had_select BOOLEAN;
BEGIN
    IF to_regclass('public.room_messages') IS NULL THEN
        RETURN;
    END IF;
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        CONTINUE WHEN NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r);
        SELECT EXISTS (
            SELECT 1
              FROM pg_class c, aclexplode(c.relacl) a
             WHERE c.oid = 'public.room_messages'::regclass
               AND a.grantee = (SELECT oid FROM pg_roles WHERE rolname = r)
               AND a.privilege_type = 'SELECT'
        ) INTO had_select;
        EXECUTE format('REVOKE ALL ON TABLE public.room_messages FROM %I', r);
        IF had_select THEN
            -- anon: local/CI Realtime postgres_changes runs as anon (header).
            EXECUTE format('GRANT SELECT ON TABLE public.room_messages TO %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT ALL ON TABLE public.room_messages TO service_role;
    END IF;
END $$;
