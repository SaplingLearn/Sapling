-- 20260929081946_learning_sessions_mode_review.sql  (spec §4, Amendment A9)
-- Learning loop series PKG-12: daily review sessions are `sessions` rows so
-- successive-relearning counters can live in sessions.loop_state (PKG-06)
-- without a new column. 0025 constrained mode to socratic/expository/
-- teachback; widen it. The inline CHECK's default name is sessions_mode_check.
-- Existing table: RLS/grants unchanged.
ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_mode_check;
ALTER TABLE sessions ADD CONSTRAINT sessions_mode_check
    CHECK (mode IN ('socratic','expository','teachback','review'));
