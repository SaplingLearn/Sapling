-- 20260927182054_learning_mastery_event_seq.sql
-- Learning loop, PKG-03 reopen (spec §4, §13 A36): the apply order of the
-- evidence journal. Every row one apply_graph_update call journals shares one
-- created_at and has a random uuid id, so nothing else orders them for a replay
-- (the 2026-09-27 live sequence test had to re-order a 3-question quiz from its
-- p_before -> p_after links). The evidence path sets 0..n-1 in apply order
-- within the call; a replay orders by (created_at, evidence_seq). NULL on every
-- legacy journal row and on evidence rows written before this migration.
-- Deploy order: this migration BEFORE the code (the evidence path names it).
ALTER TABLE node_mastery_events ADD COLUMN IF NOT EXISTS evidence_seq integer
  CHECK (evidence_seq IS NULL OR evidence_seq >= 0);
