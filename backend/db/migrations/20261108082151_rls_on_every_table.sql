-- RLS on every public table, and no table access for anon / authenticated.
--
-- Why: the June 2026 lockdown (#231) was applied to production by hand from
-- PR #232 and never became a migration. Every table the redesign dropped and
-- recreated (0021-0027), and every table added since, came back with RLS off.
-- On 2026-11-08 the Supabase Security Advisor on production reported "RLS
-- Disabled in Public" for 35 tables (messages, notes, documents, graph_nodes,
-- quiz_attempts, user_profiles, course_chunks, events, schema_migrations, ...).
-- Supabase's default privileges grant anon and authenticated full DML on new
-- public tables (see 20260928022711_feature_flags.sql), and the anon key ships
-- in the frontend bundle, so those tables were reachable without the backend.
-- The local stack and every CI lane build from these files, so they had RLS
-- off almost everywhere too, which is why nothing caught it.
--
-- What this does, for every table in `public` at apply time (a loop, not a
-- list, so a table created out of band is covered too):
--   1. ENABLE ROW LEVEL SECURITY. No policies are added. A role without
--      BYPASSRLS therefore sees no rows.
--   2. REVOKE ALL from anon and authenticated, on tables and sequences.
--   3. GRANT ALL to service_role, so the backend's access never depends on
--      what a default privilege happened to grant when a table was made.
--   4. Default privileges for tables and sequences the migration role creates
--      later stop granting anon and authenticated anything.
--
-- Why the backend is unaffected: it authenticates as service_role, which has
-- rolbypassrls = true (verified on production in June, rls-lockdown-plan.md).
-- db/migrate.py, the e2e oracles, the promotion runner and the integration
-- truncate connect as `postgres`, the table owner, and owners bypass RLS
-- unless FORCE ROW LEVEL SECURITY is set, which this does not do.
--
-- The one exception is room_messages. It is left exactly as it is in every
-- environment: production already has RLS on for it (it was not in the
-- Advisor's list), and the local/CI stack relies on anon Realtime
-- postgres_changes for it (frontend/e2e/study-room.spec.ts). Locking it here
-- would break that lane without changing production. It moves under RLS with
-- the realtime JWT bridge (docs/security/realtime-jwt-bridge-design.md).
--
-- Guarded so it applies on a bare Postgres without the Supabase roles, like
-- the other role-touching migrations. Idempotent: every statement is safe to
-- re-run. If a table is not owned by the migration role, ENABLE fails and
-- db/migrate.py rolls the whole batch back, which is the safe outcome.

DO $$
DECLARE
    t      TEXT;
    r      TEXT;
    exempt CONSTANT TEXT[] := ARRAY['room_messages'];
BEGIN
    FOR t IN
        SELECT tablename FROM pg_tables
         WHERE schemaname = 'public'
         ORDER BY tablename
    LOOP
        CONTINUE WHEN t = ANY (exempt);

        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);

        FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                EXECUTE format('REVOKE ALL ON TABLE public.%I FROM %I', t, r);
            END IF;
        END LOOP;

        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
            EXECUTE format('GRANT ALL ON TABLE public.%I TO service_role', t);
        END IF;
    END LOOP;
END $$;

-- Sequences (identity / serial columns). No table above uses one today, but
-- a future serial column would otherwise hand anon nextval().
DO $$
DECLARE
    s TEXT;
    r TEXT;
BEGIN
    FOR s IN
        SELECT sequence_name FROM information_schema.sequences
         WHERE sequence_schema = 'public'
    LOOP
        FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                EXECUTE format('REVOKE ALL ON SEQUENCE public.%I FROM %I', s, r);
            END IF;
        END LOOP;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
            EXECUTE format('GRANT ALL ON SEQUENCE public.%I TO service_role', s);
        END IF;
    END LOOP;
END $$;

-- Future objects created by the role that runs migrations. This only changes
-- defaults for the current role; tables made by another role (for example in
-- the dashboard, which this repo forbids) are caught by
-- tests/integration/test_rls_lockdown_db.py instead.
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM %I', r);
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM %I', r);
        END IF;
    END LOOP;
END $$;
