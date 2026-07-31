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
