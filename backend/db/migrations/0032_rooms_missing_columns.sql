-- 0032: add the rooms columns routes/social.py already reads (#405).
--
-- `rooms` was created in 0001 with only id/name/invite_code/created_by/
-- created_at, but social.py selects `topic, course, owner_id, updated_at,
-- is_public` in four places (join-by-invite, list-my-rooms, room overview,
-- kick authorization). On any schema that replays purely from migrations
-- (local Supabase, the E2E stack) PostgREST rejects the select with 42703
-- ("column rooms.topic does not exist") and every one of those endpoints
-- 500s — which blocks the study-room E2E journey (#394).
--
-- This migration only reconciles the schema with the column list the code
-- reads. The columns stay nullable and unpopulated: deciding their semantics
-- (owner_id vs created_by, is_public default, and populating them in
-- create_room) remains open product work tracked in #405.
--
-- IF NOT EXISTS keeps this a no-op on any environment where the columns
-- already exist via historical dashboard DDL drift.

ALTER TABLE rooms
    ADD COLUMN IF NOT EXISTS topic      TEXT,
    ADD COLUMN IF NOT EXISTS course     TEXT,
    ADD COLUMN IF NOT EXISTS owner_id   TEXT,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS is_public  BOOLEAN;
