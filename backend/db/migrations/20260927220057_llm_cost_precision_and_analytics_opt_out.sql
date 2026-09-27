-- Two additive column changes for the PR stack #672 (Jev decision seam,
-- ADR 0027) + #677 (PostHog seam, ADR 0028), consolidated into one file
-- because the stack merges at once. Both statements are idempotent.

-- ── 1. llm_usage.cost_usd: enough scale to price a sub-micro-dollar call ────
--
-- 0035 made cost_usd NUMERIC(12,6): one-millionth of a dollar is the smallest
-- step it can store, and the decision seam's calls live at that scale:
--
--   TypeSafe Jev (#642, ADR 0027)   $0.042 / 1M input tokens, output free
--                                   = $0.000000042 per token
--     a 653-token decision            $0.000027426 -> stored 0.000027 (-1.6%)
--     a 312-token decision            $0.000013104 -> stored 0.000013 (-0.8%)
--     anything under 12 tokens        stored 0.000000 — a billed call as free
--   a short flash-lite decision     sub-micro-dollar input/output legs round
--                                   the same way
--
-- Per call the error is a rounding step; across the seam's volume (one call
-- per student chat turn, plus a shadow) it is a systematic bias in exactly
-- the Jev-vs-flash-lite cost comparison #642's shadow mode exists to make.
--
-- NUMERIC(18,10): ten fractional digits price a single Jev token exactly,
-- and eight integer digits hold any plausible per-call cost.
-- services/llm_pricing.py::cost_usd quantizes to the same scale (COST_SCALE)
-- so a written value is never re-rounded by the column.
--
-- Pure widening: every existing NUMERIC(12,6) value is representable, so the
-- USING cast is lossless. canopy_metrics() SUMs the column and ROUNDs to
-- integer cents (scale-agnostic), and the admin rollups round at the same
-- 10dp (routes/admin_analytics.py). No view depends on the column. The type
-- change rewrites llm_usage under a brief ACCESS EXCLUSIVE lock — a small
-- table. Code shipped before this runs just stores 6dp-rounded costs.

ALTER TABLE llm_usage
    ALTER COLUMN cost_usd TYPE NUMERIC(18,10) USING cost_usd::NUMERIC(18,10);

COMMENT ON COLUMN llm_usage.cost_usd IS
    'USD cost of the call at list price, 10dp (services/llm_pricing.cost_usd). '
    'NULL when the model is unpriced.';

-- ── 2. user_settings.analytics_opt_out: the persisted PostHog opt-out ──────
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
-- a constant default is metadata-only (no rewrite). Code shipped before this
-- runs tolerates the missing column (routes/profile.py::_select_settings) and
-- treats every user as DENIED until it lands.

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS analytics_opt_out BOOLEAN NOT NULL DEFAULT false;
