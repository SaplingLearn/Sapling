-- Preserve provider-specific usage details needed for cache-aware cost rollups.
ALTER TABLE llm_usage
    ADD COLUMN IF NOT EXISTS cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS thoughts_tokens INTEGER NOT NULL DEFAULT 0;
