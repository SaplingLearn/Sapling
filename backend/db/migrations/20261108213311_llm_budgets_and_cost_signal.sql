-- Per-user daily LLM token budget + the weekly LLM-cost-per-active-user signal
-- (Trov #119, docs/architecture-hardening-plan.md phase 5).
--
-- What this adds
-- --------------
-- public.llm_budgets: daily token budgets, configured from /api/admin/llm.
-- One row per (scope, subject):
--   ('default', '')        the budget everyone gets (seeded below)
--   ('role',    <slug>)    a role override, keyed on roles.slug
--   ('user',    <users.id>) a per-user override
-- daily_token_limit NULL = unlimited, 0 = no LLM work at all. Resolution, first
-- match wins: user row -> the MOST GENEROUS of the user's role rows (NULL beats
-- any number) -> default row -> none (unlimited). Service-only (RLS bucket E):
-- RLS on, no policies, nothing granted to anon / authenticated.
--
-- public.llm_budget_status(p_user_id) -> jsonb
--   {user_id, limit, source, used, window_start, reset_at}: the resolved limit
--   and today's (UTC) SUM(llm_usage.total_tokens) for the user, in ONE round
--   trip. `used` is an index range scan on llm_usage (user_id, created_at),
--   which 0035 already created as idx_llm_usage_user_created (restated below,
--   a no-op where it exists). services/llm_budget.py calls it before the first
--   model request of an agent run, only while the `llm_budget` flag is on.
--
-- public.llm_cost_per_active_user_weekly() -> jsonb
--   Weekly LLM cost per active user and the "2x jump" signal (plan Targets:
--   "LLM cost per MAU, weekly, alert on a 2x jump, source = agent usage
--   table"). Five rolling 7-day windows ending now (week 0 = the last 7 days,
--   weeks 1-4 the trailing four). Per window: usd = SUM(llm_usage.cost_usd)
--   over priced rows (cost_usd > 0, canopy_metrics' rule); active_users =
--   COUNT(DISTINCT events.user_id), non-empty id, category <> 'system' (the
--   definition routes/admin_analytics.py uses for distinct_active_users).
--   ratio = week 0 per-user cost / the mean of weeks 1-4's per-user cost (the
--   weeks that had active users); jump = ratio >= 2.0. Both NULL when either
--   side has no active users (no honest answer). Read by
--   GET /api/admin/analytics/llm/cost-per-active-user, and written so the
--   Canopy owner can add its keys to canopy_metrics() without re-deriving it
--   (this file deliberately does NOT touch canopy_metrics()).
--
-- Both functions: LANGUAGE sql STABLE, SECURITY INVOKER, search_path pinned
-- to '', EXECUTE for service_role only (llm_usage / events are service-only).
--
-- Inert until the `llm_budget` flag is turned on (services/feature_flags.py):
-- nothing reads llm_budgets or calls llm_budget_status before that. The cost
-- function is read only by an admin endpoint. Idempotent (IF NOT EXISTS / OR
-- REPLACE / ON CONFLICT DO NOTHING / guarded DO blocks), additive, and touches
-- no existing data.
--
-- Reverse (by hand, as the migration role). Turn `llm_budget` off first
-- (SAPLING_FLAG_LLM_BUDGET=off), so nothing calls the status function, then:
--   DROP FUNCTION IF EXISTS public.llm_cost_per_active_user_weekly();
--   DROP FUNCTION IF EXISTS public.llm_budget_status(text);
--   DROP TABLE IF EXISTS public.llm_budgets;   -- admin config only; no user data
-- Leave idx_llm_usage_user_created alone: 0035 owns it.

-- ── llm_budgets ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.llm_budgets (
    scope             TEXT NOT NULL,
    subject           TEXT NOT NULL DEFAULT '',
    daily_token_limit BIGINT,
    note              TEXT,
    updated_by        TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT llm_budgets_pkey PRIMARY KEY (scope, subject),
    CONSTRAINT llm_budgets_scope_check CHECK (scope IN ('default', 'role', 'user')),
    CONSTRAINT llm_budgets_subject_check CHECK ((scope = 'default') = (subject = '')),
    CONSTRAINT llm_budgets_limit_check CHECK (daily_token_limit IS NULL OR daily_token_limit >= 0)
);

COMMENT ON TABLE public.llm_budgets IS
    'Daily LLM token budgets (#119): default / role (roles.slug) / user (users.id). Enforced only while the llm_budget flag is on. Service-only.';
COMMENT ON COLUMN public.llm_budgets.daily_token_limit IS
    'Tokens (llm_usage.total_tokens) per UTC day. NULL = unlimited, 0 = none.';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
         WHERE tgname = 'trg_llm_budgets_updated_at'
           AND tgrelid = 'public.llm_budgets'::regclass
    ) THEN
        CREATE TRIGGER trg_llm_budgets_updated_at BEFORE UPDATE ON public.llm_budgets
            FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
    END IF;
END $$;

-- The global default: about 2M tokens a day. A Sonnet tutor turn with RAG
-- context and a tool loop runs ~10-40K tokens, a quiz ~20-30K, so this is a
-- runaway guard, not a study limit. Tune it from /api/admin/llm/budgets; a
-- re-run never overwrites a value an admin set.
INSERT INTO public.llm_budgets (scope, subject, daily_token_limit, note)
VALUES ('default', '', 2000000, 'Seeded by 20261108213311; edit via /api/admin/llm/budgets')
ON CONFLICT (scope, subject) DO NOTHING;

