-- Written answers contain student content: store the JSON value encrypted,
-- using the same application encryption as quiz_attempts.answers_json.
ALTER TABLE quiz_responses ALTER COLUMN selected_index DROP NOT NULL;
ALTER TABLE quiz_responses ADD COLUMN answer_text TEXT;
ALTER TABLE quiz_responses ADD CONSTRAINT quiz_responses_answer_kind_check
    CHECK ((selected_index IS NOT NULL AND answer_text IS NULL)
        OR (selected_index IS NULL AND answer_text IS NOT NULL));
