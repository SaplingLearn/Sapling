-- 20261108110805_learning_misconception_resolved_reason.sql
-- Learning loop spec §13 A127 × A123: misconceptions.resolved_reason names why
-- an open misconception closed.
--
-- A123 (20261108072715_learning_evidence_void.sql) added the column with a
-- CHECK that admits one value, 'evidence_void': the void closure, which runs
-- when every attempt supporting a misconception was graded against a retired
-- item. A127's misconceptions.resolve() closes a misconception when the student
-- answers an isomorph (the same concept, another question) correctly and
-- unassisted. It now records 'correct_unassisted_isomorph', so the CHECK admits
-- both. These are the only two writers of resolved_at. A row closed before
-- this change keeps NULL (unknown, never inferred).
--
-- Apply it BEFORE the code. Against the old CHECK, resolve()'s UPDATE is
-- refused (23514); resolve() fails closed (it logs a WARNING and closes
-- nothing), so a misconception stays open rather than closing without its
-- reason.
--
-- Matches on the constraint BODY, not an assumed name (the
-- 20260828172725_assignments_source_check_by_definition.sql lesson, as A116's
-- 20261108050630 does: a DROP by name no-ops on a suffixed variant, and the
-- narrow CHECK stays enforced beside the wide one). The widened one keeps
-- A123's name, misconceptions_resolved_reason_check.
--
-- Idempotent: on a re-run the first block matches nothing (every
-- resolved_reason CHECK already names 'correct_unassisted_isomorph') and the
-- guarded ADD is skipped. No row is written.

DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT c.conname
    FROM pg_constraint c
    WHERE c.conrelid = 'public.misconceptions'::regclass
      AND c.contype = 'c'
      AND pg_get_constraintdef(c.oid) ILIKE '%resolved_reason%'
      AND pg_get_constraintdef(c.oid) NOT ILIKE '%correct_unassisted_isomorph%'
  LOOP
    EXECUTE format('ALTER TABLE public.misconceptions DROP CONSTRAINT %I', r.conname);
    RAISE NOTICE 'dropped narrow misconceptions.resolved_reason CHECK: %', r.conname;
  END LOOP;
END $$;

-- NOT VALID for lock behaviour, not data: the old list is a strict subset of
-- this one, so no existing row can violate it, and a validating ADD would hold
-- ACCESS EXCLUSIVE on misconceptions (every wrong answer with a matched key
-- writes to it) for a scan that buys nothing. New and updated rows are checked
-- either way. The same choice A116 and 20260828172725 make.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conrelid = 'public.misconceptions'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) ILIKE '%resolved_reason%'
      AND pg_get_constraintdef(oid) ILIKE '%correct_unassisted_isomorph%'
  ) THEN
    ALTER TABLE public.misconceptions
      ADD CONSTRAINT misconceptions_resolved_reason_check
      CHECK (resolved_reason IS NULL OR resolved_reason IN ('evidence_void','correct_unassisted_isomorph')) NOT VALID;
  END IF;
END $$;
