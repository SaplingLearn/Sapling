-- canopy_metrics(): the whole body of GET /api/internal/metrics
-- (routes/internal_metrics.py) as ONE JSONB document:
--
--     { "active_users": {"24h","7d","30d"},
--       "counts":  { <key>: {"24h","7d","30d"}, ... },    -- how many HAPPENED
--       "totals":  { <key>: n, ... } }                    -- how many EXIST now
--
-- Canopy — the team's dashboard — polls that route once an hour per environment
-- and stores every number append-only, first-write-wins. A wrong number is
-- therefore permanent, which decides everything below.
--
-- THIS FILE BUILDS ON 20260921041555_canopy_active_users.sql AND LEAVES IT — AND
-- ITS FUNCTION — ALONE. That migration merged with #654 and is applied on
-- staging, so it is immutable (db/migrations/README.md). This one is a
-- standalone successor that is correct in both worlds the ledger can be in:
--   * v1 already applied (staging): the events index below already exists and
--     IF NOT EXISTS skips it; canopy_active_users() is simply left in place.
--   * neither applied (production until `make promote`, a fresh local stack):
--     the runner applies v1 and then this, in filename order, in one go.
--
-- canopy_active_users() IS DELIBERATELY NOT DROPPED HERE. `migrate-staging`
-- runs on merge while Railway deploys the new image at about the same time,
-- and nothing orders the two. The code from #654 calls canopy_active_users();
-- the code shipping with this file calls canopy_metrics(). Dropping the old
-- function here would 503 the still-running old code until the new image is
-- live, and would break a rollback to the previous image outright. Keeping it
-- costs nothing: it is already REVOKEd from PUBLIC/anon/authenticated by v1,
-- it is a read-only three-integer aggregate, and its body is the `active` CTE
-- below — the two cannot disagree. The reverse window (new code live before
-- this migration) is a 503 from the route, which Canopy reads as "no reading
-- this hour", exactly as v1 behaved before ITS migration. A later cleanup
-- migration can drop canopy_active_users() once no deployed image calls it —
-- i.e. after this has reached production and a rollback past it is off the
-- table.

