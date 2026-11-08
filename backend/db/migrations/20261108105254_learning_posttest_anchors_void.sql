-- 20261108105254_learning_posttest_anchors_void.sql
-- Learning loop spec §13 A123 × A126: the delayed post-test's concept anchors
-- leave void evidence out.
--
-- A concept's post-test windows run from its ANCHOR, its first graded evidence
-- (A112). Since A123 a row graded against an item staff retired is void, is no
-- evidence, and never anchors: loop_state_store.evidence_spans (the anchor the
-- route poses from) and the trial export's restatement both skip the rows that
-- learning_evidence_voids names. A126's posttest_anchors
-- (20261108093359_learning_posttest_outcomes.sql), written before A123 was
-- merged, took the earliest evidence row of any kind, so its readers (the
-- student's "retention check due" read and the admin funnel's due windows)
-- could anchor a concept on a void row, while the route posted from the first
-- valid one.
--
-- This migration re-creates the function as A126's definition with one change
-- in each branch: the void record's rows are left out of the first-evidence
-- read. A126's migration itself is not edited; the registry in
-- backend/tests/test_learning_migration_functions.py pins that the last
-- definition keeps A126's contract and A123's rule.

CREATE OR REPLACE FUNCTION posttest_anchors(
  p_user_id text,
  p_anchor_from timestamptz,
  p_anchor_to timestamptz,
  p_after_node_id text,
  p_limit integer
)
RETURNS TABLE (node_id text, user_id text, course_id text, concept_name text, anchor_at timestamptz)
LANGUAGE plpgsql
STABLE
SET search_path = public, pg_temp
AS $$
#variable_conflict use_column
DECLARE
  v_limit integer := LEAST(GREATEST(coalesce(p_limit, 1000), 1), 1000);
BEGIN
  IF p_user_id IS NOT NULL THEN
    RETURN QUERY
    SELECT g.id, g.user_id, g.course_id, g.concept_name, a.first_at
      FROM graph_nodes g
      CROSS JOIN LATERAL (
        SELECT min(e.created_at) AS first_at
          FROM node_mastery_events e
         WHERE e.node_id = g.id AND e.event_type = 'evidence'
           -- spec §13 A123: a void row is no evidence and never anchors
           AND NOT EXISTS (SELECT 1 FROM learning_evidence_voids v WHERE v.event_id = e.id)
      ) a
     WHERE g.user_id = p_user_id
       AND g.course_id IS NOT NULL
       AND a.first_at IS NOT NULL
       AND (p_anchor_from IS NULL OR a.first_at >= p_anchor_from)
       AND (p_anchor_to IS NULL OR a.first_at <= p_anchor_to)
       AND (p_after_node_id IS NULL OR g.id > p_after_node_id)
     ORDER BY g.id
     LIMIT v_limit;
  ELSE
    RETURN QUERY
    SELECT g.id, g.user_id, g.course_id, g.concept_name, a.first_at
      FROM (
        -- the cursor bounds the aggregate itself: a page groups only the
        -- nodes after the previous page, never the whole journal again
        SELECT e.node_id AS anchored_node, min(e.created_at) AS first_at
          FROM node_mastery_events e
         WHERE e.event_type = 'evidence'
           AND (p_after_node_id IS NULL OR e.node_id > p_after_node_id)
           -- spec §13 A123: a void row is no evidence and never anchors
           AND NOT EXISTS (SELECT 1 FROM learning_evidence_voids v WHERE v.event_id = e.id)
         GROUP BY e.node_id
      ) a
      JOIN graph_nodes g ON g.id = a.anchored_node
     WHERE g.course_id IS NOT NULL
       AND (p_anchor_from IS NULL OR a.first_at >= p_anchor_from)
       AND (p_anchor_to IS NULL OR a.first_at <= p_anchor_to)
     ORDER BY g.id
     LIMIT v_limit;
  END IF;
END
$$;

REVOKE ALL ON FUNCTION posttest_anchors(text, timestamptz, timestamptz, text, integer) FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format(
                'REVOKE ALL ON FUNCTION posttest_anchors(text, timestamptz, timestamptz, text, integer) FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION posttest_anchors(text, timestamptz, timestamptz, text, integer) TO service_role;
    END IF;
END $$;

-- PostgREST resolves functions from its schema cache; the local stack does not
-- reliably reload on DDL (docs/local-supabase.md). NOTIFY is delivered at
-- COMMIT and is a no-op with no listener.
NOTIFY pgrst, 'reload schema';
