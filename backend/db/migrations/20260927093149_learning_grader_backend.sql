-- Learning loop PKG-05 (reopens PKG-03; spec §4, §13 A22): which backend
-- produced an evidence verdict. Plaintext enum; written only on evidence rows
-- by apply_graph_update, null on every legacy journal row.
ALTER TABLE node_mastery_events ADD COLUMN IF NOT EXISTS grader_backend text
  CHECK (grader_backend IS NULL OR grader_backend IN ('deterministic','gemini','gemini_second','jev'));
