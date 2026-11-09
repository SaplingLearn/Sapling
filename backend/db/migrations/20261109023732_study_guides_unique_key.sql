-- study_guides: one guide per (user_id, offering_id, exam_id), enforced by the
-- database — but ONLY where the table is already clean (#828, wave-2 release
-- doc §11). NON-DESTRUCTIVE: this file never deletes or changes a row.
--
-- Until now duplicate guides were prevented in code only (the per-guide
-- single-flight in routes/study_guide.py, a per-process lock that #117's
-- `stateless_locks` lease now extends across replicas). A cross-replica race
-- before that could leave two rows for one key; reads take the newest.
--
-- What this does
-- --------------
-- In ONE guarded DO block (the runner wraps each file in a transaction, so no
-- CREATE INDEX CONCURRENTLY; the table is small):
--   1. If the index already exists: nothing.
--   2. LOCK TABLE study_guides IN SHARE MODE (what CREATE INDEX takes anyway),
--      so no duplicate can be inserted between the check and the build.
--   3. If any (user_id, offering_id, exam_id) has more than one row: RAISE
--      NOTICE with the number of duplicated keys and SKIP — the index is not
--      created and the migration still succeeds.
--   4. Otherwise CREATE UNIQUE INDEX study_guides_user_offering_exam_key. The
--      three columns are NOT NULL since 0025; on an environment where any of
--      them is nullable the index is built NULLS NOT DISTINCT (PG15+), so a
--      NULL offering cannot duplicate either.
--
-- FOLLOW-UP (needs a human decision): where step 3 skipped, the duplicates have
-- to be resolved before the constraint can exist — which copy of a guide to
-- keep (newest generated_at is what reads already show) is a product call, and
-- deleting a student's row is out of scope for an automatic migration. Find
-- them with:
--   SELECT user_id, offering_id, exam_id, count(*) FROM public.study_guides
--    GROUP BY 1, 2, 3 HAVING count(*) > 1;
-- then re-run this block by hand (it is idempotent), or add a new migration.
--
-- Deploy order: the code shipped with this file (routes/study_guide.py)
-- treats a unique violation on insert as "this key already has a row" and
-- replaces that row in place (regenerate) — it works with and without the
-- index. Code from BEFORE it inserts a second row on regenerate and would get
-- a 409 -> 500 from the index, so on an environment that applies migrations
-- before deploying, regenerate fails for the minutes between the two. Apply
-- with or after the deploy where that matters.
--
-- Reverse (by hand, as the migration role):
--   DROP INDEX IF EXISTS public.study_guides_user_offering_exam_key;

DO $$
DECLARE
    v_dupes    BIGINT;
    v_nullable BOOLEAN;
BEGIN
    IF to_regclass('public.study_guides_user_offering_exam_key') IS NOT NULL THEN
        RETURN;
    END IF;

    LOCK TABLE public.study_guides IN SHARE MODE;

    SELECT count(*) INTO v_dupes
      FROM (SELECT 1
              FROM public.study_guides
             GROUP BY user_id, offering_id, exam_id
            HAVING count(*) > 1) d;

    IF v_dupes > 0 THEN
        RAISE NOTICE 'study_guides: % (user_id, offering_id, exam_id) key(s) have duplicate rows; '
                     'NOT creating study_guides_user_offering_exam_key (no rows changed). '
                     'Resolve the duplicates, then re-run this migration''s DO block.', v_dupes;
        RETURN;
    END IF;

    SELECT bool_or(is_nullable = 'YES') INTO v_nullable
      FROM information_schema.columns
     WHERE table_schema = 'public' AND table_name = 'study_guides'
       AND column_name IN ('user_id', 'offering_id', 'exam_id');

    IF v_nullable THEN
        EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS study_guides_user_offering_exam_key '
                'ON public.study_guides (user_id, offering_id, exam_id) NULLS NOT DISTINCT';
    ELSE
        EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS study_guides_user_offering_exam_key '
                'ON public.study_guides (user_id, offering_id, exam_id)';
    END IF;
END $$;
