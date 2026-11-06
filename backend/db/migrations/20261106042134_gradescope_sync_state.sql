-- #770 (state-machine audit L2): persist the Gradescope connection/sync outcome.
--
-- Before this, "connected" meant only "a gradescope_credentials row exists", and
-- the only recorded outcome was last_synced_at on success. An expired cookie
-- session kept reading as connected, and a failed sync left no trace.
--
--   needs_reauth     set when Gradescope rejects the STORED credentials (a sync
--                    or course listing got an auth failure); cleared by a fresh
--                    credential save or any later successful login. The status
--                    endpoint reports state='needs_reauth' while it is set.
--   last_attempt_at  when the last sync attempt finished (success or failure).
--   last_sync_error  stable machine code for the last sync attempt's failure,
--                    NULL when it succeeded. Codes only, never upstream text, so
--                    nothing user- or Gradescope-supplied lands in this column.
--
-- Additive and idempotent (IF NOT EXISTS / guarded constraint), so a replay from
-- empty and a re-run are both clean.

ALTER TABLE gradescope_credentials
    ADD COLUMN IF NOT EXISTS needs_reauth    BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS last_attempt_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_sync_error TEXT;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'gradescope_credentials_last_sync_error_chk'
  ) THEN
    ALTER TABLE gradescope_credentials
      ADD CONSTRAINT gradescope_credentials_last_sync_error_chk CHECK (
        last_sync_error IS NULL
        OR last_sync_error IN ('auth_failed', 'fetch_failed', 'write_failed', 'partial_write')
      );
  END IF;
END $$;
