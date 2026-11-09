-- jobs_overview(): the admin queue view as one exact aggregate (#116 follow-up,
-- wave-2 release doc §11 / #836).
--
-- `GET /api/admin/jobs` counted unfinished rows per type by scanning them
-- (capped at 10,000, with an `outstanding_truncated` flag). This function
-- answers the same question with one GROUP BY:
--
-- public.jobs_overview() -> TABLE (type text, status text, n bigint,
--                                  oldest_created_at timestamptz)
--   One row per (type, status) present in public.jobs: how many rows, and the
--   oldest row's created_at (for an unfinished status, how long the oldest
--   waiting job has been there). STABLE, read-only, SECURITY INVOKER with
--   search_path pinned to ''; EXECUTE for service_role only (jobs is
--   service-only, RLS bucket E).
--
-- Inert until used: routes/admin_jobs.py calls it and falls back to the old
-- capped scan when the function is missing, so code and migration can land in
-- either order. Idempotent (CREATE OR REPLACE + guarded grants), additive.
--
-- Reverse (by hand, as the migration role; the route falls back on its own):
--   DROP FUNCTION IF EXISTS public.jobs_overview();

CREATE OR REPLACE FUNCTION public.jobs_overview()
RETURNS TABLE (type TEXT, status TEXT, n BIGINT, oldest_created_at TIMESTAMPTZ)
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = ''
AS $$
    SELECT j.type, j.status, pg_catalog.count(*)::BIGINT, pg_catalog.min(j.created_at)
      FROM public.jobs j
     GROUP BY j.type, j.status
     ORDER BY j.type, j.status;
$$;

COMMENT ON FUNCTION public.jobs_overview() IS
    'Per (type, status) job counts and oldest created_at for the admin queue view (#116).';

DO $$
DECLARE
    r TEXT;
BEGIN
    REVOKE ALL ON FUNCTION public.jobs_overview() FROM PUBLIC;
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION public.jobs_overview() FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION public.jobs_overview() TO service_role;
    END IF;
END $$;
