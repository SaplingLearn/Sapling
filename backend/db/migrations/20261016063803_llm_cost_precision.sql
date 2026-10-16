-- llm_usage.cost_usd: enough scale to price a sub-micro-dollar call (#672,
-- ADR 0027). Ships with the decision seam that needs it: llm_pricing.COST_SCALE
-- quantizes every computed cost to 10dp, so the column must hold 10dp.
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
-- table. Idempotent: re-running it on a 10dp column changes nothing.
--
-- (This replaces the cost half of the never-applied, stack-consolidated
-- 20260927220057_llm_cost_precision_and_analytics_opt_out.sql, split so each
-- PR ships its own schema change.)

ALTER TABLE llm_usage
    ALTER COLUMN cost_usd TYPE NUMERIC(18,10) USING cost_usd::NUMERIC(18,10);

COMMENT ON COLUMN llm_usage.cost_usd IS
    'USD cost of the call at list price, 10dp (services/llm_pricing.cost_usd). '
    'NULL when the model is unpriced.';
