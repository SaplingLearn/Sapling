-- Source reference viewer: persist the raw upload instead of discarding it
-- after OCR extraction, so a PDF source can be rendered and circled in the
-- browser. See docs/superpowers/specs/2026-10-14-source-reference-viewer-design.md.
--
-- NULL for every document uploaded before this ships (the bytes are already
-- gone) and treated identically to "no original available" — there is
-- nothing to backfill.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS original_storage_path TEXT;

-- The object-storage bucket itself is a row in storage.buckets (the Storage
-- extension's own table, present in both local and hosted Supabase) —
-- creating it here means `python -m db.migrate` provisions it the same way
-- it provisions everything else, with no separate dashboard/CLI step.
-- `public = false`: every read goes through a signed URL
-- (routes/documents.py's new /original-url route), never a public link.
INSERT INTO storage.buckets (id, name, public)
VALUES ('document-originals', 'document-originals', false)
ON CONFLICT (id) DO NOTHING;
