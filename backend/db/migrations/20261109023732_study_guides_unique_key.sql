-- study_guides: one guide per (user_id, offering_id, exam_id), enforced by the
-- database — but ONLY where the table is already clean, and ONLY when an
-- operator says so (#828, wave-2 release doc §11). NON-DESTRUCTIVE: nothing
-- here deletes or changes a row.
--
-- Until now duplicate guides were prevented in code only (the per-guide
-- single-flight in routes/study_guide.py, a per-process lock that #117's
-- `stateless_locks` lease now extends across replicas). A cross-replica race
-- before that could leave two rows for one key; reads take the newest.
--
-- INERT: this file only defines a function and does NOT call it, so applying
-- it changes nothing for any running code.
--
-- public.ensure_study_guides_unique_key() -> text
--   1. If study_guides_user_offering_exam_key already exists: 'exists'.
--   2. LOCK TABLE study_guides IN SHARE MODE (what CREATE INDEX takes anyway),
--      so no duplicate can be inserted between the check and the build.
--   3. If any (user_id, offering_id, exam_id) has more than one row:
--      'skipped: N duplicate keys' (plus a NOTICE) — no index, no row changed.
--   4. Otherwise CREATE UNIQUE INDEX study_guides_user_offering_exam_key and
--      'created'. The three columns are NOT NULL since 0025; where any of them
--      is nullable the index is built NULLS NOT DISTINCT (PG15+).
--   Plain CREATE INDEX (not CONCURRENTLY: a function runs inside a
--   transaction); the table is small. SECURITY DEFINER because building an
--   index needs the table owner's rights, so it runs as the migration role;
--   search_path pinned to ''. EXECUTE revoked from PUBLIC, anon and
--   authenticated, granted to service_role only. The backend never calls it.
--
-- RELEASE STEP (by hand, once per environment): AFTER the deploy that carries
-- the tolerant routes/study_guide.py (a unique violation on insert replaces
-- the key's row in place), run as the migration role:
--   SELECT public.ensure_study_guides_unique_key();
-- Code from before that deploy inserts a second row on regenerate and would get
-- a 409 -> 500 from the index, which is why the index is not built here.
--
-- FOLLOW-UP (needs a human decision) when it answers 'skipped: ...': which copy
-- of a duplicated guide to keep (newest generated_at is what reads already
-- show) is a product call, and deleting a student's row is out of scope for an
-- automatic step. Find them with:
--   SELECT user_id, offering_id, exam_id, count(*) FROM public.study_guides
--    GROUP BY 1, 2, 3 HAVING count(*) > 1;
-- then call the function again (it is idempotent).
--
-- Reverse (by hand, as the migration role):
--   DROP INDEX IF EXISTS public.study_guides_user_offering_exam_key;  -- only if it was created
--   DROP FUNCTION IF EXISTS public.ensure_study_guides_unique_key();

CREATE OR REPLACE FUNCTION public.ensure_study_guides_unique_key()
RETURNS TEXT
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_dupes    BIGINT;
    v_nullable BOOLEAN;
BEGIN
    IF pg_catalog.to_regclass('public.study_guides_user_offering_exam_key') IS NOT NULL THEN
        RETURN 'exists';
    END IF;

    LOCK TABLE public.study_guides IN SHARE MODE;

    SELECT count(*) INTO v_dupes
      FROM (SELECT 1
              FROM public.study_guides
             GROUP BY user_id, offering_id, exam_id
            HAVING count(*) > 1) d;

    IF v_dupes > 0 THEN
        RAISE NOTICE 'study_guides: % (user_id, offering_id, exam_id) key(s) have duplicate rows; '
                     'NOT creating study_guides_user_offering_exam_key (no rows changed).', v_dupes;
        RETURN 'skipped: ' || v_dupes || ' duplicate keys';
    END IF;

    SELECT bool_or(c.is_nullable = 'YES') INTO v_nullable
      FROM information_schema.columns c
     WHERE c.table_schema = 'public' AND c.table_name = 'study_guides'
       AND c.column_name IN ('user_id', 'offering_id', 'exam_id');

    IF v_nullable THEN
        EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS study_guides_user_offering_exam_key '
                'ON public.study_guides (user_id, offering_id, exam_id) NULLS NOT DISTINCT';
    ELSE
        EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS study_guides_user_offering_exam_key '
                'ON public.study_guides (user_id, offering_id, exam_id)';
    END IF;
    RETURN 'created';
END;
$$;

COMMENT ON FUNCTION public.ensure_study_guides_unique_key() IS
    'Release step (#828): build the study_guides (user, offering, exam) unique index if the table has no duplicates. Run by hand after the tolerant study_guide.py deploys.';

DO $$
DECLARE
    r TEXT;
BEGIN
    REVOKE ALL ON FUNCTION public.ensure_study_guides_unique_key() FROM PUBLIC;
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION public.ensure_study_guides_unique_key() FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION public.ensure_study_guides_unique_key() TO service_role;
    END IF;
END $$;
