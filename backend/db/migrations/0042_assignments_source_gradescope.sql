-- 0042: allow 'gradescope' as an assignment source (#265).
--
-- 0021 recreated `assignments` with
--   source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','syllabus'))
-- but routes/gradescope.py::sync_course writes source='gradescope' on every
-- synced row. So even once the column drift in that module is fixed, every
-- insert would fail the CHECK — the sync has no valid value to write.
--
-- Widening only: {manual, syllabus} is a strict subset of the new set, so every
-- existing row already satisfies it and the constraint is added VALIDATED
-- rather than NOT VALID (nothing to grandfather).
--
-- The constraint name is Postgres's default for the inline CHECK in 0021
-- (`<table>_<column>_check`); DROP ... IF EXISTS keeps this replay-safe on an
-- environment where it was already renamed or absent.

ALTER TABLE assignments DROP CONSTRAINT IF EXISTS assignments_source_check;

ALTER TABLE assignments ADD CONSTRAINT assignments_source_check
    CHECK (source IN ('manual', 'syllabus', 'gradescope'));
