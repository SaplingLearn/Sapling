-- backend/db/migrations/0033_add_gradescope_links.sql
--
-- Explicit user-chosen mapping between a Sapling course and a Gradescope
-- course, matching frontend's GradescopeLink type (frontend/src/lib/api.ts).
-- One Gradescope course can only be linked to one Sapling course per user,
-- and vice versa — hence the two unique constraints.

CREATE TABLE IF NOT EXISTS gradescope_links (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    sapling_course_id      UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    gradescope_course_id   TEXT NOT NULL,
    last_synced_at         TIMESTAMPTZ,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, sapling_course_id),
    UNIQUE (user_id, gradescope_course_id)
);

-- Adjust `courses(id)` above if your courses table has a different name/PK.

CREATE INDEX IF NOT EXISTS idx_gradescope_links_user_id
    ON gradescope_links (user_id);