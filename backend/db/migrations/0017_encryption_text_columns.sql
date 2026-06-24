-- Migration: retype columns to TEXT for AES-256-GCM column-level encryption.
--
-- The encryption helpers in services/encryption.py emit base64 strings
-- (nonce || ciphertext_with_tag). NUMERIC and JSONB columns cannot store
-- those, so any encrypted write would fail at the Postgres layer.
--
-- Affected columns:
--   assignments.points_possible NUMERIC -> TEXT
--   assignments.points_earned   NUMERIC -> TEXT
--   documents.concept_notes     JSONB   -> TEXT
--   sessions.summary_json       JSONB   -> TEXT
--
-- Existing data is preserved by casting to TEXT in place (legacy plaintext
-- rows; the decrypt-fallback in services/encryption.py keeps reads working
-- until a backfill script re-encrypts every row).

ALTER TABLE assignments
  ALTER COLUMN points_possible TYPE TEXT USING points_possible::TEXT;

ALTER TABLE assignments
  ALTER COLUMN points_earned TYPE TEXT USING points_earned::TEXT;

ALTER TABLE documents
  ALTER COLUMN concept_notes TYPE TEXT USING concept_notes::TEXT;

ALTER TABLE sessions
  ALTER COLUMN summary_json TYPE TEXT USING summary_json::TEXT;
