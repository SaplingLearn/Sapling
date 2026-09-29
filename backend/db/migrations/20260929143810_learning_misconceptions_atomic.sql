-- 20260929143810_learning_misconceptions_atomic.sql
-- Learning loop PKG-10 fix round (F5, F6; spec §13 A75). A NEW migration:
-- 20260929132008_learning_misconceptions.sql is applied and never edited.
--
-- F5: learning.misconceptions.record was a read-then-insert/update from
-- Python, so two concurrent grades could open two rows for one key or lose an
-- increment. One open row per (student, node, key) is now a partial UNIQUE
-- index (never on the encrypted evidence_text), and the insert-or-increment is
-- ONE statement, misconception_record(...), INSERT ... ON CONFLICT on that
-- index. Open duplicates a racing writer may have left are merged first (their
-- counts summed onto the most recently seen row).
--
-- F6: the class rollup joins each row's node to its OWN student
-- (g.user_id = m.user_id) as defense in depth: a row naming another student's
-- node never counts. Same signature, same floor, same grants.
WITH ranked AS (
  SELECT id,
         row_number() OVER (PARTITION BY user_id, node_id, wrong_key
                            ORDER BY last_seen_at DESC, id) AS rn,
         sum(count) OVER (PARTITION BY user_id, node_id, wrong_key) AS total
  FROM misconceptions
  WHERE resolved_at IS NULL
)
UPDATE misconceptions m SET count = r.total
FROM ranked r
WHERE m.id = r.id AND r.rn = 1 AND m.count <> r.total;

WITH ranked AS (
  SELECT id,
         row_number() OVER (PARTITION BY user_id, node_id, wrong_key
                            ORDER BY last_seen_at DESC, id) AS rn
  FROM misconceptions
  WHERE resolved_at IS NULL
)
DELETE FROM misconceptions m USING ranked r WHERE m.id = r.id AND r.rn > 1;

CREATE UNIQUE INDEX IF NOT EXISTS misconceptions_open_key_uidx
  ON misconceptions (user_id, node_id, wrong_key) WHERE resolved_at IS NULL;

CREATE OR REPLACE FUNCTION misconception_record(
  p_id text, p_user_id text, p_node_id text, p_check_item_id text,
  p_wrong_key text, p_evidence_text text
)
RETURNS TABLE (id text, count int)
LANGUAGE sql SET search_path = public, pg_temp AS $$
  INSERT INTO misconceptions
    (id, user_id, node_id, check_item_id, wrong_key, evidence_text, count)
  VALUES (p_id, p_user_id, p_node_id, p_check_item_id, p_wrong_key, p_evidence_text, 1)
  ON CONFLICT (user_id, node_id, wrong_key) WHERE resolved_at IS NULL
  DO UPDATE SET count = misconceptions.count + 1,
                last_seen_at = now(),
                check_item_id = EXCLUDED.check_item_id,
                evidence_text = EXCLUDED.evidence_text
  RETURNING misconceptions.id, misconceptions.count
$$;

CREATE OR REPLACE FUNCTION misconception_rollup(p_course_id text)
RETURNS TABLE (concept_key text, wrong_key text, users int)
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT lower(btrim(regexp_replace(g.concept_name, '\s+', ' ', 'g'))), m.wrong_key,
         count(DISTINCT m.user_id)::int
  FROM misconceptions m JOIN graph_nodes g ON g.id = m.node_id
  WHERE g.course_id = p_course_id AND g.user_id = m.user_id AND m.resolved_at IS NULL
  GROUP BY g.course_id, lower(btrim(regexp_replace(g.concept_name, '\s+', ' ', 'g'))), m.wrong_key
  HAVING count(DISTINCT m.user_id) >= 5
$$;

-- Backend-only, like the rollup (20260929132008): functions grant EXECUTE to
-- PUBLIC by default; the Supabase roles are guarded (a plain Postgres has none).
REVOKE ALL ON FUNCTION misconception_record(text, text, text, text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION misconception_rollup(text) FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION misconception_record(text, text, text, text, text, text) FROM %I', r);
            EXECUTE format('REVOKE ALL ON FUNCTION misconception_rollup(text) FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION misconception_record(text, text, text, text, text, text) TO service_role;
        GRANT EXECUTE ON FUNCTION misconception_rollup(text) TO service_role;
    END IF;
END $$;

NOTIFY pgrst, 'reload schema';
