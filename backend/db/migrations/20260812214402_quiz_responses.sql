-- #541 C2: per-question quiz responses. This is the table that makes item
-- statistics, timing analysis, and misconception mining possible — one row
-- per answered question, written by POST /api/quiz/attempts/{id}/answer.
--
-- Everything here is a plaintext analytics scalar (same rationale as
-- quiz_attempts.score/total in #521): indexes and booleans carry no student
-- free text. The question/option TEXT lives encrypted in
-- quiz_attempts.questions_json; this table references it only by position.
--
-- The UNIQUE is the C1 idempotency contract: one response per
-- (attempt, question); re-answering returns the first recorded response
-- (no revision — the #537 revamp decides if that changes).

CREATE TABLE quiz_responses (
    id              TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    attempt_id      TEXT NOT NULL REFERENCES quiz_attempts(id) ON DELETE CASCADE,
    question_index  INTEGER NOT NULL CHECK (question_index >= 0),
    selected_index  INTEGER NOT NULL CHECK (selected_index >= 0),
    is_correct      BOOLEAN NOT NULL,
    time_ms         INTEGER CHECK (time_ms >= 0),
    confidence      REAL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    answered_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT quiz_responses_attempt_question_key UNIQUE (attempt_id, question_index)
);

CREATE INDEX idx_quiz_responses_attempt ON quiz_responses(attempt_id);
