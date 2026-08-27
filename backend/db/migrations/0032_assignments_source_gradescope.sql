-- 0032: allow 'gradescope' as an assignments.source value.
--
-- `0021_gradebook.sql` recreated `assignments` with
--     source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','syllabus'))
-- because the two writers it was written against (routes/gradebook.py) only ever
-- emit those two values. But routes/gradescope.py::sync_course writes
--     record_write = {..., "source": "gradescope", ...}
-- on BOTH the insert and the update path, so every row the Gradescope sync tried
-- to write violated the CHECK. The route catches the failure per-assignment and
-- counts it into `failed`, so /api/gradescope/sync/{id} returned HTTP 200 with
-- {inserted: 0, updated: 0, failed: N} — a sync that reported success in the UI
-- while writing nothing.
--
-- The pre-redesign column (0012_gradebook.sql) was a bare `TEXT DEFAULT 'manual'`
-- with no CHECK, which is why the Gradescope code was correct when it was written
-- and silently became wrong when 0021 tightened the column.
--
-- 'gradescope' is real provenance and worth keeping distinct from 'manual' (the
-- gradebook UI shows synced rows differently and must not let a sync clobber a
-- hand-entered grade), so widen the constraint rather than making the route lie
-- about where the row came from.

-- Drop by definition rather than by assumed name: the 0021 constraint is an
-- inline column CHECK, so Postgres auto-named it `assignments_source_check`, but
-- a re-created table could have picked up a numeric suffix. Matching on the
-- constraint body finds it either way, and leaves a DB that already has the
-- widened form untouched (its definition no longer lacks 'gradescope').
DO $$
DECLARE
  conname_found TEXT;
BEGIN
  SELECT c.conname INTO conname_found
  FROM pg_constraint c
  JOIN pg_class t ON t.oid = c.conrelid
  WHERE t.relname = 'assignments'
    AND c.contype = 'c'
    AND pg_get_constraintdef(c.oid) LIKE '%syllabus%'
    AND pg_get_constraintdef(c.oid) NOT LIKE '%gradescope%'
  LIMIT 1;

  IF conname_found IS NOT NULL THEN
    EXECUTE format('ALTER TABLE assignments DROP CONSTRAINT %I', conname_found);
  END IF;
END $$;

-- Re-add the widened constraint. Guarded so a replay after the drop above (or on
-- a DB that never had the narrow form) is a clean no-op.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    WHERE t.relname = 'assignments'
      AND c.contype = 'c'
      AND c.conname = 'assignments_source_check'
  ) THEN
    ALTER TABLE assignments
      ADD CONSTRAINT assignments_source_check
      CHECK (source IN ('manual', 'syllabus', 'gradescope'));
  END IF;
END $$;
