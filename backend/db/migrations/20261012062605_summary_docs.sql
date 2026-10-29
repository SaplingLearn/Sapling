-- Library summary editor revamp: replaces documents.summary (a static,
-- regenerate-only TEXT column) with an editable rich-text doc per upload.
-- See docs/superpowers/specs/2026-10-11-library-summary-editor-design.md.
--
-- content columns are JSONB holding a TipTap/ProseMirror document, encrypted
-- the same way study_guides.content is: encrypt_json() produces a base64
-- string, which Postgres accepts into a jsonb column as a JSON string
-- scalar. decrypt_json() reverses it at the read boundary. This is a brand
-- new table (no legacy plaintext rows), so there is no decrypt_json_column
-- fallback needed here — every row is ciphertext from its first insert.

CREATE TABLE IF NOT EXISTS summary_docs (
    id                  TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    owner_user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- The document whose upload created this summary doc. Hard-deleting
    -- this row (routes/documents.py's delete cascade, Task 18) is how a
    -- document's summary doc goes away together with it — the app itself
    -- only ever soft-deletes `documents`, so this FK alone never fires on
    -- the app's normal delete path, but it keeps the two tables honest if
    -- a document row is ever hard-deleted some other way.
    primary_document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    content             JSONB NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_summary_docs_owner ON summary_docs(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_summary_docs_primary_document ON summary_docs(primary_document_id);

-- Join table: which documents contribute to a summary doc's context. The
-- primary document always has a row here too (inserted alongside
-- summary_docs itself) — it is just not removable from the UI.
CREATE TABLE IF NOT EXISTS summary_doc_sources (
    summary_doc_id TEXT NOT NULL REFERENCES summary_docs(id) ON DELETE CASCADE,
    document_id    TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    added_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (summary_doc_id, document_id)
);

CREATE INDEX IF NOT EXISTS idx_summary_doc_sources_document ON summary_doc_sources(document_id);

-- Append-only restore points (same shape as node_mastery_events: never
-- updated or deleted, just appended to). 'autosave' is deliberately absent
-- from the trigger enum — see the plan header's "Deviation" note.
CREATE TABLE IF NOT EXISTS summary_doc_versions (
    id             TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    summary_doc_id TEXT NOT NULL REFERENCES summary_docs(id) ON DELETE CASCADE,
    content        JSONB NOT NULL,
    trigger        TEXT NOT NULL CHECK (trigger IN (
                       'initial', 'ai_edit_kept', 'source_added',
                       'source_removed', 'restored'
                   )),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_summary_doc_versions_doc ON summary_doc_versions(summary_doc_id, created_at DESC);

-- Pending/resolved AI "ask" requests. anchor_from/anchor_to are ProseMirror
-- document positions; both NULL means a whole-doc ask (nothing highlighted).
-- instruction/original_text/proposed_text are encrypted the same way
-- notes.body is (encrypt_if_present/decrypt_if_present — plain TEXT
-- ciphertext, not the JSONB wrapper content uses).
CREATE TABLE IF NOT EXISTS summary_doc_suggestions (
    id             TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    summary_doc_id TEXT NOT NULL REFERENCES summary_docs(id) ON DELETE CASCADE,
    anchor_from    INTEGER,
    anchor_to      INTEGER,
    instruction    TEXT NOT NULL,
    original_text  TEXT,
    proposed_text  TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'kept', 'undone')),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at    TIMESTAMPTZ,
    CONSTRAINT summary_doc_suggestions_anchor_pair CHECK (
        (anchor_from IS NULL) = (anchor_to IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_summary_doc_suggestions_doc ON summary_doc_suggestions(summary_doc_id, status);

-- Global output-style preference (concise bullets vs. full prose). Lives on
-- the existing user_settings table, not a new one — see the spec's
-- "Customization" section on why this stays a single global default rather
-- than a per-document override.
ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS summary_style TEXT NOT NULL DEFAULT 'concise' CHECK (summary_style IN ('concise', 'detailed'));
