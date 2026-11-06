-- #760 (state-machine audit, workstream D): canopy `quizzes_completed`
-- counts SCORED attempts only.
--
-- Submit stamps completed_at with its atomic claim BEFORE grading, so until
-- #760 a submit that failed after the claim left a row completed-but-scoreless
-- — and canopy_metrics() counted it as a completed quiz. #760 makes the score
-- always land (or releases the claim), but rows stranded before it remain, and
-- Canopy keeps every reading forever (20260921055024's header), so the count
-- must not depend on that never happening. A persisted score is the evidence a
-- quiz was really finished — the same signal achievement_service's
-- quizzes_completed stat and agents/tools/quiz_history.py treat as completion.
--
-- The ONLY change from 20260921055024 is the `AND score IS NOT NULL` on the
-- quizzes_completed branch; the key list, windows and the rest of the body are
-- copied verbatim, so the contract (keys, nesting, integer types) is unchanged.
-- The window still nests (24h <= 7d <= 30d): the extra predicate is applied to
-- the one 30-day row set the narrower FILTERs cut from.
--
-- CREATE OR REPLACE keeps the function's owner and privileges; the REVOKE/GRANT
-- block is repeated anyway so this file states everything it relies on (the
-- same reasoning 20260921055024 gives for repeating v1's index).
CREATE OR REPLACE FUNCTION canopy_metrics()
RETURNS JSONB
LANGUAGE sql STABLE
SET search_path = public, pg_temp
AS $$
WITH
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
)
SELECT jsonb_build_object(
    'active_users',
        (SELECT jsonb_build_object('24h', d1, '7d', d7, '30d', d30) FROM active),
    'counts',
        (SELECT COALESCE(
                    jsonb_object_agg(key, jsonb_build_object('24h', d1, '7d', d7, '30d', d30)),
                    '{}'::jsonb)
         FROM counts),
    'totals', jsonb_build_object(
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
                                WHERE category IS DISTINCT FROM 'catalog')
    )
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
