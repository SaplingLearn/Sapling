-- Stateless per-replica state, part 1 (Trov #117, docs/design/async-db-client.md §5):
-- a Postgres-backed rate limiter and a version stamp for the feature-flag cache.
--
-- What this adds
-- --------------
-- public.rate_limit_hits: one row per call a rate limit let through, keyed by
--   the limiter's key (e.g. 'quiz_generate:<user_id>', 'ocr:<user_id>').
--   Service-only (RLS bucket E in docs/security/rls-step2-plan.md): RLS on, no
--   policies, nothing granted to anon or authenticated. Rows are ephemeral and
--   carry no content: a key and a timestamp.
--
-- public.claim_rate_limit(p_key, p_limit, p_window_sec)
--     -> TABLE (hit_id bigint, retry_after integer)
--   The sliding-window limiter services/request_limits.py runs when the
--   `stateless_rate_limit` flag is on. One atomic call: takes a transaction
--   advisory lock on the key (so concurrent claims for one key serialize and
--   two replicas cannot both admit the last slot), drops the key's hits that
--   have left the window, counts the rest, and either records a new hit and
--   returns its id (the refund handle: the app deletes exactly that row when
--   the work it guarded fails) or returns NULL plus the seconds until the
--   oldest hit in the window ages out (clamped to [1, p_window_sec], the same
--   answer the in-memory limiter gives). About 1% of claims also prune up to
--   500 hits (any key) older than a day (the longest window the function
--   accepts), so keys nobody uses again do not accumulate; that bounded
--   prune runs before the key's advisory lock is taken and skips rows
--   another pruner holds. SECURITY INVOKER, search_path pinned to '',
--   EXECUTE for service_role only.
--
-- public.feature_flags_version: one row whose `version` a statement-level
--   trigger on feature_flags and feature_flag_targets bumps on every write
--   (insert, update, delete), however it was made (the admin API or hand-run
--   SQL). Not on TRUNCATE: emptying the flag store is a reset, not an edit
--   (only test/E2E resets do it, and those run with the snapshot TTL at 0),
--   the replicas still converge within the snapshot TTL, and the statement
--   would trip promotion's destructive-DDL preflight. The bump is an
--   upsert, so a deleted/truncated version row is re-created by the next
--   flag write (at the current epoch-ms, so it still differs from any
--   version a replica holds) rather than silently stuck absent. services/feature_flags.py reads it every few seconds while
--   requests flow and drops its 30 s snapshot when it moves, so an admin flag
--   write reaches every replica within that interval instead of the snapshot
--   TTL. Service-only like the flag store itself.
--
-- Inert until used: nothing reads or writes rate_limit_hits until the
-- `stateless_rate_limit` flag (default off) is turned on. The version trigger
-- only touches its own one-row table; a backend that predates this file never
-- reads it.
--
-- Idempotent (IF NOT EXISTS / OR REPLACE / guarded DO blocks), additive, and
-- touches no existing data.
--
-- Reverse (by hand, as the migration role). Turn `stateless_rate_limit` off
-- first so nothing claims meanwhile; the app falls back to its per-process
-- limiter and to the snapshot TTL on its own if these objects disappear.
--   DROP TRIGGER IF EXISTS trg_feature_flags_bump_version ON public.feature_flags;
--   DROP TRIGGER IF EXISTS trg_feature_flag_targets_bump_version ON public.feature_flag_targets;
--   DROP FUNCTION IF EXISTS public.bump_feature_flags_version();
--   DROP TABLE IF EXISTS public.feature_flags_version;
--   DROP FUNCTION IF EXISTS public.claim_rate_limit(text, integer, integer);
--   DROP TABLE IF EXISTS public.rate_limit_hits;
-- (Both tables are brand new and hold only ephemeral counters.)

-- ── rate_limit_hits ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.rate_limit_hits (
    id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key    TEXT NOT NULL,
    hit_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT rate_limit_hits_key_check CHECK (length(key) BETWEEN 1 AND 300)
);

COMMENT ON TABLE public.rate_limit_hits IS
    'Sliding-window rate-limit hits (#117), written only by claim_rate_limit(). Service-only; ephemeral.';

-- The per-key window count and its prune.
CREATE INDEX IF NOT EXISTS rate_limit_hits_key_hit_at_idx
    ON public.rate_limit_hits (key, hit_at);
-- The global prune of stale keys.
CREATE INDEX IF NOT EXISTS rate_limit_hits_hit_at_idx
    ON public.rate_limit_hits (hit_at);

ALTER TABLE public.rate_limit_hits ENABLE ROW LEVEL SECURITY;

-- ── claim_rate_limit ────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.claim_rate_limit(
    p_key        TEXT,
    p_limit      INTEGER,
    p_window_sec INTEGER
)
RETURNS TABLE (hit_id BIGINT, retry_after INTEGER)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = ''
AS $$
DECLARE
    v_now    TIMESTAMPTZ := clock_timestamp();
    v_since  TIMESTAMPTZ;
    v_count  INTEGER;
    v_oldest TIMESTAMPTZ;
    v_id     BIGINT;
BEGIN
    IF p_key IS NULL OR length(p_key) NOT BETWEEN 1 AND 300
       OR p_limit IS NULL OR p_limit < 1
       OR p_window_sec IS NULL OR p_window_sec NOT BETWEEN 1 AND 86400 THEN
        RAISE EXCEPTION 'claim_rate_limit: invalid arguments'
            USING ERRCODE = '22023';
    END IF;

    -- Housekeeping for keys nobody claims again (a day is the longest window):
    -- about 1 claim in 100 deletes at most 500 day-old hits of ANY key. It
    -- runs BEFORE the key's advisory lock is taken, so it never lengthens
    -- the time another claim on this key waits, and SKIP LOCKED means two
    -- pruning claims never wait on each other's rows.
    IF pg_catalog.random() < 0.01 THEN
        DELETE FROM public.rate_limit_hits h
         WHERE h.id IN (
             SELECT o.id
               FROM public.rate_limit_hits o
              WHERE o.hit_at < v_now - INTERVAL '1 day'
              ORDER BY o.hit_at
              LIMIT 500
              FOR UPDATE SKIP LOCKED);
    END IF;

    -- One claim per key at a time, across every replica, until commit.
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended('rate_limit:' || p_key, 0));

    v_since := v_now - pg_catalog.make_interval(secs => p_window_sec);

    DELETE FROM public.rate_limit_hits h
     WHERE h.key = p_key AND h.hit_at <= v_since;

    SELECT count(*)::INTEGER, min(h.hit_at)
      INTO v_count, v_oldest
      FROM public.rate_limit_hits h
     WHERE h.key = p_key AND h.hit_at > v_since;

    IF v_count >= p_limit THEN
        hit_id := NULL;
        retry_after := LEAST(
            p_window_sec,
            GREATEST(1, CEIL(p_window_sec - EXTRACT(EPOCH FROM (v_now - v_oldest)))::INTEGER)
        );
        RETURN NEXT;
        RETURN;
    END IF;

    INSERT INTO public.rate_limit_hits (key, hit_at)
    VALUES (p_key, v_now)
    RETURNING id INTO v_id;

    hit_id := v_id;
    retry_after := NULL;
    RETURN NEXT;
