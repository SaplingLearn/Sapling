-- Gradebook: extend assignments + user_courses, add course_categories.
-- Idempotent — safe to re-run.

-- 1. Extend assignments with grade fields and a source tag.
ALTER TABLE assignments
  ADD COLUMN IF NOT EXISTS category_id      TEXT,
  ADD COLUMN IF NOT EXISTS points_possible  NUMERIC,
  ADD COLUMN IF NOT EXISTS points_earned    NUMERIC,
  ADD COLUMN IF NOT EXISTS source           TEXT DEFAULT 'manual';

-- Allow null due_date so manually created graded items don't have to invent one.
-- Safe to re-run: DROP NOT NULL is a no-op on PG 14+ when the constraint is already absent.
ALTER TABLE assignments
  ALTER COLUMN due_date DROP NOT NULL;

-- 2. Per-(user, course) grading categories with weights.
CREATE TABLE IF NOT EXISTS course_categories (
  id          TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
  user_id     TEXT NOT NULL REFERENCES users(id),
  course_id   TEXT NOT NULL REFERENCES courses(id),
  name        TEXT NOT NULL,
  weight      NUMERIC NOT NULL,
  sort_order  INTEGER DEFAULT 0,
  created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_course_categories_user_course
  ON course_categories(user_id, course_id);

-- 3. Wire assignments.category_id to the new table.
-- PostgreSQL does not support ADD CONSTRAINT IF NOT EXISTS, so guard manually.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'assignments_category_id_fkey'
  ) THEN
    ALTER TABLE assignments
      ADD CONSTRAINT assignments_category_id_fkey
      FOREIGN KEY (category_id) REFERENCES course_categories(id)
      ON DELETE SET NULL;
  END IF;
END $$;

-- 4. Per-(user, course) grade-display preferences.
ALTER TABLE user_courses
  ADD COLUMN IF NOT EXISTS letter_scale     JSONB,
  ADD COLUMN IF NOT EXISTS syllabus_doc_id  TEXT REFERENCES documents(id);
