-- DRAFT for <ts>_rls_app_auth_helpers.sql (step 2a). Not in the repo.
-- Identity helpers every policy is anchored on, plus function EXECUTE hygiene
-- that #807 left open.

CREATE SCHEMA IF NOT EXISTS app_auth;
REVOKE ALL ON SCHEMA app_auth FROM PUBLIC;

-- The Sapling user a request runs as, or NULL. Reads the claims PostgREST
-- sets per request. Only tokens the backend minted count (iss pin), so a
-- GoTrue-issued `authenticated` token (Supabase Auth signups are on by default)
-- resolves to NULL and every policy denies it. TEXT, never uuid: users.id is
-- `user_<google id>`, and auth.uid() casts to uuid and raises 22P02 on it.
CREATE OR REPLACE FUNCTION app_auth.uid() RETURNS text
LANGUAGE sql STABLE SET search_path = '' AS $$
    SELECT CASE
        WHEN (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'iss') = 'sapling-api'
        THEN nullif(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub', '')
    END
$$;

-- Membership checks. SECURITY DEFINER so a policy on room_members can ask
-- "is the caller a member of this room" without recursing into its own RLS.
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

-- #807 gap: EXECUTE on public functions still defaults to PUBLIC
-- (match_course_chunks and set_updated_at are callable by anon today).
-- Trigger functions do not need EXECUTE at fire time, so this is safe for
-- set_updated_at (verified on PG 16).
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;

DO $$
DECLARE r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM %I', r);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM %I', r);
        END IF;
    END LOOP;
    EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC';
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        EXECUTE 'GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO service_role';
        EXECUTE 'GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA app_auth TO service_role';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA app_auth TO authenticated';
        EXECUTE 'GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA app_auth TO authenticated';
    END IF;
END $$;
