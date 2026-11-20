-- PR #866 Z36: an index led by check_items.question_hash.
--
-- The served-text scan set (services/loop/posed.py::posed_items: every loop
-- turn, and every notes or flashcards request through the integrity guard,
-- while the student has an open pose, probe or ledger hash) reads the items
-- of its hashes through check_item_service.items_by_hash, filtered on
-- `question_hash IN (...)` across every course; item_rows_for reads by hash
-- the same way. No index had question_hash as its leading column: the UNIQUE
-- (course_id, concept_key, question_hash) leads with course_id, the concept
-- index with (course_id, concept_key, ...). So each of those reads was a
-- sequential scan of every course's bank of wide encrypted rows, growing
-- with the bank, on the request path.
--
-- Locks: CREATE INDEX holds SHARE on check_items for the build (reads go on,
-- writes wait); the table is the loop's own and small before launch. This
-- file runs in one transaction (db/migrate.py), so the lock_timeout below
-- makes a lock that does not come within 5s fail the file (rolled back,
-- nothing recorded; run it again) instead of queueing every drafting write
-- behind a long reader. Idempotent (IF NOT EXISTS); no data is touched.
--
-- Reverse (by hand): DROP INDEX IF EXISTS public.check_items_question_hash_idx;

SET LOCAL lock_timeout = '5s';

CREATE INDEX IF NOT EXISTS check_items_question_hash_idx
    ON public.check_items (question_hash);
