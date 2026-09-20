-- Prod reconciliation: create graph_edges to match migration 0023.
-- Its CREATE was missing on prod (node_mastery_events + graph_nodes from 0023 ARE
-- present, so 0023 was partially hand-applied). graph_service.py reads/writes this
-- table on every graph op. Adds ONE empty table + 3 indexes. No existing row is
-- touched. Idempotent (IF NOT EXISTS), atomic (single transaction).
CREATE TABLE IF NOT EXISTS graph_edges (
    id                TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id           TEXT NOT NULL REFERENCES users(id)       ON DELETE CASCADE,
    source_node_id    TEXT NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    target_node_id    TEXT NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    relationship_type TEXT NOT NULL DEFAULT 'related'
                        CHECK (relationship_type IN ('related','prerequisite','builds_on','part_of')),
    strength          DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, source_node_id, target_node_id, relationship_type)   -- dedup (#195)
);
CREATE INDEX IF NOT EXISTS idx_graph_edges_user   ON graph_edges(user_id);
CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON graph_edges(source_node_id);
CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON graph_edges(target_node_id);
