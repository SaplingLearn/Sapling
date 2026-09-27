-- ── llm_usage.cost_usd: enough scale to price a sub-micro-dollar call ───────
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
-- the Jev-vs-flash-lite cost comparison #642's shadow mode exists to make,
-- and cost_usd() already computes the exact figure only to throw it away.
--
-- NUMERIC(18,10): ten fractional digits price a single Jev token
-- ($0.000000042) exactly, and eight integer digits hold any plausible
-- per-call cost. services/llm_pricing.py::cost_usd quantizes to the same
-- scale (COST_SCALE) so a written value is never re-rounded by the column.
--
-- Pure widening: every existing NUMERIC(12,6) value is representable, so the
-- USING cast is lossless. Consumers are unaffected by the type change:
-- canopy_metrics() SUMs the column and ROUNDs the dollars to integer cents
-- (scale-agnostic numeric math — cents stay a LOWER bound where a model is
-- unpriced, exactly as before), and the admin rollups read it as a float
-- and now round at the same 10dp (routes/admin_analytics.py).
-- No view depends on the column. Idempotent: re-running re-applies the same
-- type.

ALTER TABLE llm_usage
    ALTER COLUMN cost_usd TYPE NUMERIC(18,10) USING cost_usd::NUMERIC(18,10);

COMMENT ON COLUMN llm_usage.cost_usd IS
    'USD cost of the call at list price, 10dp (services/llm_pricing.cost_usd). '
    'NULL when the model is unpriced.';
