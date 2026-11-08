-- 20261108041742_learning_posttest_windows.sql
-- Learning loop, spec §13 A112 (docs/research/learning-loop/2026-11-07-direction-
-- audit.md rec. 2; the 2026-10-18 foundation audit's "fixed follow-up windows"):
-- the tool-removed post-test becomes an analyzable outcome measure, posed at
-- FIXED follow-up windows instead of "the last evidence is old enough" (which
-- every review postponed).
--
-- 1. One pose row per (student, node, window): `window_days` (a value of
--    learning/params.py POSTTEST_WINDOWS_DAYS) joins the primary key. Every
--    existing row was posed under the one-pose-per-node rule; it maps to the
--    7-day window and keeps its item, times and claim.
-- 2. The window's anchor: the concept's FIRST graded evidence, which practice
--    cannot move (node_mastery_events is append-only) — `anchor_event_id` (that
--    journal row's id) and `anchor_at` (its time).
-- 3. The delay the pose actually had: `last_evidence_at` (the concept's last
--    journaled evidence before the pose) and `days_since_evidence` (posed_at
--    minus it, in days), so an analysis can tell a truly delayed outcome from a
--    recently practised one.
-- 4. The outcome, written by the conditional UPDATE that closes the pose:
--    `correct`, and `max_rung` (the rung the grade carried; 0 = unassisted).
--
-- Rows posed before this migration keep NULL in 2-4: unknown, never inferred.
-- Hashes, ids, timestamps and numbers only — never item or answer text. RLS and
-- the backend-only grants are table-level (20260930024005) and unchanged.
-- Idempotent.

ALTER TABLE posttest_poses ADD COLUMN IF NOT EXISTS window_days integer;
UPDATE posttest_poses SET window_days = 7 WHERE window_days IS NULL;
ALTER TABLE posttest_poses ALTER COLUMN window_days SET NOT NULL;
ALTER TABLE posttest_poses DROP CONSTRAINT IF EXISTS posttest_poses_window_days_check;
ALTER TABLE posttest_poses ADD CONSTRAINT posttest_poses_window_days_check
  CHECK (window_days > 0);

-- Re-key on (user_id, node_id, window_days). The existing rows are unique on
-- (user_id, node_id), so with window 7 they stay unique. Guarded on the catalog:
-- a re-run with the new key in place changes nothing.
DO $$
DECLARE
    pk_name text;
    pk_def  text;
BEGIN
    SELECT conname, pg_get_constraintdef(oid) INTO pk_name, pk_def
      FROM pg_constraint
     WHERE conrelid = 'public.posttest_poses'::regclass AND contype = 'p';
    IF pk_def IS DISTINCT FROM 'PRIMARY KEY (user_id, node_id, window_days)' THEN
        IF pk_name IS NOT NULL THEN
            EXECUTE format('ALTER TABLE public.posttest_poses DROP CONSTRAINT %I', pk_name);
        END IF;
        ALTER TABLE public.posttest_poses
          ADD CONSTRAINT posttest_poses_pkey PRIMARY KEY (user_id, node_id, window_days);
    END IF;
END $$;

ALTER TABLE posttest_poses ADD COLUMN IF NOT EXISTS anchor_event_id text;
ALTER TABLE posttest_poses ADD COLUMN IF NOT EXISTS anchor_at timestamptz;
ALTER TABLE posttest_poses ADD COLUMN IF NOT EXISTS last_evidence_at timestamptz;
ALTER TABLE posttest_poses ADD COLUMN IF NOT EXISTS days_since_evidence double precision;
ALTER TABLE posttest_poses ADD COLUMN IF NOT EXISTS correct boolean;
ALTER TABLE posttest_poses ADD COLUMN IF NOT EXISTS max_rung smallint;

ALTER TABLE posttest_poses DROP CONSTRAINT IF EXISTS posttest_poses_days_since_evidence_check;
ALTER TABLE posttest_poses ADD CONSTRAINT posttest_poses_days_since_evidence_check
  CHECK (days_since_evidence IS NULL OR days_since_evidence >= 0);

-- An outcome is both columns or neither, only on an answered pose, and its rung
-- is a ladder rung (H0..H6). A renewal (A89/A93) resets all three together.
ALTER TABLE posttest_poses DROP CONSTRAINT IF EXISTS posttest_poses_outcome_check;
ALTER TABLE posttest_poses ADD CONSTRAINT posttest_poses_outcome_check
  CHECK (
    (correct IS NULL) = (max_rung IS NULL)
    AND (correct IS NULL OR answered_at IS NOT NULL)
    AND (max_rung IS NULL OR max_rung BETWEEN 0 AND 6)
  );

-- The admin learning-gain report reads the outcomes answered in a date range.
CREATE INDEX IF NOT EXISTS posttest_poses_answered_at
  ON posttest_poses (answered_at) WHERE answered_at IS NOT NULL;

-- PostgREST serves the new columns and key from its schema cache; reload it (a
-- no-op with no listener).
NOTIFY pgrst, 'reload schema';
