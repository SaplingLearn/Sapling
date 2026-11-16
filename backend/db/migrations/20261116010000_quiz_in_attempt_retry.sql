ALTER TABLE quiz_responses
    ADD COLUMN IF NOT EXISTS skipped BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS retry_enabled BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE quiz_responses DROP CONSTRAINT IF EXISTS quiz_responses_answer_kind_check;
ALTER TABLE quiz_responses ADD CONSTRAINT quiz_responses_answer_kind_check CHECK (
    (skipped AND selected_index IS NULL AND answer_text IS NULL AND NOT is_correct AND retry_correct IS NULL)
    OR (NOT skipped AND ((selected_index IS NOT NULL) <> (answer_text IS NOT NULL)))
);

CREATE OR REPLACE FUNCTION record_quiz_retry(
    p_attempt_id TEXT, p_user_id TEXT, p_question_index INTEGER, p_correct BOOLEAN
)
RETURNS TABLE (retry_correct BOOLEAN)
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
    -- Serialize with the attempt's submit and abandonment claims.
    PERFORM 1 FROM quiz_attempts
    WHERE id = p_attempt_id AND user_id = p_user_id
      AND completed_at IS NULL AND abandoned_at IS NULL
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN;
    END IF;

    RETURN QUERY
    UPDATE quiz_responses AS response
    SET retry_correct = COALESCE(response.retry_correct, p_correct)
    WHERE response.attempt_id = p_attempt_id AND response.question_index = p_question_index
      AND response.retry_enabled AND NOT response.is_correct AND NOT response.skipped
    RETURNING response.retry_correct;
END;
$$;
REVOKE ALL ON FUNCTION record_quiz_retry(TEXT, TEXT, INTEGER, BOOLEAN) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION record_quiz_retry(TEXT, TEXT, INTEGER, BOOLEAN) TO service_role;
