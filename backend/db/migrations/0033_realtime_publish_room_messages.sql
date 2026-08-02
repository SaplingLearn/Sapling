-- 0033: publish room_messages on the supabase_realtime publication.
--
-- Study-room chat propagation (frontend/src/components/screens/Social.tsx)
-- rides Supabase Realtime `postgres_changes` on `room_messages`: a foreign
-- INSERT/UPDATE event is treated as a "something changed" signal and the
-- client re-fetches through the decrypting REST endpoint (#124 — the payload
-- itself carries ciphertext `text`). Realtime only emits `postgres_changes`
-- for tables in the `supabase_realtime` publication, and no migration ever
-- added `room_messages` — the deployed environments got it via dashboard
-- configuration (the observed production behavior #124 fixed proves it is
-- published there). On a migrations-only schema (local Supabase, the E2E
-- stack) the events never fire, so cross-client chat propagation silently
-- does not happen. Needed by the #394 two-context study-room journey.
--
-- Guarded to be idempotent and safe everywhere:
--   * publication missing (bare Postgres without Realtime) -> no-op;
--   * table already published (hosted projects configured via dashboard)
--     -> no-op.
--
-- room_reactions stays unpublished on purpose: its realtime handlers were
-- removed as dead code in #231 pending the RLS/Realtime-authorization work.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'supabase_realtime')
       AND NOT EXISTS (
           SELECT 1
             FROM pg_publication_tables
            WHERE pubname = 'supabase_realtime'
              AND schemaname = 'public'
              AND tablename = 'room_messages'
       ) THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE public.room_messages;
    END IF;
END
$$;
