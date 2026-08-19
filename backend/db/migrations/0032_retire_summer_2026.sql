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
-- Replay-safe: after the first run there is no summer-2026 term and no offering
-- pointing at it, so statements 1 and 3 match nothing. Statement 2 does still
-- match (fall-2026 persists) but rewrites start_date to the value it already
-- holds, so it is idempotent in effect if not in row count.
--
-- WHY THE GUARD BELOW EXISTS. Repointing is not unconditionally safe:
-- course_offerings_unique is UNIQUE (course_id, term_id, section), so if a
-- course already has an offering in BOTH summer-2026 and fall-2026 with the
-- same section, moving the summer row onto fall-2026 lands on an occupied key
-- and raises a duplicate-key error. That is not an exotic shape —
-- resolve_offering(create=True) never sets section, so every app-created
-- offering shares the identical default, and a course active across both terms
-- produces exactly this pair.
--
-- Since db/migrate.py runs the whole file plus its ledger INSERT in one
-- transaction with no per-file recovery, that error would roll this migration
-- back and stop everything queued behind it. Choosing which of the two
-- offerings survives is a data call (enrollments hang off one id or the other),
-- so refuse loudly and name the collisions rather than guess.

DO $$
DECLARE
    n      int;
    sample text;
BEGIN
    SELECT count(*), left(coalesce(string_agg(g, '; '), ''), 500)
      INTO n, sample
      FROM (
        SELECT format('course_id=%L section=%L', s.course_id, s.section) AS g
          FROM course_offerings s
          JOIN course_offerings f
            ON f.course_id = s.course_id
           AND f.term_id   = 'fall-2026'
           AND f.section IS NOT DISTINCT FROM s.section
         WHERE s.term_id = 'summer-2026'
      ) d;

    IF n > 0 THEN
        RAISE EXCEPTION
            'cannot retire summer-2026: % offering(s) would collide with an '
            'existing fall-2026 offering on course_offerings_unique '
            '(course_id, term_id, section). Merge them first — repoint '
            'enrollments/documents/notes onto the surviving offering id, delete '
            'the redundant row, then re-run. Collisions: %',
            n, sample;
    END IF;
END $$;

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
