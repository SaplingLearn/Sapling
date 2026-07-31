-- 0042: allow 'gradescope' as an assignment source (#265).
--
-- 0021 recreated `assignments` with
--   source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','syllabus'))
-- but routes/gradescope.py::sync_course writes source='gradescope' on every
-- synced row. So even once the column drift in that module is fixed, every
-- insert would fail the CHECK — the sync has no valid value to write.
--
-- Widening only: {manual, syllabus} is a strict subset of the new set, so every
-- existing row already satisfies it by construction.
--
-- Added NOT VALID anyway, and the reason is lock behaviour rather than data
-- (an earlier draft of this comment conflated the two). A plain ADD CONSTRAINT
-- ... CHECK takes ACCESS EXCLUSIVE on `assignments` for the whole validation
-- scan, blocking every read and write to the gradebook's busiest table for its
-- duration. NOT VALID skips that scan while still enforcing the constraint on
-- every new and updated row — which is all this needs, since existing rows
-- cannot violate a widened set. Matches 0021's convention for CHECKs on
-- populated tables.
--
-- The constraint name is Postgres's default for the inline CHECK in 0021
-- (`<table>_<column>_check`); DROP ... IF EXISTS keeps this replay-safe on an
-- environment where it was already renamed or absent.

ALTER TABLE assignments DROP CONSTRAINT IF EXISTS assignments_source_check;

ALTER TABLE assignments ADD CONSTRAINT assignments_source_check
    CHECK (source IN ('manual', 'syllabus', 'gradescope')) NOT VALID;
