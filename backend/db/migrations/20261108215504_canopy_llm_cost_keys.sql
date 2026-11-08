-- Architecture hardening wave 2: Canopy keys for the weekly LLM cost signal
-- (plan Targets: "LLM cost per MAU, weekly, alert on a 2x jump"; #119).
--
-- canopy_metrics(): CREATE OR REPLACE of 20261108213623_jobs_upkeep.sql's
-- definition, verbatim except for the llm_cost CTE, the jsonb_strip_nulls
-- around `totals`, and four new `totals` keys read from
-- public.llm_cost_per_active_user_weekly()
-- (20261108213311_llm_budgets_and_cost_signal.sql):
--   totals.llm_microusd_per_user_7d       priced LLM cost per active user over
--                                         the last 7 days, in micro-USD
--   totals.llm_microusd_per_user_4w_base  mean of the four 7-day windows
--                                         before that, in micro-USD
--   totals.llm_cost_jump_ratio_pct        week 0 / baseline as a percentage
--                                         (200 = doubled)
--   totals.llm_cost_jump                  1 when that ratio is >= 2.0, else 0
-- All are JSON integers (routes/internal_metrics.py accepts only integers in
-- `totals`). Each is OMITTED when the database cannot answer it honestly (no
-- active users in a window), per the contract in
-- 20260921055024_canopy_metrics.sql. Active users here are distinct non-empty
-- events.user_id with category <> 'system' (admin analytics' definition), so
-- they can differ slightly from canopy's own active_users.
--
-- Idempotent (CREATE OR REPLACE plus the same grants). Not destructive.
--
-- Reverse (by hand, as the migration role): re-run the canopy_metrics() block
-- of 20261108213623_jobs_upkeep.sql (its CREATE OR REPLACE FUNCTION through
-- its NOTIFY).

CREATE OR REPLACE FUNCTION canopy_metrics()
RETURNS JSONB
LANGUAGE sql STABLE
SET search_path = public, pg_temp
AS $$
WITH
-- #119 (canopy_llm_cost_keys): one read of the weekly LLM cost signal.
llm_cost AS (SELECT public.llm_cost_per_active_user_weekly() AS s),
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
        -- #119 (canopy_llm_cost_keys): weekly LLM cost per active user, as
        -- JSON integers (the route accepts only integers in totals). NULL (no
        -- active users in a window) is stripped: the key is omitted, never
        -- reported as a fake zero.
        'llm_microusd_per_user_7d',
            (SELECT round((s->>'usd_per_active_user_7d')::numeric * 1000000)::bigint FROM llm_cost),
        'llm_microusd_per_user_4w_base',
            (SELECT round((s->>'baseline_usd_per_active_user')::numeric * 1000000)::bigint FROM llm_cost),
        'llm_cost_jump_ratio_pct',
            (SELECT round((s->>'ratio')::numeric * 100)::bigint FROM llm_cost),
        'llm_cost_jump',
            (SELECT CASE (s->>'jump')::boolean WHEN true THEN 1 WHEN false THEN 0 END FROM llm_cost)
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
