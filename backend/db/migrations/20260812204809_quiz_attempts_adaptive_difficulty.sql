-- #540 A1: 'adaptive' becomes a real request-side difficulty. The attempt row
-- records what the student asked for (the response's resolved_difficulty
-- reports what generation actually produced), so the 0025 CHECK
-- (easy|medium|hard) must admit 'adaptive'.
--
-- Idempotent: DROP IF EXISTS + re-ADD. The constraint name is the PG default
-- for 0025's inline CHECK on quiz_attempts(difficulty).

ALTER TABLE quiz_attempts
    DROP CONSTRAINT IF EXISTS quiz_attempts_difficulty_check;

ALTER TABLE quiz_attempts
    ADD CONSTRAINT quiz_attempts_difficulty_check
    CHECK (difficulty IN ('easy', 'medium', 'hard', 'adaptive'));
