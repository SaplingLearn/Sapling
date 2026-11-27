-- W7.8: Practice vs Exam Twin session mode on each quiz attempt.
--
-- practice (default) = learning evidence path (A132/A145 → farm → help → graph).
-- exam_twin = score-only, tool-light; never writes mastery and never claims the
-- A100 farm window (must not double-count / block daily Practice evidence).
--
-- Nullable with DEFAULT 'practice' so legacy rows and omitted inserts read as
-- Practice. CHECK keeps the wire vocabulary closed.
ALTER TABLE quiz_attempts
    ADD COLUMN IF NOT EXISTS session_mode TEXT;

UPDATE quiz_attempts
    SET session_mode = 'practice'
    WHERE session_mode IS NULL;

ALTER TABLE quiz_attempts
    ALTER COLUMN session_mode SET DEFAULT 'practice';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'quiz_attempts_session_mode_check'
    ) THEN
        ALTER TABLE quiz_attempts
            ADD CONSTRAINT quiz_attempts_session_mode_check
            CHECK (session_mode IN ('practice', 'exam_twin'));
    END IF;
END $$;

ALTER TABLE quiz_attempts
    ALTER COLUMN session_mode SET NOT NULL;
