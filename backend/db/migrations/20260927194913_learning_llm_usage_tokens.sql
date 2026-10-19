-- 20260927194913_learning_llm_usage_tokens.sql
-- Learning loop series PKG-06b (spec §4, §13 A21): usage observability.
-- cached_tokens   = Gemini usage_metadata.cached_content_token_count (implicit-cache hits)
-- thinking_tokens = Gemini usage_metadata.thoughts_token_count (already inside completion_tokens)
-- Filled by agents/usage.py::record_agent_usage; NULL on rows written before this migration
-- and on usage shapes that carry no such field. Counts only; never content.
-- llm_usage already has user_id, provider and idx_llm_usage_user_created (0035).
ALTER TABLE llm_usage
  ADD COLUMN IF NOT EXISTS cached_tokens int,
  ADD COLUMN IF NOT EXISTS thinking_tokens int;
