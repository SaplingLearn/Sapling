-- 20261108162223_learning_exact_floats.sql
-- Learning loop spec §13 A136: every double precision and real value the
-- backend reads through PostgREST comes back exact.
--
-- The Supabase Postgres image sets extra_float_digits = 0 in its
-- postgresql.conf (supabase/postgres, ansible/files/postgresql_config/
-- postgresql.conf.j2, the file the Docker image copies and the hosted AMI
-- templates). PostgreSQL's own default is 1. At 0, float8 output is rounded to
-- 15 significant digits and float4 output to 6, in text and in to_jsonb(). Every
-- PostgREST response body is built that way, so the backend read
-- p_known = 0.30000000000000004 back as 0.3, and a real column such as
-- quiz_responses.confidence to 6 digits. 20261108115720 fixed the two learning
-- evidence snapshot functions only; the backend's other reads of learner_state,
-- graph_nodes, node_mastery_events, flashcards, check_items, posttest_poses,
-- documents and the float-returning functions stayed rounded.
--
-- The backend reaches PostgREST with the service key only, so every request
-- runs as service_role. PostgREST logs in as authenticator and switches role
-- per request; PostgreSQL applies role settings at login only, so a setting on
-- service_role is applied by PostgREST itself: since PostgREST 11.0.0 it reads
-- the settings of the roles authenticator may switch to (those a user may set,
-- pg_settings.context = 'user', as extra_float_digits is) and applies each as a
-- transaction-scoped set_config on every request that runs as the role. It
-- reads them at start and on NOTIFY pgrst, 'reload config' (below). Above 0,
-- float output is the shortest text that reads back as the same value.
--
-- Hosted Supabase allows it: supautils lists service_role* among the reserved
-- roles, and the trailing * lets the privileged role change their settings;
-- Supabase's own docs change role settings this way (ALTER ROLE ... SET
-- statement_timeout, then NOTIFY pgrst, 'reload config').
--
-- Unchanged: the server default (every other connection: psql, the
-- dashboard, the migration runner), and 20261108115720's function-level
-- settings on the two snapshot functions, which keep them exact on any path.
--
-- learning_float_probe() returns known values for the release fence
-- (scripts/learning_release_verify.py --rest-float-probe) and the integration
-- lane: read through PostgREST as service_role, the exact path the backend
-- uses, they parse back to the same doubles only when the setting is applied.
-- No data, no write: STABLE, so PostgREST runs a GET of it read-only. It sets
-- no extra_float_digits of its own, or it would measure nothing.
--
-- Deploy: apply before or after the code (the code reads either way; this
-- makes its reads exact). Then run the fence's probe. Role statements are
-- guarded (a plain Postgres has no Supabase roles). Idempotent.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        ALTER ROLE service_role SET extra_float_digits = 3;
    END IF;
END $$;

CREATE OR REPLACE FUNCTION public.learning_float_probe()
RETURNS TABLE (float8_value double precision, float4_value real, jsonb_value jsonb, digits text)
LANGUAGE sql
STABLE
SET search_path = ''
AS $$
    SELECT 0.30000000000000004::double precision,
           0.12345679::real,
           pg_catalog.to_jsonb(0.30000000000000004::double precision),
           pg_catalog.current_setting('extra_float_digits')
$$;

REVOKE ALL ON FUNCTION public.learning_float_probe() FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION public.learning_float_probe() FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION public.learning_float_probe() TO service_role;
    END IF;
END $$;

-- The role setting reaches PostgREST on a config reload; the function on a
-- schema reload. Both are delivered at COMMIT, and are no-ops with no listener.
NOTIFY pgrst, 'reload config';
NOTIFY pgrst, 'reload schema';
