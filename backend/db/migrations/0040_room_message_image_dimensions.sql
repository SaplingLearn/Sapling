-- 0040: store intrinsic dimensions for room-chat image attachments (#315).
--
-- `room_messages` carries only `image_url`, so the client has nothing to
-- reserve space with and renders attachments into a zero-height box until the
-- image loads. With `loading="lazy"` (added by #312) that means scrolling UP
-- through history expands each image as it nears the viewport and shifts the
-- transcript mid-scroll. Chrome and Firefox mostly absorb it via scroll
-- anchoring; Safari has none, so the viewport visibly jumps on every load.
--
-- It also breaks the `loadEarlier` scrollTop compensation, which measures
-- scrollHeight before the prepended images have loaded.
--
-- Nullable and unpopulated by design: every message written before this
-- migration keeps NULL, and the client falls back to its current behaviour
-- for those rows. Backfilling would mean fetching every historical image to
-- measure it, which is not worth it for a layout hint.
--
-- IF NOT EXISTS so this is a no-op wherever the columns already exist.

ALTER TABLE room_messages
    ADD COLUMN IF NOT EXISTS image_width  INTEGER,
    ADD COLUMN IF NOT EXISTS image_height INTEGER;

-- Bounds at the database too, not only in the request model. These values are
-- client-supplied and the client renders them as an aspect-ratio, so an
-- absurd pair is a layout weapon against every member of the room rather than
-- a bad row for its author. Matches the CHECK convention 0021 established for
-- client-supplied numerics.
--
-- NOT VALID so the constraint applies to new writes without scanning existing
-- rows: every pre-existing row has NULL in both columns anyway, and NULL
-- passes a CHECK regardless.
DO $$
BEGIN
    ALTER TABLE room_messages
        ADD CONSTRAINT room_messages_image_dims_sane
        CHECK (
            (image_width  IS NULL OR (image_width  > 0 AND image_width  <= 20000))
            AND
            (image_height IS NULL OR (image_height > 0 AND image_height <= 20000))
        ) NOT VALID;
EXCEPTION
    WHEN duplicate_object THEN NULL;  -- already present; nothing to do
END $$;
