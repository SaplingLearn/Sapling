-- #542 D1/D2: attempt lifecycle columns.
--
-- mastery_before/after: without them a replayed or audited submit can't
-- reconstruct what the student saw, and no history UI can show progression
-- (plaintext analytics scalars, same rationale as score/total in #521).
--
-- abandoned_at: the "abandoned" half of the derived status. Status is NEVER
-- stored — it is derived at read time (completed_at → completed,
-- abandoned_at → abandoned, else in_progress), so it cannot drift from the
-- timestamps that define it. The lazy per-user sweep (routes/quiz.py) stamps
-- abandoned_at on in-progress attempts older than the documented TTL.

-- IF NOT EXISTS per the repo's idempotent-DDL rule: a migration that half
-- applied must be re-runnable without hand-editing the ledger.
ALTER TABLE quiz_attempts
    ADD COLUMN IF NOT EXISTS mastery_before DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS mastery_after  DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS abandoned_at   TIMESTAMPTZ;

-- Partial index for the lazy abandon sweep + the history read, both of
-- which filter on (user_id, completed_at IS NULL, abandoned_at IS NULL).
CREATE INDEX IF NOT EXISTS idx_quiz_attempts_user_open
    ON quiz_attempts(user_id, created_at)
    WHERE completed_at IS NULL AND abandoned_at IS NULL;
