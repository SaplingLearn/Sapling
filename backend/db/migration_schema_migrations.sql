-- Migration: schema_migrations ledger (#197)
-- Run once in the Supabase SQL editor (idempotent).
--
-- Backs db/migrate.py: records which migrations have been applied so the runner
-- can apply pending ones in a deterministic order instead of relying on prose
-- ("Run once…", "needs documents first") scattered across migration headers.
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
