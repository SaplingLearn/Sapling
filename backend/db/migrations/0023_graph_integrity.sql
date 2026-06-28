-- 0023: knowledge-graph integrity — FKs, UNIQUE-backed dedup, indexes, mastery-event rows.
-- graph_nodes stay on the ABSTRACT course (mastery is cumulative across terms).
-- No user data -> drop/recreate. CASCADE clears FKs from note_concepts/quiz_* (rebuilt in 0025).

DROP TABLE IF EXISTS graph_edges CASCADE;
DROP TABLE IF EXISTS graph_nodes CASCADE;

CREATE TABLE graph_nodes (
    id              TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id         TEXT NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
    course_id       TEXT REFERENCES courses(id)          ON DELETE SET NULL,   -- abstract course; nullable
    concept_name    TEXT NOT NULL,
    subject         TEXT,
    mastery_score   DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    mastery_tier    TEXT NOT NULL DEFAULT 'unexplored'
                      CHECK (mastery_tier IN ('unexplored','struggling','learning','mastered','subject_root')),
    times_studied   INTEGER NOT NULL DEFAULT 0,
    last_studied_at TIMESTAMPTZ,
    color           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (user_id, course_id, concept_name)   -- backs dedup; retires dedup_nodes.py (#181)
);
CREATE INDEX idx_graph_nodes_user   ON graph_nodes(user_id);
CREATE INDEX idx_graph_nodes_course ON graph_nodes(course_id);

-- Append-only mastery events (replaces graph_nodes.mastery_events jsonb; fixes non-atomic RMW #247).
CREATE TABLE node_mastery_events (
    id         TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    node_id    TEXT NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    delta      DOUBLE PRECISION NOT NULL,
    reason     TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_node_mastery_events_node ON node_mastery_events(node_id, created_at);

CREATE TABLE graph_edges (
    id                TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id           TEXT NOT NULL REFERENCES users(id)       ON DELETE CASCADE,   -- FK added (#179)
    source_node_id    TEXT NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    target_node_id    TEXT NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    relationship_type TEXT NOT NULL DEFAULT 'related'
                        CHECK (relationship_type IN ('related','prerequisite','builds_on','part_of')),
    strength          DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, source_node_id, target_node_id, relationship_type)   -- backs dedup (#195)
);
CREATE INDEX idx_graph_edges_user   ON graph_edges(user_id);
CREATE INDEX idx_graph_edges_source ON graph_edges(source_node_id);
CREATE INDEX idx_graph_edges_target ON graph_edges(target_node_id);   -- (#160)

DROP TRIGGER IF EXISTS trg_graph_nodes_updated_at ON graph_nodes;
CREATE TRIGGER trg_graph_nodes_updated_at BEFORE UPDATE ON graph_nodes
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
