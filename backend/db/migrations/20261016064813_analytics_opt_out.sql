-- user_settings.analytics_opt_out: the persisted PostHog opt-out (#677,
-- ADR 0028).
--
-- The PostHog seam (services/posthog_client.py: events, $ai_generation and
-- exceptions, all through one consent worker) sends nothing for a user whose
-- analytics_opt_out is true: services/analytics_consent.consent_for reads it
-- through a per-process TTL cache that PATCH /api/profile/{user_id}/settings
-- invalidates. The Settings → Data switch writes it. Do Not Track / Global
-- Privacy Control are honoured per request (the backend skips any request
-- carrying Sec-GPC: 1 or DNT: 1; the frontend never loads posthog-js) and are
-- deliberately NOT persisted here.
--
-- DEFAULT false = not opted out, preserving current behaviour; a missing
-- user_settings row is treated the same way. Our own events / llm_usage
-- tables are first-party observability and unaffected. Adding a column with
-- a constant default is metadata-only (no rewrite). Migrations run before the
-- code that reads the column is deployed (staging migrates on merge, prod in
-- `make promote` before the merge), so the code assumes it exists.
--
-- (This replaces the opt-out half of the never-applied, stack-consolidated
-- 20260927220057_llm_cost_precision_and_analytics_opt_out.sql; the cost half
-- shipped with #672 as 20261016063803_llm_cost_precision.sql.)

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS analytics_opt_out BOOLEAN NOT NULL DEFAULT false;
