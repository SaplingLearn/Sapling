-- Evidence provenance for cross-session goal readiness. Legacy NULL is unknown;
-- do not backfill independence from weight, scores or old session summaries.
ALTER TABLE node_mastery_events
  ADD COLUMN IF NOT EXISTS planning_observation jsonb
  CHECK (planning_observation IS NULL OR jsonb_typeof(planning_observation) = 'object');

-- This column is deliberately NOT an optional-column write downgrade. Tagged
-- loop grades must append the event before scalar writes, or return retryable
-- unavailable. Apply before serving the new tagged grading path.
