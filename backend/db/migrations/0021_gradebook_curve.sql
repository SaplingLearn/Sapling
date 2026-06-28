-- Gradebook bell-curve grading: per-course curve policy + per-assignment class stats.
-- Idempotent — safe to re-run.
--
-- routes/gradebook.py reads/writes these columns:
--   user_courses.curve_mode / curve_avg_target / curve_sd_delta  (course curve policy)
--   assignments.curve_class_mean / curve_class_sd / curve_avg_target / curve_sd_delta
-- These are plaintext NUMERIC class statistics (not student-identifying), read as
-- floats by services/gradebook_service.py — unlike points_earned/points_possible
-- which are encrypted TEXT (see migration_encryption_text_columns.sql).

-- Per-course curve policy on the enrollment row.
ALTER TABLE user_courses
  ADD COLUMN IF NOT EXISTS curve_mode       TEXT NOT NULL DEFAULT 'raw',
  ADD COLUMN IF NOT EXISTS curve_avg_target NUMERIC,
  ADD COLUMN IF NOT EXISTS curve_sd_delta   NUMERIC;

-- Per-assignment class statistics + optional per-assignment policy override.
ALTER TABLE assignments
  ADD COLUMN IF NOT EXISTS curve_class_mean NUMERIC,
  ADD COLUMN IF NOT EXISTS curve_class_sd   NUMERIC,
  ADD COLUMN IF NOT EXISTS curve_avg_target NUMERIC,
  ADD COLUMN IF NOT EXISTS curve_sd_delta   NUMERIC;

-- Guard rail: curve_mode is a closed enum ('raw' = no curve, 'curved' = apply policy).
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'user_courses_curve_mode_valid'
  ) THEN
    ALTER TABLE user_courses
      ADD CONSTRAINT user_courses_curve_mode_valid
      CHECK (curve_mode IN ('raw', 'curved'));
  END IF;
END $$;
