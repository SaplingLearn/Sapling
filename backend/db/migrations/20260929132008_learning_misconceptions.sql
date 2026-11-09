-- 20260929132008_learning_misconceptions.sql
-- Learning loop series PKG-10: per-student misconception store fed by the
-- grader's matched wrong key (spec §3.3 rule, §4 PKG-10 block), plus the
-- class rollup. `evidence_text` is encrypted (services/encryption.py) and is
-- never filtered on; `wrong_key` is the plaintext key from common_wrong_json.
-- The rollup returns nothing below MISCONCEPTION_ROLLUP_MIN_USERS distinct
-- students (learning/params.py mirrors the literal below; the test pins them
-- equal) and is executable by service_role only — it is a backend function,
-- not a tutor tool (ADR 0023 §5).
CREATE TABLE IF NOT EXISTS misconceptions (
  id             text PRIMARY KEY,
  user_id        text NOT NULL,
  node_id        text NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
  check_item_id  text,
  wrong_key      text NOT NULL,             -- plaintext enum key from common_wrong_json
  evidence_text  text,                      -- encrypted
  count          int NOT NULL DEFAULT 1,
  first_seen_at  timestamptz NOT NULL DEFAULT now(),
  last_seen_at   timestamptz NOT NULL DEFAULT now(),
  resolved_at    timestamptz
);
CREATE INDEX IF NOT EXISTS misconceptions_user_node_idx ON misconceptions (user_id, node_id, wrong_key);
-- graph_nodes rows are per user, so the rollup groups by the COURSE concept, never by
-- node_id (A29). concept_key mirrors services/graph_service._normalize_concept (runs of
-- whitespace become one space, trimmed, case-folded) and equals check_items.concept_key
-- (A2). SQL lower() stands in for Python casefold(): they agree on ASCII names and
-- can differ on some non-ASCII characters (e.g. ß, which casefold expands).
-- SECURITY DEFINER pins its search_path, so no caller-controlled schema can
-- shadow `misconceptions` or `graph_nodes` inside it (PKG-10 Deviation to §4).
CREATE OR REPLACE FUNCTION misconception_rollup(p_course_id text)
RETURNS TABLE (concept_key text, wrong_key text, users int)
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT lower(btrim(regexp_replace(g.concept_name, '\s+', ' ', 'g'))), m.wrong_key,
         count(DISTINCT m.user_id)::int
  FROM misconceptions m JOIN graph_nodes g ON g.id = m.node_id
  WHERE g.course_id = p_course_id AND m.resolved_at IS NULL
  GROUP BY g.course_id, lower(btrim(regexp_replace(g.concept_name, '\s+', ' ', 'g'))), m.wrong_key
  HAVING count(DISTINCT m.user_id) >= 5
$$;

-- Backend-only. The frontend ships the anon key and PostgREST exposes every
-- public-schema table and function: without this anyone holding it could read
-- another student's misconceptions or call the rollup below its floor's
-- intent. RLS with no policy denies every non-bypass role; service_role (the
-- backend) bypasses RLS. Functions grant EXECUTE to PUBLIC by default, so
-- PUBLIC is revoked outright. Role statements are guarded because those roles
-- are Supabase's: a plain Postgres has none of them, and an unguarded REVOKE
-- naming one aborts the whole migration. Same idiom as
-- 20260929050404_learning_ai_tutor_daily_calls.sql.
ALTER TABLE misconceptions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE misconceptions FROM PUBLIC;
REVOKE ALL ON FUNCTION misconception_rollup(text) FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE misconceptions FROM %I', r);
            EXECUTE format('REVOKE ALL ON FUNCTION misconception_rollup(text) FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE misconceptions TO service_role;
        GRANT EXECUTE ON FUNCTION misconception_rollup(text) TO service_role;
    END IF;
END $$;

-- PostgREST resolves /rpc/<name> from its schema cache; the local stack does
-- not reliably reload on DDL (docs/local-supabase.md). NOTIFY is delivered at
-- COMMIT and is a no-op with no listener.
NOTIFY pgrst, 'reload schema';
