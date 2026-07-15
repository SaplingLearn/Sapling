-- 0027: Gradescope sync tables, absorbed from origin/Gradebook (0020_gradescope) and
-- re-expressed against the redesign. The assignments.gradescope_assignment_id column +
-- idempotency index live in 0021 (assignments is created there).
-- 🔒 = column-encrypted (stays TEXT).
--
-- REWIRE NEEDED (see filed issue): the per-course link is re-targeted from courses(id) to
-- enrollments(id), because gradescope sync writes into a specific enrolled class's gradebook
-- (assignments are now enrollment-scoped). Confirm this matches the intended picker UX.

-- Encrypted Gradescope credentials, one row per user. Unchanged from the original.
CREATE TABLE gradescope_credentials (
    user_id            TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    auth_mode          TEXT NOT NULL DEFAULT 'password' CHECK (auth_mode IN ('password','cookies')),
    email_encrypted    TEXT,   -- 🔒
    password_encrypted TEXT,   -- 🔒
    cookies_encrypted  TEXT,   -- 🔒
    last_synced_at     TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT gradescope_credentials_payload_chk CHECK (
        (auth_mode = 'password' AND email_encrypted IS NOT NULL AND password_encrypted IS NOT NULL)
        OR (auth_mode = 'cookies' AND cookies_encrypted IS NOT NULL)
    )
);

-- Per-enrollment link to a Gradescope course id (was per (user, courses.id)).
CREATE TABLE gradescope_course_links (
    id                   TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    enrollment_id        TEXT NOT NULL REFERENCES enrollments(id) ON DELETE CASCADE,
    gradescope_course_id TEXT NOT NULL,
    last_synced_at       TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (enrollment_id, gradescope_course_id)
);
CREATE INDEX idx_gradescope_links_enrollment ON gradescope_course_links(enrollment_id);

DROP TRIGGER IF EXISTS trg_gradescope_credentials_updated_at ON gradescope_credentials;
CREATE TRIGGER trg_gradescope_credentials_updated_at BEFORE UPDATE ON gradescope_credentials
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
