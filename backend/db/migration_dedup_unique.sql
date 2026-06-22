-- Migration: UNIQUE constraints behind graph-node and graph-edge dedup
-- Run once in the Supabase SQL editor (Postgres 15+ for NULLS NOT DISTINCT).
--
-- Today dedup is best-effort in application code (a select-then-insert race in
-- services/graph_service.py) plus a manual db/dedup_nodes.py cleanup script.
-- Two concurrent apply_graph_update calls both miss the existence check and
-- write duplicates. This migration makes duplicates impossible at the DB level:
--   #181  graph_nodes  UNIQUE(user_id, lower(concept_name), course_id)
--   #195  graph_edges  UNIQUE(user_id, source_node_id, target_node_id)
--
-- Existing duplicate rows must be collapsed before the unique index can build,
-- so each section dedups first (keeping the strongest/oldest row) and repoints
-- or removes dependents, mirroring db/dedup_nodes.py.

-- #181 node dedup. The window ranks rows within each (user, normalized concept,
-- course) group; rn > 1 are the duplicates to collapse. Same ranking is reused
-- by each dependent-cleanup statement so they target an identical "losers" set.

-- 1. Remove edges that reference a soon-to-be-removed duplicate node.
WITH ranked AS (
  SELECT id, row_number() OVER (
    PARTITION BY user_id, lower(concept_name), course_id
    ORDER BY mastery_score DESC NULLS LAST, times_studied DESC NULLS LAST, id
  ) AS rn
  FROM graph_nodes
), losers AS (SELECT id FROM ranked WHERE rn > 1)
DELETE FROM graph_edges
 WHERE source_node_id IN (SELECT id FROM losers)
    OR target_node_id IN (SELECT id FROM losers);

-- 2. Null quiz_attempts.concept_node_id (nullable FK) pointing at a duplicate.
WITH ranked AS (
  SELECT id, row_number() OVER (
    PARTITION BY user_id, lower(concept_name), course_id
    ORDER BY mastery_score DESC NULLS LAST, times_studied DESC NULLS LAST, id
  ) AS rn
  FROM graph_nodes
), losers AS (SELECT id FROM ranked WHERE rn > 1)
UPDATE quiz_attempts SET concept_node_id = NULL
 WHERE concept_node_id IN (SELECT id FROM losers);

-- 3. Delete quiz_context rows tied to a duplicate node (NOT NULL FK).
WITH ranked AS (
  SELECT id, row_number() OVER (
    PARTITION BY user_id, lower(concept_name), course_id
    ORDER BY mastery_score DESC NULLS LAST, times_studied DESC NULLS LAST, id
  ) AS rn
  FROM graph_nodes
), losers AS (SELECT id FROM ranked WHERE rn > 1)
DELETE FROM quiz_context
 WHERE concept_node_id IN (SELECT id FROM losers);

-- 4. Finally delete the duplicate nodes themselves (winners — rn = 1 — stay).
WITH ranked AS (
  SELECT id, row_number() OVER (
    PARTITION BY user_id, lower(concept_name), course_id
    ORDER BY mastery_score DESC NULLS LAST, times_studied DESC NULLS LAST, id
  ) AS rn
  FROM graph_nodes
)
DELETE FROM graph_nodes
 WHERE id IN (SELECT id FROM ranked WHERE rn > 1);

-- Now the rows are unique, build the constraint. lower(concept_name) matches the
-- app's _normalize_concept (casefold + already-collapsed whitespace). NULLS NOT
-- DISTINCT (PG15+) so two course-less nodes for the same concept also collide.
CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_nodes_user_concept_course
    ON graph_nodes(user_id, lower(concept_name), course_id) NULLS NOT DISTINCT;

-- #195 edge dedup: collapse duplicate (user, source, target) edges, keeping the
-- oldest (then lowest id) so the constraint below can build.
WITH ranked AS (
  SELECT id, row_number() OVER (
    PARTITION BY user_id, source_node_id, target_node_id
    ORDER BY created_at ASC NULLS LAST, id
  ) AS rn
  FROM graph_edges
)
DELETE FROM graph_edges
 WHERE id IN (SELECT id FROM ranked WHERE rn > 1);

-- Backs the upsert(on_conflict="user_id,source_node_id,target_node_id") that
-- replaces the racy select-then-insert in graph_service.apply_graph_update.
CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_edges_unique
    ON graph_edges(user_id, source_node_id, target_node_id);
