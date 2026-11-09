-- RLS step 2e, enable sequence steps 4-5: close the anon path on room_messages
-- and pin it. (Trov #115; design: docs/security/realtime-jwt-bridge-design.md,
-- "Enable sequence"; the policy this relies on is
-- 20261108210944_rls_room_messages_realtime.sql.)
--
-- What this does
-- --------------
-- The end state the 2e migration's header describes as a manual step, as a
-- migration, so every database (local, CI, staging, prod) replays it:
--   GRANT SELECT ON public.room_messages TO authenticated;
--   ALTER TABLE public.room_messages ENABLE ROW LEVEL SECURITY;
--   REVOKE SELECT ON public.room_messages FROM anon;
-- From here the only way to read room_messages, other than the backend
-- (service_role, BYPASSRLS), is the 2e policy room_messages_select_member:
-- a member of the message's room holding a `sapling-realtime` token (GET
-- /api/auth/realtime-token, what the study-room client subscribes with) or a
-- `sapling-api` token. Supabase Realtime evaluates that policy per change and
-- per subscriber, so an anon-key subscription receives nothing, and a
-- non-member's token receives nothing for rooms they are not in.
--
-- The anon revoke is written as REVOKE ALL, and authenticated's grant as
-- REVOKE ALL + GRANT SELECT (the step-2a pattern,
-- 20261108092633_rls_app_auth_helpers.sql section 4). Step 2a already removed
-- the stray INSERT/UPDATE/DELETE/TRUNCATE/REFERENCES/TRIGGER both roles held,
-- so on every database that ran it this is the same as the three statements
-- above. Done this way it also clears any privilege granted since, and it
-- keeps the literal TRUNCATE keyword out of the file, which
-- promotion/preflight.py::scan_destructive would flag. End state, pinned by
-- tests/integration/test_rls_lockdown_db.py: anon holds nothing on
-- room_messages, authenticated holds exactly SELECT, service_role keeps ALL.
--
-- Where it changes something
-- --------------------------
-- * Production: NO-OP. RLS has been on for room_messages since the June
--   lockdown, the lockdown revoked anon SELECT, step 2a revoked the rest, and
--   the 2e migration granted authenticated SELECT (it does that only where
--   RLS was already on, i.e. here).
-- * Staging: CHANGES. RLS goes on and anon loses SELECT. Live chat keeps
--   working only for clients that subscribe with the bridge token. That is
--   every client today: `realtime_rls` is on (default `on`) on staging and
--   prod, and the code shipped with this migration no longer has an anon
--   path at all.
-- * Local and CI: CHANGES, the same way (a fresh replay ends here). The local
--   Realtime trusts the oct key in backend/.env.local.example, which CI copies
--   to backend/.env, so the E2E study-room journey runs through the bridge.
--
-- Precondition
-- ------------
-- `realtime_rls` is on for every student on every environment this reaches
-- (stored default `on`, no `off` rules, no SAPLING_FLAG_REALTIME_RLS=off
-- override) and SUPABASE_JWT_SIGNING_KEY is set on that backend and trusted by
-- that project's Realtime. Without that, a client still on the anon key gets no
-- live chat after this runs (REST reads keep working: they are service_role).
--
-- Idempotent: GRANT/REVOKE and ENABLE ROW LEVEL SECURITY are safe to re-run.
-- Role and table guards keep it appliable on a bare Postgres without the
-- Supabase roles. Nothing here touches data. Atomic: the runner applies the
-- file in one transaction.
--
-- Reverse (by hand, as the migration role; never on production, which has run
-- with RLS on for room_messages since June):
--   BEGIN;
--   GRANT SELECT ON public.room_messages TO anon;
--   ALTER TABLE public.room_messages DISABLE ROW LEVEL SECURITY;
--   COMMIT;
-- That restores the anon read that a REVERTED frontend (with the anon
-- subscription path) needs; the code in this change never uses it. Leave
-- authenticated's SELECT: with RLS on it is gated by the member policy, and
-- with RLS off it is what Supabase's default had given it anyway.

DO $$
DECLARE
    has_anon          BOOLEAN := EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon');
    has_authenticated BOOLEAN := EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated');
BEGIN
    IF to_regclass('public.room_messages') IS NULL THEN
        RETURN;
    END IF;
    IF has_authenticated THEN
        -- Exactly SELECT, gated by room_messages_select_member.
        REVOKE ALL ON TABLE public.room_messages FROM authenticated;
        GRANT SELECT ON TABLE public.room_messages TO authenticated;
    END IF;
    ALTER TABLE public.room_messages ENABLE ROW LEVEL SECURITY;
    IF has_anon THEN
        -- REVOKE SELECT, and any stray privilege with it.
        REVOKE ALL ON TABLE public.room_messages FROM anon;
    END IF;
END $$;
