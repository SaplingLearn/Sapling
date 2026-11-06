-- #771 (workstream M): dead state left behind by the 0020/0024 redesign.
--
-- users.current_room_id — renamed from users.room_id in 0024, and nothing has
-- written (or read) it since: room membership is room_members. Dropping it
-- also drops users_current_room_id_fkey. Any value still in it predates 0024
-- and is meaningless.
ALTER TABLE users DROP COLUMN IF EXISTS current_room_id;

-- courses.deleted_at — created by 0020 for a catalog soft-delete that was
-- never built: no code, script or SQL function ever sets it, and its one
-- reader (topic_checklist_service.resolve_scope) is removed in the same
-- change. Refuse rather than silently un-hide if someone DID set it by hand.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'public' AND table_name = 'courses'
           AND column_name = 'deleted_at'
    ) AND EXISTS (SELECT 1 FROM courses WHERE deleted_at IS NOT NULL) THEN
        RAISE EXCEPTION
            'courses.deleted_at is set on some rows; decide what those courses '
            'should be before dropping the column (#771)';
    END IF;
END $$;
ALTER TABLE courses DROP COLUMN IF EXISTS deleted_at;

-- documents.processed_at STAYS, documented: a documents row is only inserted
-- once processing has finished (routes/documents.py), so today it always
-- equals created_at. It is still the public meaning the canopy_metrics()
-- `documents_processed` counts key on (20260921055024) and the documents API
-- returns it (frontend Document.processed_at); keeping it lets processing
-- become asynchronous later without a contract change.
COMMENT ON COLUMN documents.processed_at IS
    'When processing finished. Rows are inserted only after processing, so this equals created_at today; canopy_metrics() documents_processed counts on it (#771).';
