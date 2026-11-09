-- db_scope_divergences(): the admin db-scope report's GROUP BY in SQL (#115
-- follow-up, wave-2 release doc §11 / #834).
--
-- `GET /api/admin/analytics/db-scope` grouped the db_user_scope events
-- (db.rls_shadow_divergence / db.unscoped_query / db.rls_denied) in Python
-- over a capped scan (at most 20,000 events, newest first, window <= 168 h),
-- because PostgREST has no GROUP BY. This function does the grouping:
--
-- public.db_scope_divergences(p_from, p_to, p_events)
--     -> TABLE (k jsonb, n bigint, users text[], first_seen timestamptz,
--               last_seen timestamptz, request_ids jsonb)
--   One row per distinct RAW grouping key among the matching events in
--   [p_from, p_to]. `k` is a JSON array of the payload values the app's key
--   is built from, exactly as stored (so the app applies the same
--   normalisation it applies to scanned rows, db/scope_report.py::key_of):
--     [event_type, kind, mode, method, route, table, op,
--      status (or, for rows without a `status` key, the legacy `error`), code,
--      service_count, scoped_count]
--   The two counts are only filled when `kind` is absent/empty (pre-report
--   rows whose kind the app derives from them); otherwise NULL, so they do not
--   split a group. `n` = events, `users` = the distinct non-empty user ids,
--   `request_ids` = up to 3 {id, at} (the most recent distinct request ids,
--   newest first). STABLE, read-only, SECURITY INVOKER, search_path pinned to
--   ''; EXECUTE for service_role only (events is service-only, RLS bucket E).
--   Served by idx_events_type_created (event_type, created_at DESC).
--
-- Inert until used: routes/admin_analytics.py calls it and falls back to the
-- capped scan when the function is missing, so code and migration can land in
-- either order. Idempotent (CREATE OR REPLACE + guarded grants), additive.
--
-- Reverse (by hand, as the migration role; the route falls back on its own):
--   DROP FUNCTION IF EXISTS public.db_scope_divergences(timestamptz, timestamptz, text[]);

CREATE OR REPLACE FUNCTION public.db_scope_divergences(
    p_from   TIMESTAMPTZ,
    p_to     TIMESTAMPTZ,
    p_events TEXT[]
)
RETURNS TABLE (
    k           JSONB,
    n           BIGINT,
    users       TEXT[],
    first_seen  TIMESTAMPTZ,
    last_seen   TIMESTAMPTZ,
    request_ids JSONB
)
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = ''
AS $$
    WITH ev AS (
        SELECT e.created_at, e.user_id, e.request_id,
               pg_catalog.jsonb_build_array(
                   e.event_type,
                   e.payload -> 'kind',
                   e.payload -> 'mode',
                   e.payload -> 'method',
                   e.payload -> 'route',
                   e.payload -> 'table',
                   e.payload -> 'op',
                   CASE WHEN e.payload ? 'status' THEN e.payload -> 'status'
                        ELSE e.payload -> 'error' END,
                   e.payload -> 'code',
                   CASE WHEN e.payload -> 'kind' IS NULL
                          OR e.payload -> 'kind' IN ('null', '""', 'false', '0', '[]', '{}')
                        THEN e.payload -> 'service_count' END,
                   CASE WHEN e.payload -> 'kind' IS NULL
                          OR e.payload -> 'kind' IN ('null', '""', 'false', '0', '[]', '{}')
                        THEN e.payload -> 'scoped_count' END
               ) AS k
          FROM public.events e
         WHERE e.event_type = ANY (p_events)
           AND e.created_at >= p_from
           AND e.created_at <= p_to
    ),
    grp AS (
        SELECT ev.k,
               count(*)::BIGINT AS n,
               array_agg(DISTINCT ev.user_id)
                   FILTER (WHERE ev.user_id IS NOT NULL AND ev.user_id <> '') AS users,
               min(ev.created_at) AS first_seen,
               max(ev.created_at) AS last_seen
          FROM ev
         GROUP BY ev.k
    ),
    rid AS (
        SELECT ev.k, ev.request_id, max(ev.created_at) AS at,
               row_number() OVER (PARTITION BY ev.k
                                  ORDER BY max(ev.created_at) DESC, ev.request_id) AS rn
          FROM ev
         WHERE ev.request_id IS NOT NULL AND ev.request_id <> ''
         GROUP BY ev.k, ev.request_id
    )
    SELECT g.k, g.n, COALESCE(g.users, '{}'::TEXT[]), g.first_seen, g.last_seen,
           COALESCE((SELECT jsonb_agg(jsonb_build_object('id', r.request_id, 'at', r.at)
                                      ORDER BY r.rn)
                       FROM rid r
                      WHERE r.k = g.k AND r.rn <= 3), '[]'::JSONB)
      FROM grp g
     ORDER BY g.n DESC;
$$;

COMMENT ON FUNCTION public.db_scope_divergences(TIMESTAMPTZ, TIMESTAMPTZ, TEXT[]) IS
    'db_user_scope events grouped by their raw report key, for /api/admin/analytics/db-scope (#115).';

DO $$
DECLARE
    fn CONSTANT TEXT := 'public.db_scope_divergences(timestamptz, timestamptz, text[])';
    r  TEXT;
BEGIN
    EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', fn);
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION %s FROM %I', fn, r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role', fn);
    END IF;
END $$;
