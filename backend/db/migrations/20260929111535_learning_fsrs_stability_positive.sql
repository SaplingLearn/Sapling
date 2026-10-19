-- 20260929111535_learning_fsrs_stability_positive.sql  (spec §4; PKG-12 fix round)
-- Learning loop series PKG-12: an FSRS stability is a finite positive number of
-- days, or NULL (never scheduled: the reader uses FSRS_S0_GOOD). The review queue
-- skips a row that breaks this (learning/review.py::InvalidStability); this makes
-- the database refuse one. In Postgres 'NaN' compares greater than every number,
-- including 'Infinity', so `< 'Infinity'` excludes both NaN and +Infinity.
-- Existing rows: the only writers are graph_service._fsrs_after (learner_state)
-- and learning/flashcard_fsrs.flashcard_fsrs_update (flashcards), both through
-- learning.fsrs.next_state, which floors every new stability at
-- FSRS_STABILITY_MIN (0.001) and is finite for finite input
-- (tests/test_learning_review.py::test_fsrs_writers_never_store_an_invalid_stability).
-- Existing tables: RLS/grants unchanged.
ALTER TABLE learner_state DROP CONSTRAINT IF EXISTS learner_state_fsrs_s_positive;
ALTER TABLE learner_state ADD CONSTRAINT learner_state_fsrs_s_positive
    CHECK (fsrs_s IS NULL OR (fsrs_s > 0 AND fsrs_s < 'Infinity'::double precision));
ALTER TABLE flashcards DROP CONSTRAINT IF EXISTS flashcards_fsrs_s_positive;
ALTER TABLE flashcards ADD CONSTRAINT flashcards_fsrs_s_positive
    CHECK (fsrs_s IS NULL OR (fsrs_s > 0 AND fsrs_s < 'Infinity'::double precision));
