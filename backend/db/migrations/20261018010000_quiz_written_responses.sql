-- Written answers contain student content: store the JSON value encrypted,
-- using the same application encryption as quiz_attempts.answers_json.
-- Idempotent (guarded) so a partially applied environment can be reconciled.
ALTER TABLE quiz_responses ALTER COLUMN selected_index DROP NOT NULL;
ALTER TABLE quiz_responses ADD COLUMN IF NOT EXISTS answer_text TEXT;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'quiz_responses_answer_kind_check'
          AND conrelid = 'quiz_responses'::regclass
    ) THEN
        ALTER TABLE quiz_responses ADD CONSTRAINT quiz_responses_answer_kind_check
            CHECK ((selected_index IS NOT NULL AND answer_text IS NULL)
                OR (selected_index IS NULL AND answer_text IS NOT NULL));
    END IF;
END $$;
