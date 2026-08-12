-- #540 A1: 'adaptive' becomes a real request-side difficulty. The attempt row
-- records what the student asked for (the response's resolved_difficulty
-- reports what generation actually produced), so the 0025 CHECK
-- (easy|medium|hard) must admit 'adaptive'.
--
-- DEPLOY ORDER: widening the CHECK is backward-compatible — apply this
-- migration BEFORE deploying the code that accepts 'adaptive'. In the gap the
-- other way around, an adaptive generate runs the full LLM call and then 500s
-- on the INSERT. (The promote runner migrates before merging; for staging run
-- `python -m db.migrate` before the deploy picks up the code.)
--
-- The DROP is by introspection, not by an assumed default name: environments
-- with out-of-band table history (staging has had some) can carry the same
-- CHECK under a different name, and a name-keyed `DROP IF EXISTS` would
-- silently no-op and leave the narrow constraint alive beside the new one.
DO $$
DECLARE c record;
BEGIN
    FOR c IN
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'quiz_attempts'::regclass
          AND contype = 'c'
          AND pg_get_constraintdef(oid) ILIKE '%difficulty%'
    LOOP
        EXECUTE format('ALTER TABLE quiz_attempts DROP CONSTRAINT %I', c.conname);
    END LOOP;
END $$;

ALTER TABLE quiz_attempts
    ADD CONSTRAINT quiz_attempts_difficulty_check
    CHECK (difficulty IN ('easy', 'medium', 'hard', 'adaptive'));
