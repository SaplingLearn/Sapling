-- canopy_active_users(): distinct active users over the trailing 24 hours /
-- 7 days / 30 days, for GET /api/internal/metrics (routes/internal_metrics.py).
--
-- Canopy — the team's dashboard — polls that route once an hour per environment
-- and stores the three numbers append-only, first-write-wins. A wrong number is
-- therefore permanent, which is what decides the shape of this function.
--
-- WHY A FUNCTION AT ALL. PostgREST has no COUNT(DISTINCT). The existing answer
-- (routes/admin_analytics.py) pages `events` into Python and de-duplicates
-- there, stopping at a 100,000-row cap with `truncated: true`. For an admin
-- screen that flag is enough. Here a truncated scan would UNDERCOUNT and the
-- undercount would be kept forever, and the paging itself (one round trip per
-- 1,000 rows, against an 8-second poll timeout) gets slower every month
-- `events` grows. One aggregate in Postgres cannot truncate and is one round
-- trip. Same seam the RAG retrieval already uses: a SQL function reached via
-- db.connection.rpc (see 0039's match_course_chunks).
--
-- WHAT "ACTIVE" MEANS. At least one `events` row attributed to the user inside
-- the window — the same source and the same "has a user_id" rule as
-- admin_analytics' `distinct_active_users`, so the two dashboards agree.
-- `user_id <> ''` mirrors that code's truthiness test (`if r.get("user_id")`);
-- NULL is the anonymous/system actor (0035) and is never a user.
--
-- WHY THE WINDOWS CANNOT DISAGREE. One statement, one 30-day row set, and
-- now() is the transaction timestamp — identical every time it appears. Each
-- narrower window is a FILTER over the wider one's rows, so d1 <= d7 <= d30 by
-- construction. Canopy refuses all three numbers if that ever fails.
--
-- COUNT returns BIGINT, which PostgREST serialises as a JSON number (not a
-- string) — the route checks for exactly that.
--
-- CREATE OR REPLACE rather than IF NOT EXISTS: functions have no IF NOT EXISTS
-- form, and replacing with the identical body is the no-op we want on re-run.
-- The signature takes no arguments, so a later change to the BODY can never
-- leave a stale overload behind (the trap 20260920072705 had to work around).
-- Changing the RETURN columns is different — that needs DROP FUNCTION first.
CREATE OR REPLACE FUNCTION canopy_active_users()
RETURNS TABLE (
    d1  BIGINT,
    d7  BIGINT,
    d30 BIGINT
)
LANGUAGE sql STABLE
AS $$
    SELECT
        COUNT(DISTINCT e.user_id) FILTER (WHERE e.created_at >= now() - interval '24 hours'),
        COUNT(DISTINCT e.user_id) FILTER (WHERE e.created_at >= now() - interval '7 days'),
        COUNT(DISTINCT e.user_id)
    FROM events e
    WHERE e.user_id IS NOT NULL
      AND e.user_id <> ''
      AND e.created_at >= now() - interval '30 days';
$$;

-- Backend-only. Postgres grants EXECUTE on a new function to PUBLIC, and
-- Supabase's default privileges grant it to `anon` and `authenticated` as well
-- — and PostgREST exposes every public-schema function at /rest/v1/rpc/<name>.
-- The frontend ships the anon key, so without this anyone holding it could read
-- the counts straight from Supabase, bypassing the route's bearer token.
-- The backend connects as `service_role`.
--
-- The role-specific statements are guarded because those three roles are
-- Supabase's: a plain Postgres (a scratch database, a future CI lane) has none
-- of them, and an unguarded REVOKE/GRANT naming a missing role aborts the whole
-- migration.
REVOKE ALL ON FUNCTION canopy_active_users() FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION canopy_active_users() FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION canopy_active_users() TO service_role;
    END IF;
END $$;

-- 0035 indexed events by (user_id, created_at), (event_type, created_at) and
-- (category, created_at): nothing LEADS with created_at, so a pure time-window
-- read — this function, and every admin_analytics range scan — cannot use an
-- index to skip old rows, and `events` has no retention. With this one the
-- function touches only the last 30 days of rows however large the table gets
-- (checked on a scratch Postgres: 200k rows over 400 days, ~15k in the window,
-- bitmap scan on this index, ~25 ms). Plain CREATE INDEX (not CONCURRENTLY, which cannot run inside the
-- transaction db/migrate.py wraps each file in). The build blocks writes to
-- `events` while it runs; the only writer is events_service's background drain
-- thread, off the request path, so a student never waits on it.
CREATE INDEX IF NOT EXISTS idx_events_created_user ON events (created_at, user_id);

-- PostgREST resolves /rpc/<name> from its schema cache, and a function it has
-- not cached is a 404 ("not in the schema cache") — which the route would serve
-- as a 503 until something else reloaded it. Hosted Supabase reloads on DDL by
-- itself; the local stack does not reliably (docs/local-supabase.md). Asking
-- is free: NOTIFY is delivered at COMMIT, and with no listener it is a no-op.
NOTIFY pgrst, 'reload schema';
