-- ADR 0028: persisted third-party analytics (PostHog) opt-out.
--
-- The PostHog seam (services/posthog_client.py mirror, services/
-- ai_observability.py AI-span export) sends nothing for a user whose
-- analytics_opt_out is true: services/analytics_consent.consent_for reads it
-- through a per-process TTL cache that PATCH /api/profile/{user_id}/settings
-- invalidates. The settings toggle writes it; the frontend also sets it when
-- the browser sends Do Not Track / Global Privacy Control, and the backend
-- additionally skips any request carrying Sec-GPC: 1 or DNT: 1.
--
-- DEFAULT false = not opted out, preserving current behaviour; a missing
-- user_settings row is treated the same way (the column default). Our own
-- events / llm_usage tables are first-party observability and unaffected.
ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS analytics_opt_out BOOLEAN NOT NULL DEFAULT false;
