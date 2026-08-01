-- 0033: course_offerings.section becomes NOT NULL DEFAULT ''.
--
-- RECOVERED, NOT NEW — transcribed from a migration applied to staging
-- out-of-band and recorded under exactly this basename while never existing in
-- this repo. Restored so the ledger and the repo agree. Same rationale as
-- 0019_newsletter_approved_at.sql; the short version is that the ledger keys on
-- basename, so only a file with this exact name clears the orphan.
--
-- WHAT IT DOES, AND WHY IT IS THE RIGHT SHAPE
--
-- 0020 added `section` as a plain nullable TEXT, and 0020's
-- `course_offerings_unique` is UNIQUE (course_id, term_id, section). Plain
-- UNIQUE treats NULLs as distinct, so two rows for the same (course_id,
-- term_id) with section IS NULL both survive. 0036 patches exactly that hole
-- with a partial unique index over the NULL case.
--
-- But NULL was never the only way to say "no section". Every seeder in this
-- repo writes the empty string instead:
--     db/seed_staging.py       "section": ""
--     db/seed_local_rich.py    "section": ""
--     db/e2e_staging_http.py   "section": ""
-- while services/academics.py::resolve_offering(create=True) omits the key
-- entirely and therefore wrote NULL. So a seeded offering and a
-- resolve_offering'd offering for the same course+term were two DIFFERENT
-- values, and 0036's partial index — scoped to `WHERE section IS NULL` — could
-- not see the pair. The duplicate-offering bug 0036 exists to prevent walks in
-- through the '' door.
--
-- Collapsing NULL into '' removes the second door. With section NOT NULL there
-- is exactly one representation of "no section", and the pre-existing
-- `course_offerings_unique` covers it directly — one constraint instead of two,
-- and no NULL semantics to reason about. resolve_offering needs no change: it
-- still omits the key, the DEFAULT supplies '', and a lost create race still
-- surfaces as the 409 its existing handler already re-selects on.
--
-- 0036 is left in place and applies after this file, where it becomes a
-- permanent no-op (a partial index over a predicate no row can satisfy). It is
-- dropped by a later migration rather than edited, since it has already been
-- applied elsewhere and applied migrations are immutable.
--
-- Ordering note: '0033_offering...' sorts before '0033_realtime...' ('o' < 'r')
-- and before 0036. The two 0033s are independent; only the 0033-before-0036
-- relationship matters.
--
-- Idempotent: the UPDATE matches nothing on a second run, and SET DEFAULT /
-- SET NOT NULL are declarative rather than incremental.

UPDATE course_offerings SET section = '' WHERE section IS NULL;

ALTER TABLE course_offerings ALTER COLUMN section SET DEFAULT '';

ALTER TABLE course_offerings ALTER COLUMN section SET NOT NULL;
