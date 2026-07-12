-- 0031_piazza_integration.sql
--
-- Piazza has no "list my classes" endpoint in the unofficial piazza-api
-- client, so courses are linked one at a time by network_id (pasted from
-- the course's Piazza URL) rather than auto-matched like Gradescope.
--
-- Credentials reuse external_connections (provider='piazza') -- no new
-- table needed for that part.
--
-- Rename the numeric prefix to match your actual next migration number.

CREATE TABLE IF NOT EXISTS piazza_links (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id     UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    network_id    TEXT NOT NULL,         -- Piazza's nid, e.g. "hl5qm84dl4t3x2"
    network_name  TEXT,                  -- cached display name from Piazza, for the UI
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, course_id)
);

CREATE TABLE IF NOT EXISTS piazza_posts (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id               UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id             UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    network_id            TEXT NOT NULL,
    piazza_post_id        TEXT NOT NULL,   -- external post/thread id (cid)
    post_type             TEXT,            -- 'question' | 'note' | 'poll' | ...
    is_instructor_answer  BOOLEAN NOT NULL DEFAULT false,
    folder                TEXT,
    subject               TEXT,            -- encrypted (encrypt_if_present) -- may contain student text
    content                TEXT,           -- encrypted (encrypt_if_present)
    piazza_created_at     TIMESTAMPTZ,     -- Piazza's own post timestamp
    synced_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, network_id, piazza_post_id)
);

CREATE INDEX IF NOT EXISTS idx_piazza_posts_user_course
    ON piazza_posts (user_id, course_id, piazza_created_at DESC);