-- Already created by 0035 under this name; restated so this file states the
-- index llm_budget_status relies on.
CREATE INDEX IF NOT EXISTS idx_llm_usage_user_created ON public.llm_usage (user_id, created_at DESC);

-- ── access: service-only ────────────────────────────────────────────────────

ALTER TABLE public.llm_budgets ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.llm_budgets FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT ALL ON TABLE public.llm_budgets TO service_role;
    END IF;
END $$;

-- ── llm_budget_status ───────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.llm_budget_status(p_user_id TEXT)
RETURNS JSONB
LANGUAGE sql
STABLE
SET search_path = ''
AS $$
    WITH day AS (
        SELECT date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' AS start
    ),
    candidates AS (
        SELECT b.daily_token_limit, 'user'::text AS source, 1 AS rank
          FROM public.llm_budgets b
         WHERE b.scope = 'user' AND b.subject = p_user_id
        UNION ALL
        SELECT rp.daily_token_limit, rp.source, 2
          FROM (
            SELECT b.daily_token_limit, 'role:' || b.subject AS source
              FROM public.llm_budgets b
              JOIN public.roles r       ON r.slug = b.subject
              JOIN public.user_roles ur ON ur.role_id = r.id
             WHERE b.scope = 'role' AND ur.user_id = p_user_id
             ORDER BY b.daily_token_limit DESC NULLS FIRST, b.subject
             LIMIT 1
          ) rp
        UNION ALL
        SELECT b.daily_token_limit, 'default', 3
          FROM public.llm_budgets b
         WHERE b.scope = 'default'
    ),
    chosen AS (
        SELECT c.daily_token_limit, c.source FROM candidates c ORDER BY c.rank LIMIT 1
    ),
    used AS (
        SELECT COALESCE(SUM(u.total_tokens), 0)::bigint AS tokens
          FROM public.llm_usage u, day
         WHERE u.user_id = p_user_id
           AND u.created_at >= day.start
    )
    SELECT jsonb_build_object(
        'user_id',      p_user_id,
        'limit',        (SELECT daily_token_limit FROM chosen),
        'source',       COALESCE((SELECT source FROM chosen), 'none'),
        'used',         (SELECT tokens FROM used),
        'window_start', (SELECT start FROM day),
        'reset_at',     (SELECT start FROM day) + interval '1 day'
    );
$$;

-- ── llm_cost_per_active_user_weekly ─────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.llm_cost_per_active_user_weekly()
RETURNS JSONB
LANGUAGE sql
STABLE
SET search_path = ''
AS $$
    WITH weeks AS (
        SELECT w,
               now() - make_interval(days => 7 * (w + 1)) AS from_ts,
               now() - make_interval(days => 7 * w)       AS to_ts
          FROM generate_series(0, 4) AS w
    ),
    cost AS (
        SELECT wk.w,
               COALESCE(SUM(u.cost_usd) FILTER (WHERE u.cost_usd > 0), 0)::numeric AS usd
          FROM weeks wk
          LEFT JOIN public.llm_usage u
                 ON u.created_at >= wk.from_ts AND u.created_at < wk.to_ts
         GROUP BY wk.w
    ),
    active AS (
        SELECT wk.w, COUNT(DISTINCT e.user_id) AS users
          FROM weeks wk
          LEFT JOIN public.events e
                 ON e.created_at >= wk.from_ts AND e.created_at < wk.to_ts
                AND e.user_id IS NOT NULL AND e.user_id <> ''
                AND e.category <> 'system'
         GROUP BY wk.w
    ),
    per AS (
        SELECT wk.w, wk.from_ts, wk.to_ts, c.usd, a.users,
               c.usd / NULLIF(a.users, 0) AS per_user
          FROM weeks wk
          JOIN cost c   ON c.w = wk.w
          JOIN active a ON a.w = wk.w
    ),
    cur AS (
        SELECT p.per_user FROM per p WHERE p.w = 0
    ),
    base AS (
        SELECT AVG(p.per_user) AS per_user, COUNT(p.per_user) AS weeks
          FROM per p
         WHERE p.w BETWEEN 1 AND 4
    )
    SELECT jsonb_build_object(
        'as_of',                        now(),
        'threshold',                    2.0,
        'usd_per_active_user_7d',       round(cur.per_user, 6),
        'baseline_usd_per_active_user', round(base.per_user, 6),
        'baseline_weeks',               base.weeks,
        'ratio',                        round(cur.per_user / NULLIF(base.per_user, 0), 4),
        'jump',                         CASE
                                            WHEN cur.per_user IS NULL OR NULLIF(base.per_user, 0) IS NULL
                                            THEN NULL
                                            ELSE cur.per_user >= 2.0 * base.per_user
                                        END,
        'weeks', (
            SELECT jsonb_agg(jsonb_build_object(
                       'week',                p.w,
                       'from',                p.from_ts,
                       'to',                  p.to_ts,
                       'usd',                 round(p.usd, 6),
                       'active_users',        p.users,
                       'usd_per_active_user', round(p.per_user, 6)
                   ) ORDER BY p.w)
              FROM per p
        )
    )
      FROM cur, base;
$$;

-- ── function privileges: service_role only ──────────────────────────────────

DO $$
DECLARE
    fn TEXT;
    r  TEXT;
BEGIN
    FOREACH fn IN ARRAY ARRAY[
        'public.llm_budget_status(text)',
        'public.llm_cost_per_active_user_weekly()'
    ] LOOP
        EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', fn);
        FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                EXECUTE format('REVOKE ALL ON FUNCTION %s FROM %I', fn, r);
            END IF;
        END LOOP;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
            EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role', fn);
        END IF;
    END LOOP;
END $$;
