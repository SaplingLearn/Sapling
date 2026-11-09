-- 20260929050404_learning_ai_tutor_daily_calls.sql
-- Learning loop, owner decision A38 on HANDOFF-06b ("New"): a daily cap on the
-- COUNT of tutor calls per student. Every $/token cap in services/ai_budget.py
-- reads llm_usage, and llm_usage is blind twice over: its cost read 0 on every
-- deployed backend for two months (#689), and EVENTS_LOGGING_ENABLED=false
-- writes no rows at all. This counter is written directly, never through
-- events_service, so it holds in both cases.
--
-- One row per (student, UTC day); `day` is passed by the backend (the UTC date
-- of its clock), so the database's timezone never moves a day boundary.
-- Counts only, never content. Rows of past days are inert (the cap reads today's
-- row only); nothing prunes them yet.
CREATE TABLE IF NOT EXISTS ai_tutor_daily_calls (
  user_id    text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  day        date NOT NULL,
  calls      integer NOT NULL DEFAULT 0 CHECK (calls >= 0),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, day)
);

-- The atomic increment: one statement, so two workers counting the same
-- student's calls can never lose one (a read-then-write from Python would).
-- Returns the new count. CREATE OR REPLACE: functions have no IF NOT EXISTS
-- form, and replacing with the identical body is the no-op a re-run wants.
CREATE OR REPLACE FUNCTION ai_budget_bump_tutor_calls(p_user_id text, p_day date)
RETURNS integer
LANGUAGE sql
VOLATILE
AS $$
    INSERT INTO ai_tutor_daily_calls (user_id, day, calls)
    VALUES (p_user_id, p_day, 1)
    ON CONFLICT (user_id, day) DO UPDATE
        SET calls = ai_tutor_daily_calls.calls + 1,
            updated_at = now()
    RETURNING calls;
$$;

-- Backend-only. The frontend ships the anon key and PostgREST exposes every
-- public-schema table and function, so without this anyone holding it could
-- read another student's counter or reset their own cap. RLS with no policy
-- denies every non-bypass role; service_role (the backend) bypasses RLS.
-- Role statements are guarded because those roles are Supabase's: a plain
-- Postgres has none of them, and an unguarded REVOKE naming one aborts the
-- whole migration. Same idiom as 20260921041555_canopy_active_users.sql.
ALTER TABLE ai_tutor_daily_calls ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE ai_tutor_daily_calls FROM PUBLIC;
REVOKE ALL ON FUNCTION ai_budget_bump_tutor_calls(text, date) FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE ai_tutor_daily_calls FROM %I', r);
            EXECUTE format(
                'REVOKE ALL ON FUNCTION ai_budget_bump_tutor_calls(text, date) FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE ai_tutor_daily_calls TO service_role;
        GRANT EXECUTE ON FUNCTION ai_budget_bump_tutor_calls(text, date) TO service_role;
    END IF;
END $$;

-- PostgREST resolves /rpc/<name> from its schema cache; the local stack does
-- not reliably reload on DDL (docs/local-supabase.md). NOTIFY is delivered at
-- COMMIT and is a no-op with no listener.
NOTIFY pgrst, 'reload schema';
