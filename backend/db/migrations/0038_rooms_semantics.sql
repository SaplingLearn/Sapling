-- 0038: give the #405 rooms columns real semantics ("real ownership +
-- public rooms").
--
-- 0032 added topic/course/owner_id/updated_at/is_public nullable and
-- unpopulated (its header deliberately deferred the semantics to #405).
-- This migration backfills and constrains them:
--   * owner_id := created_by for existing rows — ownership starts with the
--     creator and is TRANSFERABLE later; created_by stays the immutable
--     creator record. Authorization (kick, future transfer/delete) keys on
--     owner_id from here on.
--   * is_public: DEFAULT false + NOT NULL (NULL was neither public nor
--     private). false = invite-only; true = joinable without an invite via
--     POST /api/social/public-rooms/{id}/join and listed by
--     GET /api/social/public-rooms.
--   * updated_at: DEFAULT now() + backfill from created_at; membership
--     changes touch it in code (routes/social.py::_touch_room).

UPDATE rooms SET owner_id = created_by WHERE owner_id IS NULL;
ALTER TABLE rooms ALTER COLUMN owner_id SET NOT NULL;

UPDATE rooms SET is_public = FALSE WHERE is_public IS NULL;
ALTER TABLE rooms ALTER COLUMN is_public SET DEFAULT FALSE;
ALTER TABLE rooms ALTER COLUMN is_public SET NOT NULL;

UPDATE rooms SET updated_at = created_at WHERE updated_at IS NULL;
ALTER TABLE rooms ALTER COLUMN updated_at SET DEFAULT now();
