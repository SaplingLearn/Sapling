-- Re-apply the assignments.source widening, matching on the constraint BODY
-- rather than its name.
--
-- 0042_assignments_source_gradescope.sql already widened this set, and its
-- ledger row says it applied. It did run — it just did not necessarily do
-- anything, because it drops the old constraint by an assumed name:
--
--     ALTER TABLE assignments DROP CONSTRAINT IF EXISTS assignments_source_check;
--     ALTER TABLE assignments ADD CONSTRAINT assignments_source_check
--         CHECK (source IN ('manual','syllabus','gradescope')) NOT VALID;
--
-- `assignments_source_check` is Postgres's default name for the inline CHECK in
-- 0021, but a table that has been recreated can carry a suffixed variant
-- (`assignments_source_check1`). Where that happened the DROP silently no-ops,
-- the ADD succeeds, and BOTH constraints end up on the table. Both are
-- enforced, so the narrow one still rejects 'gradescope' — and 0042 is recorded
-- as applied having changed nothing observable.
--
-- This is not theoretical. On the database behind the deployed backend,
-- 0042 is present in schema_migrations and an INSERT with source='gradescope'
-- still failed with 23514 (check_violation) while source='manual' succeeded.
-- Every Gradescope sync against that database wrote zero rows, and
-- routes/gradescope.py::sync_course counts those into `failed` and still
-- returns HTTP 200 — so it reported success in the UI while writing nothing.
--
-- Matching on pg_get_constraintdef() finds the narrow constraint whatever it is
-- called, and the loop clears every variant rather than assuming there is one.
-- Idempotent: on a database where 0042 did land correctly, the loop matches
-- nothing and the guarded ADD is skipped.

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

-- NOT VALID for lock behaviour, not data: {manual, syllabus} is a strict subset
-- of the widened set, so no existing row can violate it and the validation scan
-- buys nothing. A validating ADD would hold ACCESS EXCLUSIVE on the gradebook's
-- busiest table for the length of the scan. Same choice 0042 and 0021 make.
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