END;
$$;

COMMENT ON FUNCTION public.claim_rate_limit(TEXT, INTEGER, INTEGER) IS
    'Atomic sliding-window rate-limit claim (#117): (hit_id, NULL) when admitted, (NULL, retry_after_seconds) when not.';

-- ── feature_flags_version ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.feature_flags_version (
    id         BOOLEAN PRIMARY KEY DEFAULT TRUE,
    version    BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT feature_flags_version_single_row CHECK (id)
);

COMMENT ON TABLE public.feature_flags_version IS
    'One row; bumped by a trigger on every feature_flags / feature_flag_targets write so each replica drops its flag snapshot (#117). Service-only.';

INSERT INTO public.feature_flags_version (id, version)
VALUES (TRUE, 0)
ON CONFLICT (id) DO NOTHING;

ALTER TABLE public.feature_flags_version ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION public.bump_feature_flags_version()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $$
BEGIN
    -- Self-healing: if the one row is gone (deleted or truncated by hand, or
    -- a test reset), the next flag write re-creates it instead of bumping
    -- nothing. Readers treat a missing row as "unknown" (TTL only) until then.
    -- The re-created version is the current epoch in milliseconds, not 1: a
    -- replica that last saw the old row at, say, 1 must still see it move.
    INSERT INTO public.feature_flags_version AS v (id, version, updated_at)
    VALUES (TRUE, (extract(epoch FROM clock_timestamp()) * 1000)::bigint, now())
    ON CONFLICT (id) DO UPDATE
        SET version = v.version + 1, updated_at = now();
    RETURN NULL;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
         WHERE tgname = 'trg_feature_flags_bump_version'
           AND tgrelid = 'public.feature_flags'::regclass
    ) THEN
        CREATE TRIGGER trg_feature_flags_bump_version
            AFTER INSERT OR UPDATE OR DELETE ON public.feature_flags
            FOR EACH STATEMENT EXECUTE FUNCTION public.bump_feature_flags_version();
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
         WHERE tgname = 'trg_feature_flag_targets_bump_version'
           AND tgrelid = 'public.feature_flag_targets'::regclass
    ) THEN
        CREATE TRIGGER trg_feature_flag_targets_bump_version
            AFTER INSERT OR UPDATE OR DELETE ON public.feature_flag_targets
            FOR EACH STATEMENT EXECUTE FUNCTION public.bump_feature_flags_version();
    END IF;
END $$;

-- ── access: service-only ────────────────────────────────────────────────────

DO $$
DECLARE
    t  TEXT;
    fn TEXT;
    r  TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['public.rate_limit_hits', 'public.feature_flags_version'] LOOP
        FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                EXECUTE format('REVOKE ALL ON TABLE %s FROM %I', t, r);
            END IF;
        END LOOP;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
            EXECUTE format('GRANT ALL ON TABLE %s TO service_role', t);
        END IF;
    END LOOP;

    FOREACH fn IN ARRAY ARRAY[
        'public.claim_rate_limit(text, integer, integer)',
        'public.bump_feature_flags_version()'
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
