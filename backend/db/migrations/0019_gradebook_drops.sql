-- Gradebook drops policy: per-category "drop the N lowest assignments".
-- Idempotent — safe to re-run.

ALTER TABLE course_categories
  ADD COLUMN IF NOT EXISTS drop_lowest INTEGER NOT NULL DEFAULT 0;

-- Guard rail: never negative.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'course_categories_drop_lowest_nonneg'
  ) THEN
    ALTER TABLE course_categories
      ADD CONSTRAINT course_categories_drop_lowest_nonneg
      CHECK (drop_lowest >= 0);
  END IF;
END $$;
