-- Learning loop series PKG-14 half B (review fix round, regression M2, spec §13 A95):
-- re-derive every stored graph_nodes.mastery_tier from mastery_score with the
-- ONE tier function's cuts (learning/bkt.py::tier_for over learning/params.py
-- TIER_UNEXPLORED_MAX 0.10 / BAND_NOVICE_MAX 0.30 / BKT_PROFICIENT 0.95).
-- Rows written under the retired 0.1 / 0.45 / 0.75 cuts would otherwise keep
-- them until their next write — a "mastered" 0.8 node demoted after a good quiz.
-- The CASE mirrors tier_for exactly (pinned by
-- tests/test_learning_tier_rederive_migration.py). Scores are clamped to [0, 1]
-- as tier_for's callers clamp. 'subject_root' rows (CHECK, 0023) are left alone.
-- Idempotent: only rows whose tier differs are touched; a second run is a no-op.
-- Runs at the migration step of the launch runbook (half B ships it).
UPDATE graph_nodes
SET mastery_tier = CASE
    WHEN p >= 0.95 THEN 'mastered'
    WHEN p >= 0.30 THEN 'learning'
    WHEN p >= 0.10 THEN 'struggling'
    ELSE 'unexplored'
  END
FROM (
  SELECT id AS node_id, LEAST(1.0, GREATEST(0.0, COALESCE(mastery_score, 0.0))) AS p
  FROM graph_nodes
) AS s
WHERE graph_nodes.id = s.node_id
  AND graph_nodes.mastery_tier IS DISTINCT FROM 'subject_root'
  AND graph_nodes.mastery_tier IS DISTINCT FROM (
    CASE
      WHEN s.p >= 0.95 THEN 'mastered'
      WHEN s.p >= 0.30 THEN 'learning'
      WHEN s.p >= 0.10 THEN 'struggling'
      ELSE 'unexplored'
    END
  );
