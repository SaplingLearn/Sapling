-- Migration: Notetaker tables (notes + note_concepts)
-- notes.title and notes.body are AES-GCM encrypted at the application layer
-- (services/encryption.py). tags is plaintext text[] so PostgREST array
-- filters work for tag-based search. last_summary is the cached output of
-- the most recent /summarize action; null until the user runs it.
--
-- note_concepts is a junction table linking notes <-> graph_nodes.
-- ON DELETE CASCADE on note_id ensures deleting a note cleans up its
-- links. The graph_node FK is intentionally NOT a hard FK because
-- graph_nodes uses TEXT ids managed by application code (no enforced FK
-- pattern elsewhere in this codebase — see graph_edges.source_node_id).

CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    title TEXT,
    body TEXT,
    tags TEXT[] NOT NULL DEFAULT '{}',
    last_summary TEXT,
    last_summary_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_notes_user_updated
    ON notes (user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_notes_user_course
    ON notes (user_id, course_id);

CREATE TABLE IF NOT EXISTS note_concepts (
    note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    concept_node_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (note_id, concept_node_id)
);

CREATE INDEX IF NOT EXISTS idx_note_concepts_concept
    ON note_concepts (concept_node_id);
