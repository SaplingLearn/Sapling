-- 20260927035346_learning_flashcards_fsrs.sql
-- Learning loop series PKG-11: FSRS-6 state on flashcards (spec §3.2, §4).
-- Written only by routes/flashcards.py::rate_card when
-- learning.gate.learning_loop_active() is true; NULL on every legacy row.
ALTER TABLE flashcards
  ADD COLUMN IF NOT EXISTS fsrs_d double precision,
  ADD COLUMN IF NOT EXISTS fsrs_s double precision,
  ADD COLUMN IF NOT EXISTS due_at timestamptz,
  ADD COLUMN IF NOT EXISTS reps int NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS lapses int NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS flashcards_due_idx ON flashcards (user_id, due_at);
