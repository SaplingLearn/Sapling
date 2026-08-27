-- 0032: allow 'gradescope' as an assignments.source value.
--
-- `0021_gradebook.sql` recreated `assignments` with
--     source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','syllabus'))
-- because routes/gradebook.py, its only writer at the time, emits exactly those
-- two. But routes/gradescope.py::sync_course writes
--     record_write = {..., "source": "gradescope", ...}
-- on BOTH its insert and its update path, so every row the Gradescope sync tried
-- to write was rejected with 23514 (check_violation). The route catches failures
-- per-assignment into `failed`, so POST /api/gradescope/sync/{id} returned HTTP
-- 200 with {inserted: 0, updated: 0, failed: N} — a sync that reported success
-- in the UI while writing nothing. Confirmed live against the staging database
-- before this fix: source='manual' accepted, source='gradescope' rejected.
--
-- The pre-redesign column (0012_gradebook.sql) was a bare `TEXT DEFAULT 'manual'`
-- with no CHECK, so the Gradescope code was correct when written and silently
-- became wrong when 0021 tightened the column underneath it.
--
-- 'gradescope' is real provenance worth keeping distinct from 'manual' (a sync
-- must never look like a hand-entered grade), so widen the constraint rather
-- than making the route misreport where the row came from.

-- Drop by DEFINITION, not by name.
--
-- main's equivalent migration (0042_assignments_source_gradescope.sql) does
--     ALTER TABLE assignments DROP CONSTRAINT IF EXISTS assignments_source_check;
-- which assumes Postgres's default name for 0021's inline CHECK. When a table
-- has been recreated the original can carry a numeric suffix
-- (`assignments_source_check1`), and then the DROP silently no-ops while the ADD
-- succeeds — leaving BOTH constraints in place. Both are enforced, the narrow
-- one still rejects 'gradescope', and the migration is recorded as applied
-- having changed nothing. Matching on the constraint body avoids that trap and
-- clears every narrow variant, however many there are.
DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT c.conname
    FROM pg_constraint c
    WHERE c.conrelid = 'public.assignments'::regclass
      AND c.contype = 'c'
      AND pg_get_constraintdef(c.oid) ILIKE '%syllabus%'
      AND pg_get_constraintdef(c.oid) NOT ILIKE '%gradescope%'
  LOOP
    EXECUTE format('ALTER TABLE public.assignments DROP CONSTRAINT %I', r.conname);
    RAISE NOTICE 'dropped narrow assignments.source CHECK: %', r.conname;
  END LOOP;
END $$;

-- Re-add widened, NOT VALID.
--
-- NOT VALID is about lock behaviour, not data: {manual, syllabus} is a strict
-- subset of the new set, so every existing row already satisfies it by
-- construction. A plain ADD CONSTRAINT ... CHECK holds ACCESS EXCLUSIVE on
-- `assignments` for the whole validation scan, blocking every read and write to
-- the gradebook's busiest table. NOT VALID skips the scan while still enforcing
-- on every new and updated row, which is all this needs. Matches main's 0042.
--
-- Guarded so a replay (or an environment already carrying the widened form,
-- including one fixed by hand ahead of this migration) is a clean no-op.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conrelid = 'public.assignments'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) ILIKE '%gradescope%'
  ) THEN
    ALTER TABLE public.assignments
      ADD CONSTRAINT assignments_source_check
      CHECK (source IN ('manual', 'syllabus', 'gradescope')) NOT VALID;
  END IF;
END $$;
