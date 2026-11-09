-- 20261108093359_learning_posttest_outcomes.sql
-- Learning loop, spec §13 A126 (docs/research/learning-loop/2026-11-07-direction-
-- audit.md rec. 2: a 1-week plus a 4-week follow-up, a pretest form, and report
-- missing outcomes and uncertainty): the delayed post-test records enough to
-- support a learning claim.
--
-- 1. posttest_poses records how its item was chosen and what the answer
--    reports beside its outcome:
--    item_match       — the posed item against the student's pretest item (the
--                       concept's FIRST graded item, the A112 anchor): exact |
--                       difficulty | format | none | no_pretest;
--    item_source      — reserve (one of the concept's protected post-test items)
--                       | fallback (a fresh unprotected item);
--    served_at        — the item's first display (POST /posttest/shown, the
--                       server's clock);
--    answer_latency_s — answered_at − served_at, in seconds (NULL: never shown);
--    hidden_count, hidden_s — page-hidden periods and seconds while the item
--                       was on screen: client-reported, clamped by the server,
--                       never read by the grade.
--    A renewal (A89/A93) resets them with the outcome. Rows written before this
--    migration keep NULL: unknown, never inferred.
-- 2. posttest_skips — a due window /posttest/start had nothing fresh to pose
--    for, and why (no_items | exhausted | reported): one row per (student,
--    node, window), the latest reason. With the poses, every due window is
--    countable: answered, expired, open, skipped or never opened.
-- 3. posttest_anchors(...) — each concept's anchor (its FIRST graded evidence
--    time, the A112 anchor) for one student or every student, optionally in an
--    anchor-time range, keyset-paged by node id: PostgREST cannot GROUP BY.
--    STABLE, read-only.
--
-- Hashes, ids, codes, timestamps and numbers only — never item or answer text.
-- Backend-only (RLS on, no policy; service_role bypasses it). Idempotent.

ALTER TABLE posttest_poses ADD COLUMN IF NOT EXISTS item_match text;
ALTER TABLE posttest_poses ADD COLUMN IF NOT EXISTS item_source text;
ALTER TABLE posttest_poses ADD COLUMN IF NOT EXISTS served_at timestamptz;
ALTER TABLE posttest_poses ADD COLUMN IF NOT EXISTS answer_latency_s double precision;
ALTER TABLE posttest_poses ADD COLUMN IF NOT EXISTS hidden_count integer;
ALTER TABLE posttest_poses ADD COLUMN IF NOT EXISTS hidden_s double precision;

ALTER TABLE posttest_poses DROP CONSTRAINT IF EXISTS posttest_poses_item_match_check;
ALTER TABLE posttest_poses ADD CONSTRAINT posttest_poses_item_match_check
  CHECK (item_match IS NULL OR item_match IN ('exact', 'difficulty', 'format', 'none', 'no_pretest'));
ALTER TABLE posttest_poses DROP CONSTRAINT IF EXISTS posttest_poses_item_source_check;
ALTER TABLE posttest_poses ADD CONSTRAINT posttest_poses_item_source_check
  CHECK (item_source IS NULL OR item_source IN ('reserve', 'fallback'));

-- What an answer reports exists only on an answered pose: a latency needs the
-- display it is measured from, and the hidden telemetry is both values or
-- neither, never negative.
ALTER TABLE posttest_poses DROP CONSTRAINT IF EXISTS posttest_poses_answer_telemetry_check;
ALTER TABLE posttest_poses ADD CONSTRAINT posttest_poses_answer_telemetry_check
  CHECK (
    (answer_latency_s IS NULL
       OR (answer_latency_s >= 0 AND answered_at IS NOT NULL AND served_at IS NOT NULL))
    AND (hidden_count IS NULL) = (hidden_s IS NULL)
    AND (hidden_count IS NULL
       OR (hidden_count >= 0 AND hidden_s >= 0 AND answered_at IS NOT NULL))
  );

CREATE TABLE IF NOT EXISTS posttest_skips (
  user_id     text        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  node_id     text        NOT NULL,
  window_days integer     NOT NULL CHECK (window_days > 0),
  course_id   text        NOT NULL,
  reason      text        NOT NULL CHECK (reason IN ('no_items', 'exhausted', 'reported')),
  skipped_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, node_id, window_days)
);

-- Each concept's anchor. p_user_id NULL = every student (the admin funnel);
-- p_anchor_from / p_anchor_to bound the anchor (inclusive, NULL = open);
-- p_after_node_id is the keyset cursor (node ids after it); p_limit is clamped
-- to 1..1000, PostgREST's max rows. A node with no course is never posed, so
-- never returned. CREATE OR REPLACE: functions have no IF NOT EXISTS.
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

-- Backend-only (the 20261108041639_learning_item_quality.sql idiom): RLS with no
-- policy denies every non-bypass role; service_role (the backend) bypasses it.
-- Functions grant EXECUTE to PUBLIC by default, so that is revoked. Role
-- statements are guarded because those roles are Supabase's: a plain Postgres
-- has none of them, and an unguarded REVOKE naming one aborts the migration.
ALTER TABLE posttest_skips ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE posttest_skips FROM PUBLIC;
REVOKE ALL ON FUNCTION posttest_anchors(text, timestamptz, timestamptz, text, integer) FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE posttest_skips FROM %I', r);
            EXECUTE format(
                'REVOKE ALL ON FUNCTION posttest_anchors(text, timestamptz, timestamptz, text, integer) FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE posttest_skips TO service_role;
        GRANT EXECUTE ON FUNCTION posttest_anchors(text, timestamptz, timestamptz, text, integer) TO service_role;
    END IF;
END $$;

-- PostgREST serves the new columns, table and /rpc/posttest_anchors from its
-- schema cache; reload it (a no-op with no listener).
NOTIFY pgrst, 'reload schema';
