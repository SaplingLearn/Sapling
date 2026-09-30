-- Learning loop series PKG-14 half B (owner decision 2026-09-29, spec §13 A89):
-- the loop session an llm_usage row's run belonged to, when the run site knew it
-- (agents/usage.py::record_agent_usage(session_id=…)). scripts/derive_zpd_metrics.py
-- costs a row per session from this column first and falls back to the A82 event
-- join, then to per user-day, for rows that carry no session (every row written
-- before this migration, and runs with no session: course-asset drafting, the
-- post-test grade, non-tutor features). An id only — never content.
-- Additive and nullable: no default, no backfill, no index (the report reads a
-- created_at window through idx_llm_usage_user_created, 0035). llm_usage's RLS
-- and grants are table-level (0035) and cover the new column unchanged. A deploy
-- that reaches a database before this migration drops the column from its
-- inserts and retries (services/events_service.py), so no usage row is lost.
ALTER TABLE llm_usage
  ADD COLUMN IF NOT EXISTS session_id text;

-- PostgREST serves the new column from its schema cache; reload it (a no-op with
-- no listener).
NOTIFY pgrst, 'reload schema';
