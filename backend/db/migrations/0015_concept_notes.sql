-- Migration: Document concept notes
-- Adds a structured concept_notes column to the documents table and drops the
-- now-unused key_takeaways column.
--
-- concept_notes entry: { "name": "Concept Name", "description": "markdown body" }
-- Description supports KaTeX math, mermaid, function plots, and theorem/proof
-- callouts via the same MarkdownChat renderer used in the tutoring chat.
--
-- WARNING: dropping key_takeaways is destructive. Any existing data in that
-- column is lost. The flashcards column is intentionally kept — the flashcards
-- feature still uses it.

ALTER TABLE documents ADD COLUMN IF NOT EXISTS concept_notes JSONB;
ALTER TABLE documents DROP COLUMN IF EXISTS key_takeaways;

-- Per-node color override on graph_nodes (overrides the course color when set).
ALTER TABLE graph_nodes ADD COLUMN IF NOT EXISTS color TEXT;
