-- Gradescope sync: encrypted per-user credentials + per-course linking +
-- idempotent assignment upsert. Idempotent — safe to re-run.

-- 1. Encrypted Gradescope credentials, one row per user.
--    Two auth modes:
--      'password' — email + password ciphertext; backend logs in fresh on
--                   each sync. Won't work for SSO-only accounts (BU, etc.).
--      'cookies'  — pasted browser session cookies (JSON {signed_token,
--                   _gradescope_session}). Required for SSO students.
--                   Cookies typically last ~2 weeks before re-paste.
--    Always one row per user. Switching modes overwrites the previous.
CREATE TABLE IF NOT EXISTS gradescope_credentials (
  user_id            TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  auth_mode          TEXT NOT NULL DEFAULT 'password',
  email_encrypted    TEXT,
  password_encrypted TEXT,
  cookies_encrypted  TEXT,
  last_synced_at     TIMESTAMPTZ,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Idempotent column adds for existing tables created from the first
-- version of this migration (which had NOT NULL email/password and
-- no auth_mode / cookies columns).
ALTER TABLE gradescope_credentials
  ADD COLUMN IF NOT EXISTS auth_mode         TEXT NOT NULL DEFAULT 'password',
  ADD COLUMN IF NOT EXISTS cookies_encrypted TEXT;
ALTER TABLE gradescope_credentials
  ALTER COLUMN email_encrypted    DROP NOT NULL,
  ALTER COLUMN password_encrypted DROP NOT NULL;

-- Sanity guard: a row must have at least one auth payload that matches
-- its declared mode.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'gradescope_credentials_payload_chk'
  ) THEN
    ALTER TABLE gradescope_credentials
      ADD CONSTRAINT gradescope_credentials_payload_chk CHECK (
        (auth_mode = 'password' AND email_encrypted IS NOT NULL AND password_encrypted IS NOT NULL)
        OR (auth_mode = 'cookies' AND cookies_encrypted IS NOT NULL)
      );
  END IF;
END $$;

-- 2. Per-(user, sapling-course) link to a Gradescope course id.
--    The user picks which Sapling course each Gradescope course corresponds to.
CREATE TABLE IF NOT EXISTS gradescope_course_links (
  id                    TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
  user_id               TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  sapling_course_id     TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  gradescope_course_id  TEXT NOT NULL,
  last_synced_at        TIMESTAMPTZ,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, sapling_course_id)
);

CREATE INDEX IF NOT EXISTS idx_gradescope_links_user
  ON gradescope_course_links(user_id);

-- 3. Add idempotency key on assignments — the Gradescope assignment id.
--    Used by the sync route as the unique key for upserts so re-running
--    sync updates grades on existing rows rather than duplicating them.
ALTER TABLE assignments
  ADD COLUMN IF NOT EXISTS gradescope_assignment_id TEXT;

-- Partial unique index: only enforce uniqueness when the id is non-null,
-- so manual / syllabus assignments stay unconstrained.
CREATE UNIQUE INDEX IF NOT EXISTS idx_assignments_gradescope_id
  ON assignments(course_id, gradescope_assignment_id)
  WHERE gradescope_assignment_id IS NOT NULL;
