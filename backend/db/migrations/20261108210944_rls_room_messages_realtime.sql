-- RLS step 2e: the room_messages read policy for the Realtime JWT bridge.
-- (Trov #115; design: docs/security/realtime-jwt-bridge-design.md, section
-- "Step 2e (shipped)"; plan: docs/security/rls-step2-plan.md §2.4, §6.1.)
--
-- What this does
-- --------------
-- 1. app_auth.realtime_uid() -> TEXT. The Sapling user a Supabase Realtime
--    subscription runs as, read from `request.jwt.claims` (Realtime's
--    realtime.apply_rls sets it to the subscriber's JWT claims, exactly as
--    PostgREST does per request), but only when iss = 'sapling-realtime': the
--    token GET /api/auth/realtime-token mints for the browser (db/user_jwt.py
--    ::mint_realtime, behind the `realtime_rls` flag). Any other token,
--    including the backend's own 'sapling-api' token, a Supabase Auth (GoTrue)
--    signup, the local demo issuer and a token with no issuer, resolves to
--    NULL. app_auth.uid() is NOT changed: it still trusts 'sapling-api' only,
--    so a realtime token a student lifts out of the browser resolves to no
--    user in every other policy (it can read its own rooms' messages, which
--    it could already see in the app, and nothing else).
-- 2. app_auth.is_room_member_realtime(room_id). SECURITY DEFINER for the same
--    reason as app_auth.is_room_member (step 2a): the room_members policy is
--    anchored on app_auth.uid(), which is NULL for a realtime token, so a
--    plain EXISTS on room_members would always come back empty. Pins
--    search_path = '' and filters on app_auth.realtime_uid().
-- 3. Policy room_messages_select_member: FOR SELECT TO authenticated, a row
--    is visible when the caller is a member of its room, as either
--      * a backend 'sapling-api' token (app_auth.is_room_member, for a future
--        user-scoped social router; /api/social is service-scoped today), or
--      * a browser 'sapling-realtime' token (app_auth.is_room_member_realtime).
--    Realtime re-evaluates it for every change and every subscriber, so a
--    student who leaves or is kicked stops receiving the room's changes.
--    (Deletes are not RLS-filtered by Realtime and carry only the primary
--    key; room messages are soft-deleted, so that is moot here.)
--    No INSERT/UPDATE/DELETE policy: every write goes through the backend as
--    service_role, and authenticated holds no write privilege (step 2a).
-- 4. GRANT SELECT ON room_messages TO authenticated, but ONLY where RLS is
--    already on for room_messages (production: on since the June lockdown,
--    zero policies). There the policy above is the whole gate. Where RLS is
--    off (local, CI, staging) authenticated already holds the SELECT
--    Supabase's default gave it (step 2a kept it), and granting it where it
--    was missing would let every authenticated token (a GoTrue signup
--    included) read every room, so the migration leaves those alone. The
--    manual enable step below grants it explicitly.
--
-- Why it is inert
-- ---------------
-- * Where RLS is OFF on room_messages (local, CI, staging today) Postgres
--   never evaluates the policy: anon and authenticated keep reading exactly
--   what they read now, so the anon Realtime postgres_changes lane
--   (frontend/src/components/screens/Social.tsx, frontend/e2e/study-room
--   .spec.ts) and flag-off clients are untouched. This migration does NOT
--   enable RLS on room_messages and does NOT revoke anon SELECT.
-- * Where RLS is ON (production), anon already reads nothing (the June
--   lockdown revoked its SELECT; live chat delivers nothing today), and the
--   policy only admits tokens nothing mints until the `realtime_rls` or
--   `db_user_scope` flag leaves "off". GoTrue and other foreign tokens
--   resolve to NULL in both helpers and read zero rows.
-- * The backend reaches PostgREST as service_role (BYPASSRLS); migrations,
--   oracles and the integration conftest connect as `postgres` (table owner,
--   RLS not forced).
--
-- The later MANUAL step (not in this migration)
-- ---------------------------------------------
-- Once `realtime_rls` is "on" for every student (stored default "on", no
-- "off" rules, no SAPLING_FLAG_REALTIME_RLS=off override) and the final E2E
-- pass with the flag on is green, on each environment, as the migration role:
--   BEGIN;
--   GRANT SELECT ON public.room_messages TO authenticated;
--   ALTER TABLE public.room_messages ENABLE ROW LEVEL SECURITY;
--   REVOKE SELECT ON public.room_messages FROM anon;
--   COMMIT;
-- (production already has RLS on and no anon SELECT, so there only the GRANT
-- can matter, and this migration already made it.) From that moment a client
-- still on the anon key gets no live chat (REST reads keep working: they are
-- service_role). Then pin it in a NEW migration (same three statements,
-- idempotent) so local/CI replay the end state, and drop room_messages from
-- EXEMPT in tests/integration/test_rls_lockdown_db.py and from the
-- `room_messages` anon-SELECT test there. Rollback of the manual step:
--   BEGIN;
--   GRANT SELECT ON public.room_messages TO anon;
--   ALTER TABLE public.room_messages DISABLE ROW LEVEL SECURITY;
--   COMMIT;
-- (not on production, which has run with RLS on since June).
--
-- Idempotent: CREATE OR REPLACE FUNCTION, DROP POLICY IF EXISTS + CREATE
-- POLICY, GRANT/REVOKE are all safe to re-run. Role and table guards keep it
-- appliable on a bare Postgres without the Supabase roles. Nothing here
-- touches data.
--
-- Reverse (by hand, as the migration role):
--   DROP POLICY IF EXISTS room_messages_select_member ON public.room_messages;
--   DROP FUNCTION IF EXISTS app_auth.is_room_member_realtime(text);
--   DROP FUNCTION IF EXISTS app_auth.realtime_uid();
--   -- The SELECT grant (section 4) is only ever added where RLS was already
--   -- on and authenticated lacked it; leaving it is harmless with zero
--   -- policies (deny-all). To restore the exact prior ACL there:
--   --   REVOKE SELECT ON public.room_messages FROM authenticated;
--   -- (production's authenticated held SELECT before 2a; check `\dp
--   -- room_messages` first and skip the REVOKE if it predates this.)

-- ── 1–2. app_auth helpers ───────────────────────────────────────────────────

CREATE SCHEMA IF NOT EXISTS app_auth;

-- The Sapling user a Realtime subscription runs as, or NULL. See the header.
CREATE OR REPLACE FUNCTION app_auth.realtime_uid() RETURNS text
LANGUAGE sql STABLE SET search_path = '' AS $$
    SELECT CASE
        WHEN (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'iss') = 'sapling-realtime'
        THEN nullif(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub', '')
    END
$$;

-- "Is the Realtime subscriber a member of this room". SECURITY DEFINER so it
-- reads room_members past that table's own (app_auth.uid()-anchored) RLS.
CREATE OR REPLACE FUNCTION app_auth.is_room_member_realtime(p_room_id text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    SELECT EXISTS (SELECT 1 FROM public.room_members m
                    WHERE m.room_id = p_room_id AND m.user_id = app_auth.realtime_uid())
$$;

REVOKE ALL ON FUNCTION app_auth.realtime_uid() FROM PUBLIC;
REVOKE ALL ON FUNCTION app_auth.is_room_member_realtime(text) FROM PUBLIC;

DO $$
DECLARE
    r TEXT;
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON FUNCTION app_auth.realtime_uid() FROM anon;
        REVOKE ALL ON FUNCTION app_auth.is_room_member_realtime(text) FROM anon;
    END IF;
    -- authenticated runs the policy (as the PostgREST request role, or as the
    -- role Realtime's apply_rls switches to); service_role for parity with 2a.
    FOREACH r IN ARRAY ARRAY['authenticated', 'service_role'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('GRANT USAGE ON SCHEMA app_auth TO %I', r);
            EXECUTE format('GRANT EXECUTE ON FUNCTION app_auth.realtime_uid() TO %I', r);
            EXECUTE format(
                'GRANT EXECUTE ON FUNCTION app_auth.is_room_member_realtime(text) TO %I', r);
        END IF;
    END LOOP;
END $$;

-- ── 3–4. room_messages: member read policy (+ the grant where RLS is on) ────

DO $$
BEGIN
    IF to_regclass('public.room_messages') IS NULL
       OR NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        RETURN;
    END IF;
    DROP POLICY IF EXISTS room_messages_select_member ON public.room_messages;
    CREATE POLICY room_messages_select_member ON public.room_messages
        FOR SELECT TO authenticated
        USING ((SELECT app_auth.is_room_member(room_messages.room_id))
               OR (SELECT app_auth.is_room_member_realtime(room_messages.room_id)));
    IF (SELECT relrowsecurity FROM pg_class WHERE oid = 'public.room_messages'::regclass) THEN
        GRANT SELECT ON TABLE public.room_messages TO authenticated;
    END IF;
END $$;
