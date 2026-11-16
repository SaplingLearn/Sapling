-- Job queue upkeep (#116, docs/architecture-hardening-plan.md phase 2), its
-- two Canopy numbers, and the four Canopy numbers of the weekly LLM cost
-- signal (#119). Builds on 20261108095241_jobs_queue.sql and
-- 20261108213311_llm_budgets_and_cost_signal.sql. This is wave 2's ONE
-- canopy_metrics() redefinition.
--
-- What this adds
-- --------------
-- heartbeat_job(p_id, p_worker, p_attempt) -> boolean
--     A running job's worker pushes its lease forward: locked_at = now(). The
--     lease is measured from locked_at by every claimer (claim_jobs re-offers a
--     running row once locked_at + its lease has passed), so a handler that
--     outlives one lease no longer gets its job re-run by a second worker
--     while it is still working. Fenced exactly like complete_job/fail_job:
--     only the claim's own (locked_by, attempts) and only while `running`.
--     False means the claim is gone (re-claimed after the lease ran out, or
--     reaped `dead`): the worker stops heartbeating and the fenced
--     complete/fail decides nothing. No lease argument: the lease length is
--     the CLAIMER's (claim_jobs' p_lease_seconds), and resetting locked_at is
--     all a heartbeat has to do; a heartbeat arriving after the lease expired
--     but before anyone re-claimed is harmless (the worker is alive).
--
-- prune_jobs(p_older_than_days, p_limit) -> integer (rows deleted)
--     Deletes at most p_limit (capped at 10000) `succeeded` rows whose
--     updated_at (when they succeeded) is older than p_older_than_days
--     (floored at 1). Never touches queued/failed/running/dead rows: dead
--     letters stay until someone has looked at them. Batched (one LIMITed
--     DELETE per call, oldest first, SKIP LOCKED so two pruners never wait on
--     each other); services/jobs.py's `jobs.prune` handler calls it in a
--     bounded loop. Idempotent: a second call finds nothing older to delete.
--
-- Two partial indexes: succeeded rows by updated_at (the prune) and dead rows
-- by updated_at (the dead-letter list in routes/admin_jobs.py and the Canopy
-- count below).
--
-- canopy_metrics(): CREATE OR REPLACE of the CURRENT definition
-- (20261106055333_state_machines_audit.sql, the #760 block), copied verbatim
-- except for six added keys, one added CTE (llm_cost) and a jsonb_strip_nulls
-- around `totals` (every pre-existing totals key is a COUNT, never NULL, so
-- the strip only ever drops the new llm_* keys). The contract's key list and
-- source rules live in 20260921055024_canopy_metrics.sql's header
-- (immutable); these six extend it:
--   counts.jobs_dead_lettered  {24h,7d,30d}. `jobs` rows in status `dead`,
--                              windowed on updated_at (when they died). The
--                              plan's "jobs failed after all retries" measure
--                              (its target: under 1%). Dead rows are never
--                              pruned, so the 30-day window is complete.
--                              Always present: the table exists from
--                              20261108095241 on and an idle queue is a
--                              MEASURED zero.
--   totals.jobs_queue_depth    point in time. `jobs` rows not finished:
--                              queued + failed (waiting out a retry backoff,
--                              still owed a run) + running.
-- Both read only `jobs`, which holds ids and statuses, never student content.
--
-- #119, all four read from ONE call of
-- public.llm_cost_per_active_user_weekly() (20261108213311) so Canopy and
-- GET /api/admin/analytics/llm/cost-per-active-user never disagree. Active
-- users there are distinct non-empty events.user_id with category <> 'system'
-- (admin analytics' definition), so they can differ slightly from canopy's
-- own active_users. Cost is priced llm_usage rows (cost_usd > 0). JSON
-- integers (the route accepts only integers in `totals`), each OMITTED when
-- the database cannot answer it honestly (contract rule) — never a fake 0:
--   totals.llm_microusd_per_user_7d       priced LLM cost per active user over
--                                         the last 7 days, micro-USD (half-up).
--                                         Omitted when the last 7 days have no
--                                         priced rows or no active users.
--   totals.llm_microusd_per_user_4w_base  mean per-user cost of the four 7-day
--                                         windows before that (those with an
--                                         answer), micro-USD. Omitted when none
--                                         of the four has one.
--   totals.llm_cost_jump_ratio_pct        floor(ratio * 100), ratio being the
--                                         function's published 4-dp ratio, so
--                                         >= 200 exactly when llm_cost_jump is
--                                         1 (200 = doubled). Omitted when the
--                                         ratio is unknown, or above 1e9 % (a
--                                         near-zero baseline), which keeps it
--                                         far inside the route's 1e12 cap.
--   totals.llm_cost_jump                  1 when that same ratio >= 2.0, else
--                                         0. Omitted when the ratio is unknown;
--                                         still 1 when the ratio_pct itself is
--                                         omitted for size.
-- Both micro-USD keys are likewise omitted past the route's 1e12 cap ($1M
-- per user per week: never real, but never a 503 either).
-- Cost: the function re-reads 35 days of llm_usage and events once per
-- hourly poll instead of reusing this function's 30-day `llm` / `active`
-- passes (different window, different active-user rule); both scans are
-- index range scans on created_at, so the extra pass is cheap.
--
-- The route (routes/internal_metrics.py) only validates and forwards: counts
-- stay within its 48-key cap, totals within 24 (13 after this file).
--
-- All three functions are service_role only (REVOKE from PUBLIC/anon/
-- authenticated, restated below as 20261108095241 does).
--
-- Idempotent (CREATE OR REPLACE / IF NOT EXISTS), additive, rewrites no data.
-- Nothing calls heartbeat_job/prune_jobs until a worker built from this
-- branch runs (`python -m worker`, which only exists once the `jobs_queue`
-- flag has a Railway worker service behind it). The new canopy keys appear on
-- the next hourly poll; an older image forwards them unchanged.
--
-- Reverse (by hand, as the migration role):
--   DROP FUNCTION IF EXISTS public.prune_jobs(integer, integer);
--   DROP FUNCTION IF EXISTS public.heartbeat_job(uuid, text, integer);
--   DROP INDEX IF EXISTS public.jobs_succeeded_updated_idx;
--   DROP INDEX IF EXISTS public.jobs_dead_updated_idx;
-- and restore the previous canopy_metrics() by re-running the "#760
-- canopy_metrics" block of 20261106055333_state_machines_audit.sql (from its
-- CREATE OR REPLACE FUNCTION canopy_metrics() through its NOTIFY). That
-- restore removes all six keys above (jobs_* and llm_*) and is what must run
-- BEFORE 20261108213311 is reversed (it drops the cost function this
-- canopy_metrics() calls). Drop the functions only with the worker stopped
-- (or on an image without the heartbeat): a running worker's heartbeat would
-- log a warning per call.

-- ── indexes ─────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS jobs_succeeded_updated_idx
    ON public.jobs (updated_at)
    WHERE status = 'succeeded';

CREATE INDEX IF NOT EXISTS jobs_dead_updated_idx
    ON public.jobs (updated_at)
    WHERE status = 'dead';

-- ── heartbeat_job ───────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.heartbeat_job(
    p_id      UUID,
    p_worker  TEXT,
    p_attempt INTEGER
)
RETURNS BOOLEAN
LANGUAGE sql
VOLATILE
SET search_path = ''
AS $$
    WITH beat AS (
        UPDATE public.jobs j
           SET locked_at = now()
         WHERE j.id = p_id
           AND j.locked_by = p_worker
           AND j.attempts = p_attempt
           AND j.status = 'running'
        RETURNING 1
    )
    SELECT EXISTS (SELECT 1 FROM beat);
$$;

-- ── prune_jobs ──────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.prune_jobs(
    p_older_than_days INTEGER,
    p_limit           INTEGER
)
RETURNS INTEGER
LANGUAGE sql
VOLATILE
SET search_path = ''
AS $$
    WITH doomed AS (
        SELECT d.id
          FROM public.jobs d
         WHERE d.status = 'succeeded'
           AND d.updated_at < now() - make_interval(
                   days => greatest(coalesce(p_older_than_days, 30), 1))
         ORDER BY d.updated_at
         LIMIT least(greatest(coalesce(p_limit, 1000), 0), 10000)
         FOR UPDATE SKIP LOCKED
    ),
    gone AS (
        DELETE FROM public.jobs j
         USING doomed
         WHERE j.id = doomed.id
           AND j.status = 'succeeded'
        RETURNING 1
    )
    SELECT count(*)::integer FROM gone;
$$;

DO $$
DECLARE
    fn TEXT;
    r  TEXT;
BEGIN
    FOREACH fn IN ARRAY ARRAY[
        'public.heartbeat_job(uuid, text, integer)',
        'public.prune_jobs(integer, integer)'
    ] LOOP
        EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', fn);
        FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                EXECUTE format('REVOKE ALL ON FUNCTION %s FROM %I', fn, r);
            END IF;
        END LOOP;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
            EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role', fn);
        END IF;
    END LOOP;
END $$;

-- ── canopy_metrics(): + jobs_*, + llm_cost per active user ──────────────────
--
-- Everything below up to the NOTIFY is 20261106055333's #760 definition
-- verbatim except the marked #116 and #119 additions.
CREATE OR REPLACE FUNCTION canopy_metrics()
RETURNS JSONB
LANGUAGE sql STABLE
SET search_path = public, pg_temp
AS $$
WITH
-- #119 (20261108213623): one read of the weekly LLM cost signal, as numerics.
llm_cost AS (
    SELECT (s->>'usd_per_active_user_7d')::numeric       AS cur,
           (s->>'baseline_usd_per_active_user')::numeric AS base,
           (s->>'ratio')::numeric                        AS ratio
    FROM (SELECT public.llm_cost_per_active_user_weekly() AS s) f
),
-- v1's definition, unchanged: distinct users with at least one attributed
-- `events` row. NULL is the anonymous/system actor (0035); '' mirrors
-- admin_analytics' truthiness test, so the two dashboards agree.
active AS (
    SELECT
        COUNT(DISTINCT e.user_id) FILTER (WHERE e.created_at >= now() - interval '24 hours') AS d1,
        COUNT(DISTINCT e.user_id) FILTER (WHERE e.created_at >= now() - interval '7 days')   AS d7,
        COUNT(DISTINCT e.user_id)                                                            AS d30
    FROM events e
    WHERE e.user_id IS NOT NULL
      AND e.user_id <> ''
      AND e.created_at >= now() - interval '30 days'
),
event_keys (event_type, key) AS (
    VALUES
        ('session.started',              'tutor_sessions'),
        ('chat.message_sent',            'chat_messages'),
        ('document.upload',              'documents_uploaded'),
        ('auth.login',                   'logins'),
        ('error.5xx',                    'errors_5xx'),
        ('error.4xx',                    'errors_4xx'),
        ('quiz.generation_failed',       'quiz_generation_failed'),
        ('quiz.context_write_failed',    'quiz_context_write_failed'),
        ('rag.retrieval_failed',         'rag_retrieval_failed'),
        ('rag.chunks_dropped',           'rag_chunks_dropped'),
        ('rag.visibility_resync_failed', 'rag_visibility_resync_failed')
),
-- LEFT JOIN: a type nothing emitted this month is a MEASURED zero and keeps its
-- key — but only while `events` is being written at all (the WHERE).
event_counts AS (
    SELECT
        k.key,
        COUNT(e.created_at) FILTER (WHERE e.created_at >= now() - interval '24 hours') AS d1,
        COUNT(e.created_at) FILTER (WHERE e.created_at >= now() - interval '7 days')   AS d7,
        COUNT(e.created_at)                                                            AS d30
    FROM event_keys k
    LEFT JOIN events e
           ON e.event_type = k.event_type
          AND e.created_at >= now() - interval '30 days'
    WHERE EXISTS (SELECT 1 FROM events x WHERE x.created_at >= now() - interval '30 days')
    GROUP BY k.key
),
llm AS (
    SELECT
        COUNT(*)                                                             AS calls_d30,
        COUNT(*) FILTER (WHERE u.created_at >= now() - interval '7 days')    AS calls_d7,
        COUNT(*) FILTER (WHERE u.created_at >= now() - interval '24 hours')  AS calls_d1,
        COUNT(u.cost_usd)                                                    AS priced_d30,
        COALESCE(SUM(u.total_tokens) FILTER (WHERE u.total_tokens > 0), 0)   AS tokens_d30,
        COALESCE(SUM(u.total_tokens) FILTER (WHERE u.total_tokens > 0
                 AND u.created_at >= now() - interval '7 days'), 0)          AS tokens_d7,
        COALESCE(SUM(u.total_tokens) FILTER (WHERE u.total_tokens > 0
                 AND u.created_at >= now() - interval '24 hours'), 0)        AS tokens_d1,
        COALESCE(SUM(u.cost_usd) FILTER (WHERE u.cost_usd > 0), 0)           AS usd_d30,
        COALESCE(SUM(u.cost_usd) FILTER (WHERE u.cost_usd > 0
                 AND u.created_at >= now() - interval '7 days'), 0)          AS usd_d7,
        COALESCE(SUM(u.cost_usd) FILTER (WHERE u.cost_usd > 0
                 AND u.created_at >= now() - interval '24 hours'), 0)        AS usd_d1
    FROM llm_usage u
    WHERE u.created_at >= now() - interval '30 days'
),
counts (key, d1, d7, d30) AS (
    SELECT key, d1, d7, d30 FROM event_counts

    UNION ALL
    SELECT 'signups',
           COUNT(*) FILTER (WHERE created_at >= now() - interval '24 hours'),
           COUNT(*) FILTER (WHERE created_at >= now() - interval '7 days'),
           COUNT(*)
    FROM users
    WHERE created_at >= now() - interval '30 days' AND google_id IS NOT NULL

    UNION ALL
    SELECT 'approvals',
           COUNT(*) FILTER (WHERE created_at >= now() - interval '24 hours'),
           COUNT(*) FILTER (WHERE created_at >= now() - interval '7 days'),
           COUNT(*)
    FROM admin_audit_log
    WHERE created_at >= now() - interval '30 days' AND action = 'user.approve'

    UNION ALL
    SELECT 'quizzes_started',
           COUNT(*) FILTER (WHERE created_at >= now() - interval '24 hours'),
           COUNT(*) FILTER (WHERE created_at >= now() - interval '7 days'),
           COUNT(*)
    FROM quiz_attempts
    WHERE created_at >= now() - interval '30 days'

    UNION ALL
    SELECT 'quizzes_completed',
           COUNT(*) FILTER (WHERE completed_at >= now() - interval '24 hours'),
           COUNT(*) FILTER (WHERE completed_at >= now() - interval '7 days'),
           COUNT(*)
    FROM quiz_attempts
    WHERE completed_at >= now() - interval '30 days' AND score IS NOT NULL

    UNION ALL
    SELECT 'documents_processed',
           COUNT(*) FILTER (WHERE processed_at >= now() - interval '24 hours'),
           COUNT(*) FILTER (WHERE processed_at >= now() - interval '7 days'),
           COUNT(*)
    FROM documents
    WHERE processed_at >= now() - interval '30 days'

    UNION ALL
    SELECT 'notes_created',
           COUNT(*) FILTER (WHERE created_at >= now() - interval '24 hours'),
           COUNT(*) FILTER (WHERE created_at >= now() - interval '7 days'),
           COUNT(*)
    FROM notes
    WHERE created_at >= now() - interval '30 days'

    UNION ALL
    SELECT 'flashcards_created',
           COUNT(*) FILTER (WHERE created_at >= now() - interval '24 hours'),
           COUNT(*) FILTER (WHERE created_at >= now() - interval '7 days'),
           COUNT(*)
    FROM flashcards
    WHERE created_at >= now() - interval '30 days'

    UNION ALL
    SELECT 'xp_events',
           COUNT(*) FILTER (WHERE created_at >= now() - interval '24 hours'),
           COUNT(*) FILTER (WHERE created_at >= now() - interval '7 days'),
           COUNT(*)
    FROM xp_events
    WHERE created_at >= now() - interval '30 days'

    UNION ALL
    SELECT 'achievements_earned',
           COUNT(*) FILTER (WHERE earned_at >= now() - interval '24 hours'),
           COUNT(*) FILTER (WHERE earned_at >= now() - interval '7 days'),
           COUNT(*)
    FROM user_achievements
    WHERE earned_at >= now() - interval '30 days'

    UNION ALL
    SELECT 'room_messages',
           COUNT(*) FILTER (WHERE created_at >= now() - interval '24 hours'),
           COUNT(*) FILTER (WHERE created_at >= now() - interval '7 days'),
           COUNT(*)
    FROM room_messages
    WHERE created_at >= now() - interval '30 days'

    UNION ALL
    SELECT 'feedback',
           COUNT(*) FILTER (WHERE created_at >= now() - interval '24 hours'),
           COUNT(*) FILTER (WHERE created_at >= now() - interval '7 days'),
           COUNT(*)
    FROM feedback
    WHERE created_at >= now() - interval '30 days'

    UNION ALL
    SELECT 'issue_reports',
           COUNT(*) FILTER (WHERE created_at >= now() - interval '24 hours'),
           COUNT(*) FILTER (WHERE created_at >= now() - interval '7 days'),
           COUNT(*)
    FROM issue_reports
    WHERE created_at >= now() - interval '30 days'

    UNION ALL
    SELECT 'llm_calls', calls_d1, calls_d7, calls_d30
    FROM llm WHERE calls_d30 > 0

    UNION ALL
    SELECT 'llm_tokens', tokens_d1, tokens_d7, tokens_d30
    FROM llm WHERE calls_d30 > 0

    -- ROUND(numeric) rounds half away from zero, which for these non-negative
    -- sums is the contract's half-up. It is monotone, so the cents nest
    -- because the dollars do.
    UNION ALL
    SELECT 'llm_cost_cents',
           ROUND(usd_d1 * 100)::BIGINT, ROUND(usd_d7 * 100)::BIGINT, ROUND(usd_d30 * 100)::BIGINT
    FROM llm WHERE priced_d30 > 0

    -- #116 (20261108213623): jobs that ran out of retries, or were declared
    -- unrunnable, by when they died (`updated_at` of a `dead` row; only the
    -- late finish of the attempt that died touches it again, through the
    -- fenced complete_job/fail_job). A measured zero while the queue is idle:
    -- the table always exists.
    UNION ALL
    SELECT 'jobs_dead_lettered',
           COUNT(*) FILTER (WHERE updated_at >= now() - interval '24 hours'),
           COUNT(*) FILTER (WHERE updated_at >= now() - interval '7 days'),
           COUNT(*)
    FROM public.jobs
    WHERE status = 'dead' AND updated_at >= now() - interval '30 days'
)
SELECT jsonb_build_object(
    'active_users',
        (SELECT jsonb_build_object('24h', d1, '7d', d7, '30d', d30) FROM active),
    'counts',
        (SELECT COALESCE(
                    jsonb_object_agg(key, jsonb_build_object('24h', d1, '7d', d7, '30d', d30)),
                    '{}'::jsonb)
         FROM counts),
    -- jsonb_strip_nulls: only the #119 keys below can be NULL (no honest
    -- answer); stripping turns that into an omitted key, never a fake 0.
    'totals', jsonb_strip_nulls(jsonb_build_object(
        'users',               (SELECT COUNT(*) FROM users
                                WHERE google_id IS NOT NULL AND deleted_at IS NULL),
        'users_pending',       (SELECT COUNT(*) FROM users
                                WHERE google_id IS NOT NULL AND deleted_at IS NULL
                                  AND NOT is_approved),
        'documents',           (SELECT COUNT(*) FROM documents  WHERE deleted_at IS NULL),
        'notes',               (SELECT COUNT(*) FROM notes      WHERE deleted_at IS NULL),
        'flashcards',          (SELECT COUNT(*) FROM flashcards),
        'rooms',               (SELECT COUNT(*) FROM rooms),
        'rag_chunks',          (SELECT COUNT(*) FROM course_chunks),
        'rag_document_chunks', (SELECT COUNT(*) FROM course_chunks
                                WHERE category IS DISTINCT FROM 'catalog'),
        -- #116 (20261108213623): work not yet finished — waiting, waiting out
        -- a retry backoff, or in a worker's hands.
        'jobs_queue_depth',    (SELECT COUNT(*) FROM public.jobs
                                WHERE status IN ('queued', 'failed', 'running')),
        -- #119 (20261108213623): weekly LLM cost per active user. NULL (no
        -- answer, or past the route's 1e12 cap) is stripped above.
        'llm_microusd_per_user_7d',
            (SELECT CASE WHEN cur * 1000000 <= 1000000000000
                         THEN ROUND(cur * 1000000)::BIGINT END FROM llm_cost),
        'llm_microusd_per_user_4w_base',
            (SELECT CASE WHEN base * 1000000 <= 1000000000000
                         THEN ROUND(base * 1000000)::BIGINT END FROM llm_cost),
        -- FLOOR, not ROUND: pct >= 200 exactly when ratio >= 2.0 (the jump).
        'llm_cost_jump_ratio_pct',
            (SELECT CASE WHEN ratio * 100 <= 1000000000
                         THEN FLOOR(ratio * 100)::BIGINT END FROM llm_cost),
        'llm_cost_jump',
            (SELECT CASE WHEN ratio >= 2.0 THEN 1 WHEN ratio < 2.0 THEN 0 END FROM llm_cost)
    ))
);
$$;

REVOKE ALL ON FUNCTION canopy_metrics() FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION canopy_metrics() FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION canopy_metrics() TO service_role;
    END IF;
END $$;

NOTIFY pgrst, 'reload schema';
