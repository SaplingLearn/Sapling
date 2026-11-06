-- #760 (state-machine audit, workstream D): an attempt is never BOTH
-- completed and abandoned.
--
-- Status is derived from the two stamps (completed_at → completed,
-- abandoned_at → abandoned, else in_progress — 20260813013547), so a row
-- carrying both is a state the lifecycle has no name for; the derived status
-- silently picks "completed". Every writer now claims conditionally on the
-- OTHER stamp being NULL (submit's claim since #537 G4's review, the abandon
-- route, the lazy sweep), so no current code path can produce one — this
-- makes the database say so too, for whatever writer comes next.
--
-- Existing rows. Before submit's claim also filtered on abandoned_at IS NULL,
-- a submit racing a Discard (or the sweep) in another tab could win both
-- claims, so a pre-existing violator is possible. Three steps, in one
-- transaction (db/migrate.py wraps each file in one):
--   1. ADD ... NOT VALID — enforced for every new write from here on, without
--      checking the old rows yet.
--   2. Repair the old rows. A row with a SCORE was really submitted (score,
--      mastery and XP were all paid out after the claim), so the abandon stamp
--      is the one that lost: clear it. A row with NO score never finished
--      grading (the completed-but-scoreless strand #760 also fixes), so it was
--      never a completed quiz — no XP is paid before the score lands — and it
--      reads as what the student did: abandoned. Clear completed_at.
--   3. VALIDATE — now cannot fail, and proves step 2 left nothing behind.
--
-- Idempotent: the duplicate_object guard skips step 1 on a re-run, step 2
-- matches no rows once applied, and VALIDATE on a validated constraint is a
-- no-op.
DO $$
BEGIN
    ALTER TABLE quiz_attempts
        ADD CONSTRAINT quiz_attempts_not_completed_and_abandoned
        CHECK (completed_at IS NULL OR abandoned_at IS NULL) NOT VALID;
EXCEPTION
    WHEN duplicate_object THEN NULL;  -- already present; nothing to do
END $$;

UPDATE quiz_attempts
   SET abandoned_at = NULL
 WHERE completed_at IS NOT NULL
   AND abandoned_at IS NOT NULL
   AND score IS NOT NULL;

UPDATE quiz_attempts
   SET completed_at = NULL
 WHERE completed_at IS NOT NULL
   AND abandoned_at IS NOT NULL
   AND score IS NULL;

ALTER TABLE quiz_attempts
    VALIDATE CONSTRAINT quiz_attempts_not_completed_and_abandoned;
