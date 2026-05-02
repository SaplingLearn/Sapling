-- Adds course_id to flashcards so imports can attach to a real course
-- without renaming the existing topic column. Existing rows stay NULL.

ALTER TABLE flashcards
  ADD COLUMN IF NOT EXISTS course_id TEXT REFERENCES courses(id);

CREATE INDEX IF NOT EXISTS idx_flashcards_user_course
  ON flashcards(user_id, course_id);
