-- #764 (state-machine audit, workstream G): room lifecycle.
--
-- 1. room_bans — a kick is a ban. Before this, kick_member only deleted the
--    room_members row, so the kicked student could rejoin at once with the
--    same invite code (or the public-join button). The kick now records a ban
--    row and both join paths (POST /rooms/join, POST /public-rooms/{id}/join)
--    refuse a banned user. Rows die with the room or the user.
--
-- 2. Rooms are now DELETED when their last member leaves (routes/social.py::
--    leave_room), which is what kills the invite code. The 0001 children of
--    `rooms` were created without ON DELETE, so a room with any message,
--    activity row, cached summary or member could not be deleted at all. They
--    become ON DELETE CASCADE so one `DELETE FROM rooms` is the whole,
--    atomic teardown. room_reactions already cascades off room_messages, and
--    users.current_room_id is already ON DELETE SET NULL (0024).
--    room_messages.reply_to_id becomes ON DELETE SET NULL: send_room_message
--    never checked that the replied-to message lives in the same room, so a
--    reply in ANOTHER room could otherwise pin a deleted room's message.
--
-- The FKs are found by (table, column, referenced table) rather than by their
-- default `<table>_<column>_fkey` names, because environments that predate the
-- baseline got these tables through dashboard DDL and the names are not
-- guaranteed. Idempotent: re-running drops and re-adds the same constraint.

CREATE TABLE IF NOT EXISTS room_bans (
    room_id    TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    banned_by  TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (room_id, user_id)
);

-- The API is the only client; nothing reaches this through anon/authenticated.
ALTER TABLE room_bans ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON room_bans FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON room_bans TO service_role;

DO $$
DECLARE
    spec RECORD;
    con  RECORD;
BEGIN
    FOR spec IN
        SELECT * FROM (VALUES
            ('room_members',   'room_id',     'rooms',         'id', 'CASCADE'),
            ('room_activity',  'room_id',     'rooms',         'id', 'CASCADE'),
            ('room_messages',  'room_id',     'rooms',         'id', 'CASCADE'),
            ('room_summaries', 'room_id',     'rooms',         'id', 'CASCADE'),
            ('room_messages',  'reply_to_id', 'room_messages', 'id', 'SET NULL')
        ) AS t(tbl, col, ref_tbl, ref_col, on_delete)
    LOOP
        IF to_regclass('public.' || spec.tbl) IS NULL THEN
            CONTINUE;
        END IF;

        FOR con IN
            SELECT c.conname
              FROM pg_constraint c
              JOIN pg_attribute a
                ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
             WHERE c.contype = 'f'
               AND c.conrelid = ('public.' || spec.tbl)::regclass
               AND c.confrelid = ('public.' || spec.ref_tbl)::regclass
               AND array_length(c.conkey, 1) = 1
               AND a.attname = spec.col
        LOOP
            EXECUTE format('ALTER TABLE public.%I DROP CONSTRAINT %I', spec.tbl, con.conname);
        END LOOP;

        EXECUTE format(
            'ALTER TABLE public.%I ADD CONSTRAINT %I FOREIGN KEY (%I) REFERENCES public.%I(%I) ON DELETE %s',
            spec.tbl, spec.tbl || '_' || spec.col || '_fkey', spec.col,
            spec.ref_tbl, spec.ref_col, spec.on_delete
        );
    END LOOP;
END $$;

-- 3. Backfill: bring rooms broken before #764 under the invariants the routes
--    now keep. A room whose owner is no longer a member passes to its
--    earliest remaining member; a room with no members at all is deleted (its
--    invite code was still live, and no endpoint lets anyone read it).
UPDATE rooms r
   SET owner_id = (
           SELECT m.user_id FROM room_members m
            WHERE m.room_id = r.id
            ORDER BY m.joined_at ASC NULLS LAST, m.user_id ASC
            LIMIT 1
       ),
       updated_at = now()
 WHERE EXISTS (SELECT 1 FROM room_members m WHERE m.room_id = r.id)
   AND NOT EXISTS (
           SELECT 1 FROM room_members m
            WHERE m.room_id = r.id AND m.user_id = r.owner_id
       );

DELETE FROM rooms r
 WHERE NOT EXISTS (SELECT 1 FROM room_members m WHERE m.room_id = r.id);
