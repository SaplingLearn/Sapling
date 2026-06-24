-- Migration: performance indexes for hot-path read/filter queries.
--
-- These indexes are also declared in 0001_baseline_schema.sql so fresh
-- environments get them at baseline time. This standalone migration exists for
-- EXISTING databases that were baselined before the indexes were added — the
-- migration runner records 0001 as already-applied on those, so the baseline
-- edit alone never reaches them. Every statement is idempotent
-- (CREATE INDEX IF NOT EXISTS), so it is a no-op where the index already exists.
--
-- Plain CREATE INDEX (not CONCURRENTLY): db/migrate.py applies each migration
-- inside a single transaction, and CREATE INDEX CONCURRENTLY cannot run in a
-- transaction block. For the original hot-prod rollout these were applied by
-- hand with CONCURRENTLY; this migration backfills any environment that missed
-- that manual step.
--
-- Audit references:
--   #161  messages(session_id, created_at)        — chat-history load
--   #160  graph_edges(user_id | source | target)  — graph render + cascade delete
--   #176  sessions(user_id, started_at DESC)       — history list + profile stats
--   #177  documents(user_id, created_at | course)  — library list + study-guide ctx
--   #178  study_guides + quiz_attempts filters     — guide cache + achievement counts

-- #161 messages: every chat load filters session_id, orders created_at asc.
CREATE INDEX IF NOT EXISTS idx_messages_session_created
    ON messages(session_id, created_at);

-- #160 graph_edges has zero indexes; graph render filters by user_id.
CREATE INDEX IF NOT EXISTS idx_graph_edges_user
    ON graph_edges(user_id);

-- Node-endpoint lookups: cascade delete scans by source_node_id. Kept as a
-- bare single-column index (not composite with user_id) so it also serves the
-- bulk dedup deletes in db/dedup_nodes.py:51, which filter source_node_id
-- via `in.(...)` WITHOUT user_id — a leading-user_id composite could not.
CREATE INDEX IF NOT EXISTS idx_graph_edges_source
    ON graph_edges(source_node_id);

-- ...and the mirror direction for the second cascade-delete scan (same
-- bare-endpoint rationale: also serves the target_node_id `in.(...)` dedup).
CREATE INDEX IF NOT EXISTS idx_graph_edges_target
    ON graph_edges(target_node_id);

-- #176 sessions: history list filters user_id, orders started_at desc.
CREATE INDEX IF NOT EXISTS idx_sessions_user_started
    ON sessions(user_id, started_at DESC);

-- #177 documents: library listing filters user_id, orders created_at desc.
CREATE INDEX IF NOT EXISTS idx_documents_user_created
    ON documents(user_id, created_at DESC);

-- Study-guide context fetch filters user_id + course_id.
CREATE INDEX IF NOT EXISTS idx_documents_user_course
    ON documents(user_id, course_id);

-- #178 study_guides: cached-guide listing filters user_id, orders generated_at.
CREATE INDEX IF NOT EXISTS idx_study_guides_user
    ON study_guides(user_id, generated_at DESC);

-- Cache-hit lookup keys on (user_id, course_id, exam_id).
CREATE INDEX IF NOT EXISTS idx_study_guides_lookup
    ON study_guides(user_id, course_id, exam_id);

-- quiz_attempts: achievement counts + history aggregations filter user_id.
CREATE INDEX IF NOT EXISTS idx_quiz_attempts_user
    ON quiz_attempts(user_id);
