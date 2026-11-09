-- 20260927024349_learning_learner_state.sql
-- Learning loop series PKG-03: per-(user, concept) BKT/FSRS state and the
-- evidence columns on the mastery journal. Spec §4 PKG-03 block, verbatim
-- (including max_streak_unassisted, spec §13 Amendment A3).
-- Deploy order: this migration BEFORE the code (apply_graph_update names the
-- new node_mastery_events columns and the learner_state table).
CREATE TABLE IF NOT EXISTS learner_state (
  user_id            text NOT NULL,
  node_id            text NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
  p_known            double precision NOT NULL,
  n_strong_unassisted int NOT NULL DEFAULT 0,
  streak_unassisted  int NOT NULL DEFAULT 0,
  max_streak_unassisted int NOT NULL DEFAULT 0,   -- Amendment A3: wheelspin needs "ever reached 3"
  opps               int NOT NULL DEFAULT 0,
  fsrs_d             double precision,
  fsrs_s             double precision,
  fsrs_last_review_at timestamptz,
  fsrs_due_at        timestamptz,
  htc_k              double precision,
  unassisted_next    double precision,
  assist_gap         double precision,
  in_zone            boolean,
  last_evidence_at   timestamptz,
  updated_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, node_id)
);
CREATE INDEX IF NOT EXISTS learner_state_due_idx ON learner_state (user_id, fsrs_due_at);
ALTER TABLE node_mastery_events
  ADD COLUMN IF NOT EXISTS channel text,
  ADD COLUMN IF NOT EXISTS correct boolean,
  ADD COLUMN IF NOT EXISTS weight double precision,
  ADD COLUMN IF NOT EXISTS assisted boolean,
  ADD COLUMN IF NOT EXISTS max_rung smallint,
  ADD COLUMN IF NOT EXISTS p_before double precision,
  ADD COLUMN IF NOT EXISTS p_after double precision,
  ADD COLUMN IF NOT EXISTS session_id text,
  ADD COLUMN IF NOT EXISTS check_item_id text,
  ADD COLUMN IF NOT EXISTS question_hash text,
  ADD COLUMN IF NOT EXISTS confidence double precision;
-- evidence rows use event_type = 'evidence'; delta = p_after - p_before keeps legacy readers valid.
