-- Idempotency support: documents.request_id stores the X-Request-ID
-- header from the upload request, deduping client retries.
ALTER TABLE documents
  ADD COLUMN IF NOT EXISTS request_id text;

CREATE UNIQUE INDEX IF NOT EXISTS documents_request_id_user_unique
  ON documents (user_id, request_id)
  WHERE request_id IS NOT NULL;

-- Manual run notes:
-- 1. Apply on staging first.
-- 2. Old rows have request_id=NULL; they're ignored by the unique index.
-- 3. Fresh uploads from the new code will populate request_id.
