-- Per-question mastery attribution (study roadmap §3.13).
--
-- Mastery has always been awarded WHOLE-ATTEMPT: one apply_graph_update call
-- against quiz_attempts.concept_node_id, regardless of what the individual
-- questions actually tested. A quiz that drifts across four concepts pays all
-- four answers into one node.
--
-- The roadmap needs per-subtopic mastery to mean something, so attribution
-- moves to the grain where it happens: one node per response.
--
-- Nullable on purpose, with three distinct reasons a row can carry NULL:
--   * every row written before this migration (no backfill — the question
--     text needed to resolve them is encrypted inside
--     quiz_attempts.questions_json, and guessing retroactively would be
--     worse than admitting the gap);
--   * a question whose `concept_tested` matched no node in the course —
--     these are reported through services/tool_signals.report_empty_result
--     rather than silently credited to the wrong concept;
--   * a legacy attempt with no concept_node_id to fall back to.
--
-- ON DELETE SET NULL rather than CASCADE: deleting a concept must not erase
-- the record that a student answered a question. The response survives,
-- unattributed.
--
-- This column is also what lets freshness (§3.7) ask the only question it
-- cares about — "when did this student last prove THIS subtopic?" —
-- as max(answered_at) WHERE is_correct AND concept_node_id = n.

ALTER TABLE quiz_responses
    ADD COLUMN IF NOT EXISTS concept_node_id TEXT
        REFERENCES graph_nodes(id) ON DELETE SET NULL;

-- Partial index: the freshness read and the submit-time grouping both filter
-- to rows that HAVE a node, and the NULL rows (every historical one) would
-- otherwise dominate the index for no reader's benefit.
CREATE INDEX IF NOT EXISTS idx_quiz_responses_concept_node
    ON quiz_responses(concept_node_id, answered_at DESC)
    WHERE concept_node_id IS NOT NULL;