-- WHY ONE FUNCTION. PostgREST has no COUNT(DISTINCT), no SUM, no FILTER; the
-- existing answer (routes/admin_analytics.py) pages rows into Python and stops
-- at a 100,000-row cap with `truncated: true`. A truncated scan UNDERCOUNTS,
-- and here the undercount would be kept forever. Aggregates in Postgres cannot
-- truncate. And one statement means one snapshot and one now(): no number in a
-- response can contradict another. Same seam the RAG retrieval uses — a SQL
-- function reached via db.connection.rpc (0039's match_course_chunks).
--
-- WHY THE WINDOWS CANNOT DISAGREE. Every `counts` entry reads ONE 30-day row
-- set and cuts the two narrower windows out of it with FILTER, so
-- 24h <= 7d <= 30d by construction (the sums only ever add non-negative
-- values, so they are monotone too). Canopy drops a key whose windows do not
-- nest; the route refuses the whole response.
--
-- OMIT, NEVER APPROXIMATE. A key whose source cannot answer honestly is ABSENT
-- from the document — on the dashboard absent reads "not reported", while 0
-- reads as a measured zero. Two consequences in the SQL:
--   * `events` and `llm_usage` are written by a fire-and-forget queue with a
--     kill switch (EVENTS_LOGGING_ENABLED, services/events_service.py). With
--     it off both tables simply stop growing, and every count over them would
--     read 0. So the event-sourced keys are emitted only when `events` holds
--     at least one row in the 30-day window (a live app writes error.4xx rows
--     constantly — every stray 404 is one), and the llm_* keys only when
--     `llm_usage` does. A switch flipped yesterday is NOT detectable; this
--     catches an environment that is not recording at all.
--   * llm_cost_cents additionally needs one PRICED row in the window: cost_usd
--     is NULL for a model with no entry in services/llm_pricing.py, and a sum
--     over nothing but NULLs is not "zero cents".
--   Deliberately absent (see the PR): study_guides (that table is a cache —
--   every document upload deletes the offering's rows, so a windowed count
--   over it measures cache survival, not generation).
--
-- SOURCES, AND WHAT A DELETE DOES TO EACH. `counts` say what HAPPENED, so a
-- row soft-deleted afterwards still counts; `totals` say what EXISTS, so it
-- does not.
--   signups             users.created_at, google_id IS NOT NULL. The filter
--                       drops the stub rows graph_service.ensure_user_exists
--                       inserts ({id, streak_count}, no google_id) — a stub is
--                       not a person. Accounts later soft-deleted still count.
--                       (db/seed_local_rich's users carry no google_id either,
--                       so a freshly seeded LOCAL stack reports no users.)
--   approvals           admin_audit_log rows with action = 'user.approve' —
--                       approve ACTIONS, the same definition as the admin
--                       overview's approvals_by_day. Re-approving counts again.
--   tutor_sessions      events 'session.started', not the `sessions` table:
--   chat_messages       events 'chat.message_sent', not `messages`. A student
--                       deleting a session HARD-deletes the session and every
--                       message in it (routes/learn.py), so those tables
--                       forget what happened; the events do not, and each is
--                       emitted at the single place its row is written.
--                       chat_messages = student turns (one event per persisted
--                       turn), not assistant replies.
--   documents_uploaded  events 'document.upload' — accepted upload ATTEMPTS.
--                       There is no table row until processing succeeds.
--   documents_processed documents.processed_at (stamped at insert, which only
--                       happens after processing). Soft-deleted rows count.
--   quizzes_started     quiz_attempts.created_at (the row is written when the
--   quizzes_completed   quiz is served); completed_at is stamped by submit.
--                       Never deleted. Abandoned attempts are started, not
--                       completed.
--   notes_created       notes.created_at; soft-deleted rows count.
--   flashcards_created  flashcards.created_at. Cards are HARD-deleted one at a
--                       time by their owner and nothing else records a card's
--                       creation, so this is "created in the window and not
--                       deleted since" — a lower bound.
--   xp_events           xp_events.created_at (append-only ledger).
--   achievements_earned user_achievements.earned_at (includes admin grants).
--   room_messages       room_messages.created_at; is_deleted rows count.
--   feedback            feedback.created_at / issue_reports.created_at. Rows
--   issue_reports       only — the free text is encrypted and never read.
--   llm_calls           llm_usage rows; SUM(total_tokens); and
--   llm_tokens          ROUND(SUM(cost_usd) * 100) as integer cents, rounding
--   llm_cost_cents      half-up. NULL costs are ignored, so cents is a LOWER
--                       bound wherever a model is unpriced.
--   errors_5xx/_4xx     events 'error.5xx' / 'error.4xx' — RequestIDMiddleware
--                       writes exactly one per response with status >= 400
--                       (and one per unhandled crash), choosing the type from
--                       the status code, so the type IS the status class. 4xx
--                       includes anonymous and bot traffic, and Canopy's own
--                       rejected polls.
--   quiz_generation_failed, quiz_context_write_failed, rag_retrieval_failed,
--   rag_visibility_resync_failed, logins
--                       one event each, by event_type.
--   rag_chunks_dropped  events 'rag.chunks_dropped': indexing RUNS that lost
--                       at least one chunk — not the number of chunks.
--   totals.users / users_pending   users with a google_id and deleted_at IS
--                       NULL / of those, is_approved = false.
--   totals.documents / notes       deleted_at IS NULL.
--   totals.flashcards / rooms      every row (hard-deleted rows are gone).
--   totals.rag_chunks / rag_document_chunks   course_chunks rows / those with
--                       category IS DISTINCT FROM 'catalog' (the partition
--                       20260920072705 uses). "0 document chunks" was #628.
--
-- Nothing here is per-user, a distinct-users-per-feature figure, an average,
-- free text or latency. Adding a key = one branch below plus one line in the
-- PR; the route validates and forwards keys generically.
--
-- TYPES. COUNT and SUM(integer) are BIGINT and the cents are cast to BIGINT, so
-- every JSONB number is an integer — PostgREST sends the document through as
-- JSON numbers, never strings. The route checks for exactly that.
--
-- SECURITY INVOKER (the default): the backend connects as `service_role`,
-- which bypasses RLS, so nothing needs a definer's rights. search_path is
-- pinned anyway so the table names below can only ever mean public.*.
--
-- CREATE OR REPLACE: functions have no IF NOT EXISTS form, and replacing with
-- the identical body is the no-op wanted on re-run. No arguments, so a later
-- change to the BODY can never leave a stale overload behind (the trap
-- 20260920072705 had to work around). The return type is one JSONB, so adding
-- a key never needs DROP FUNCTION either.
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
    WHERE completed_at >= now() - interval '30 days'

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

-- Backend-only. Postgres grants EXECUTE on a new function to PUBLIC, and
-- Supabase's default privileges grant it to `anon` and `authenticated` as well
-- — and PostgREST exposes every public-schema function at /rest/v1/rpc/<name>.
-- The frontend ships the anon key, so without this anyone holding it could read
-- the whole document straight from Supabase, bypassing the route's bearer
-- token. The backend connects as `service_role`.
--
-- The role-specific statements are guarded because those three roles are
-- Supabase's: a plain Postgres (a scratch database, a future CI lane) has none
-- of them, and an unguarded REVOKE/GRANT naming a missing role aborts the whole
-- migration.
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

-- INDEXES. A windowed read must be able to skip everything older than 30 days,
-- or it gets slower every month the table grows. Only the tables that grow
-- PER INTERACTION and have no retention get one; the per-artifact tables
-- (documents, notes, flashcards, quiz_attempts, feedback, issue_reports,
-- user_achievements) are small enough that a sequential scan is cheaper than
-- carrying an index on the write path — measured, see the PR.
--
--   events      0035's three indexes lead with user_id / event_type / category.
--               The per-type counts ride idx_events_type_created as it is; the
--               active-user count and the "is anything being recorded" probe
--               need one that LEADS with created_at. v1 (20260921041555)
--               already creates exactly this index, so wherever v1 ran this
--               line is a skip. It is repeated so this file states everything
--               canopy_metrics() depends on, and stays correct by itself.
--   llm_usage   0035: (feature, created_at), (user_id, created_at).
--   xp_events   20260731193214: (user_id, created_at).
--   room_messages  0001: (room_id, created_at).
--
-- Plain CREATE INDEX (not CONCURRENTLY, which cannot run inside the transaction
-- db/migrate.py wraps each file in). Each build blocks writes to its table
-- while it runs — milliseconds at today's sizes. `events` and `llm_usage` are
-- written only by events_service's background drain thread, off the request
-- path; an XP award or a room message sent in that instant waits for the build.
CREATE INDEX IF NOT EXISTS idx_events_created_user   ON events        (created_at, user_id);
CREATE INDEX IF NOT EXISTS idx_llm_usage_created     ON llm_usage     (created_at);
CREATE INDEX IF NOT EXISTS idx_xp_events_created     ON xp_events     (created_at);
CREATE INDEX IF NOT EXISTS idx_room_messages_created ON room_messages (created_at);

-- PostgREST resolves /rpc/<name> from its schema cache, and a function it has
-- not cached is a 404 ("not in the schema cache") — which the route would serve
-- as a 503 until something else reloaded it. Hosted Supabase reloads on DDL by
-- itself; the local stack does not reliably (docs/local-supabase.md). Asking
-- is free: NOTIFY is delivered at COMMIT, and with no listener it is a no-op.
NOTIFY pgrst, 'reload schema';
