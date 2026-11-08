-- 20261108224511_learning_varied_practice_validate.sql
-- Learning loop spec §13 A141: validate the closed multi-concept shape CHECK
-- that 20261108205812_learning_varied_practice_review.sql adds NOT VALID.
--
-- VALIDATE CONSTRAINT scans check_items under SHARE UPDATE EXCLUSIVE, which
-- blocks no read or write (only other schema changes and VACUUM), in its own
-- transaction: the review migration's ACCESS EXCLUSIVE locks are released by
-- then. Every stored row passes the constraint (the code writes nothing
-- else); a row that did not would fail this file, and nothing would be
-- recorded. lock_timeout 5s: a lock that does not come within 5s fails the
-- file (rolled back; run it again).
--
-- Deploy order: right after 20261108205812, in the same run, before the code
-- (the rollout entry in docs/operations/learning-engineering-readiness.md).
-- Until it runs, new and updated rows are checked already.

SET LOCAL lock_timeout = '5s';

ALTER TABLE public.check_items VALIDATE CONSTRAINT check_items_multi_concept_shape;
