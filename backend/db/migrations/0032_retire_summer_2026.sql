-- 0032: retire the Summer 2026 term; Fall 2026 absorbs its window.
--
-- RECOVERED, NOT NEW — transcribed from a migration applied to staging
-- out-of-band and recorded under exactly this basename while never existing in
-- this repo. Restored so the ledger and the repo agree. See
-- 0019_newsletter_approved_at.sql for why transcription (rather than deleting
-- the ledger row) is the reconciliation move.
--
-- THIS ONE CHANGES DATA AND BEHAVIOUR, not just schema. Read before replaying
-- it against an environment that matters.
--
-- 0019 seeds four terms with deliberately contiguous, non-overlapping ranges,
-- so that exactly one term contains any given date:
--     spring-2026  2026-01-05 .. 2026-05-17
--     summer-2026  2026-05-18 .. 2026-08-23
--     fall-2026    2026-08-24 .. 2027-01-03
-- Retiring summer-2026 would leave a 98-day hole in that cover, and
-- services/academics.py::current_term() resolves by date — a date in the hole
-- resolves to no term at all, and resolve_offering(create=True) then cannot
-- place a new enrollment. So fall-2026's start_date moves back to 2026-05-18 to
-- close the gap. The invariant 0019 documents is preserved, not abandoned.
--
-- CONSEQUENCE WORTH STATING PLAINLY: this changes what `current_term()` returns
-- for any date in the old summer window. A date such as 2026-07-31 resolved to
-- summer-2026 before this migration and resolves to fall-2026 after it. New
-- enrollments created in that window land in Fall rather than Summer.
--
-- Offerings are repointed before the term row is deleted, because
-- course_offerings.term_id is the only FK into terms (verified against the live
-- schema) and it is ON DELETE RESTRICT — deleting first would simply fail.
--
-- Idempotent: every statement is a WHERE-guarded write that matches nothing on
-- a second run.

-- 1. Move any Summer 2026 offering into Fall 2026 before the term disappears.
UPDATE course_offerings
   SET term_id = 'fall-2026'
 WHERE term_id = 'summer-2026';

-- 2. Close the date-cover gap the deletion would otherwise open.
UPDATE terms
   SET start_date = '2026-05-18'
 WHERE id = 'fall-2026';

-- 3. The term itself.
DELETE FROM terms WHERE id = 'summer-2026';
