-- Migration: performance indexes for hot-path read/filter queries
-- Run once in the Supabase SQL editor (idempotent — safe to re-run).
--
-- Adds the missing indexes called out in the backend performance audit:
--   #161  messages(session_id, created_at)        — chat-history load
--   #160  graph_edges(user_id | source | target)  — graph render + cascade delete
--   #176  sessions(user_id, started_at DESC)       — history list + profile stats
--   #177  documents(user_id, created_at | course)  — library list + study-guide ctx
--   #178  study_guides + quiz_attempts filters     — guide cache + achievement counts
--
-- Every statement uses CREATE INDEX IF NOT EXISTS so re-running is a no-op.

-- #161 messages: every chat load filters session_id, orders created_at asc.
CREATE INDEX IF NOT EXISTS idx_messages_session_created
    ON messages(session_id, created_at);

-- #160 graph_edges has zero indexes; graph render filters by user_id.
CREATE INDEX IF NOT EXISTS idx_graph_edges_user
    ON graph_edges(user_id);

-- Node-endpoint lookups: cascade delete scans by source_node_id.
CREATE INDEX IF NOT EXISTS idx_graph_edges_source
    ON graph_edges(source_node_id);

-- ...and the mirror direction for the second cascade-delete scan.
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
