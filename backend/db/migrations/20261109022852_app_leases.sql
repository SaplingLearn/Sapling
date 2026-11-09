-- Stateless per-replica state, part 2 (Trov #117, wave 3): one small lease
-- primitive so the per-process locks hold across API replicas.
--
-- What this adds
-- --------------
-- public.app_leases: one row per held (or recently held) lease, keyed by an
--   app-chosen key such as 'account_op:<user id>', 'study_guide:<sha256>' or
--   'oauth_nonce:<sha256 of the nonce>'. A key derived from secret or user
--   data is HASHED by the app before it gets here (services/pg_lease.py); a raw
--   OAuth nonce is never stored. `holder` is an opaque per-acquisition token
--   (host:pid:random). Service-only (RLS bucket E): RLS on, no policies,
--   nothing granted to anon or authenticated. Rows are ephemeral and carry no
--   content.
--
-- public.claim_lease(p_key, p_holder, p_ttl_sec) -> boolean
--   One atomic statement: INSERT the lease, or take the existing row over when
--   it has EXPIRED or is already this holder's (a renewal: the expiry moves
--   out, `acquired_at` stays). TRUE when p_holder holds the key afterwards,
--   FALSE when another holder's unexpired lease is in the way. The conflict
--   takes the row lock, so two replicas can never both get TRUE for one key.
--   About 1% of claims also delete up to 500 rows (any key) that expired
--   over an hour ago, skipping rows another pruner holds, so keys nobody
--   claims again (one per consumed OAuth nonce) do not accumulate.
--
-- public.renew_lease(p_key, p_holder, p_ttl_sec) -> boolean
--   The renewal a held lease's body runs every ttl/3: moves `expires_at` out
--   ONLY on an existing row p_holder still holds. Never inserts, so a renewal
--   that lands after its own release (or after another holder took an expired
--   lease over) cannot bring the lease back. TRUE when the row was extended.
--
-- public.release_lease(p_key, p_holder) -> boolean
--   Deletes the lease only when p_holder still holds it (a lease that expired
--   and was taken over is left to its new holder). TRUE when a row went.
--
-- All three SECURITY INVOKER with search_path pinned to '', EXECUTE for
-- service_role only.
--
-- Inert until used: nothing calls these until the `stateless_locks` flag
-- (default off) is turned on. Idempotent (IF NOT EXISTS / OR REPLACE /
-- guarded DO blocks), additive, touches no existing data.
--
-- Not in the account wipe/bundle: a lease is transient infrastructure, not
-- study data. A per-user key (account_op:<id>) lives at most its TTL.
--
-- Reverse (by hand, as the migration role). Turn `stateless_locks` off first;
-- the app falls back to its in-process locks on its own if these disappear.
--   DROP FUNCTION IF EXISTS public.release_lease(text, text);
--   DROP FUNCTION IF EXISTS public.renew_lease(text, text, integer);
--   DROP FUNCTION IF EXISTS public.claim_lease(text, text, integer);
--   DROP TABLE IF EXISTS public.app_leases;
-- (The table is brand new and holds only ephemeral leases.)

CREATE TABLE IF NOT EXISTS public.app_leases (
    key         TEXT PRIMARY KEY,
    holder      TEXT NOT NULL,
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    expires_at  TIMESTAMPTZ NOT NULL,
    CONSTRAINT app_leases_key_check CHECK (length(key) BETWEEN 1 AND 300),
    CONSTRAINT app_leases_holder_check CHECK (length(holder) BETWEEN 1 AND 200)
);

COMMENT ON TABLE public.app_leases IS
    'Cross-replica leases (#117 stateless_locks), written only by claim_lease()/renew_lease()/release_lease(). Service-only; ephemeral.';

-- The opportunistic prune of long-expired keys.
CREATE INDEX IF NOT EXISTS app_leases_expires_at_idx
    ON public.app_leases (expires_at);

ALTER TABLE public.app_leases ENABLE ROW LEVEL SECURITY;

-- ── claim_lease ─────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.claim_lease(
    p_key     TEXT,
    p_holder  TEXT,
    p_ttl_sec INTEGER
)
RETURNS BOOLEAN
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = ''
AS $$
DECLARE
    v_now TIMESTAMPTZ := clock_timestamp();
    v_got TEXT;
BEGIN
    IF p_key IS NULL OR length(p_key) NOT BETWEEN 1 AND 300
       OR p_holder IS NULL OR length(p_holder) NOT BETWEEN 1 AND 200
       OR p_ttl_sec IS NULL OR p_ttl_sec NOT BETWEEN 1 AND 86400 THEN
        RAISE EXCEPTION 'claim_lease: invalid arguments'
            USING ERRCODE = '22023';
    END IF;

    -- Housekeeping: about 1 claim in 100 drops at most 500 leases that
    -- expired over an hour ago (any key). SKIP LOCKED: two pruning claims
    -- never wait on each other, and a row a claim is taking over is skipped.
    IF pg_catalog.random() < 0.01 THEN
        DELETE FROM public.app_leases l
         WHERE l.key IN (
             SELECT o.key
               FROM public.app_leases o
              WHERE o.expires_at < v_now - INTERVAL '1 hour'
              ORDER BY o.expires_at
              LIMIT 500
              FOR UPDATE SKIP LOCKED);
    END IF;

    INSERT INTO public.app_leases AS l (key, holder, acquired_at, expires_at)
    VALUES (p_key, p_holder, v_now,
            v_now + pg_catalog.make_interval(secs => p_ttl_sec))
    ON CONFLICT (key) DO UPDATE
        SET holder      = EXCLUDED.holder,
            acquired_at = CASE WHEN l.holder = EXCLUDED.holder
                               THEN l.acquired_at ELSE EXCLUDED.acquired_at END,
            expires_at  = EXCLUDED.expires_at
        WHERE l.holder = EXCLUDED.holder OR l.expires_at <= v_now
    RETURNING l.holder INTO v_got;

    RETURN v_got IS NOT NULL;
END;
$$;

COMMENT ON FUNCTION public.claim_lease(TEXT, TEXT, INTEGER) IS
    'Atomic lease claim/renewal (#117): TRUE when p_holder holds p_key for p_ttl_sec more seconds.';

-- ── renew_lease ─────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.renew_lease(
    p_key     TEXT,
    p_holder  TEXT,
    p_ttl_sec INTEGER
)
RETURNS BOOLEAN
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = ''
AS $$
BEGIN
    IF p_key IS NULL OR length(p_key) NOT BETWEEN 1 AND 300
       OR p_holder IS NULL OR length(p_holder) NOT BETWEEN 1 AND 200
       OR p_ttl_sec IS NULL OR p_ttl_sec NOT BETWEEN 1 AND 86400 THEN
        RAISE EXCEPTION 'renew_lease: invalid arguments'
            USING ERRCODE = '22023';
    END IF;

    UPDATE public.app_leases l
       SET expires_at = clock_timestamp() + pg_catalog.make_interval(secs => p_ttl_sec)
     WHERE l.key = p_key AND l.holder = p_holder;
    RETURN FOUND;
END;
$$;

COMMENT ON FUNCTION public.renew_lease(TEXT, TEXT, INTEGER) IS
    'Extend a lease p_holder still holds (#117); never recreates a released or taken-over one.';

-- ── release_lease ───────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.release_lease(
    p_key    TEXT,
    p_holder TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = ''
AS $$
BEGIN
    DELETE FROM public.app_leases l
     WHERE l.key = p_key AND l.holder = p_holder;
    RETURN FOUND;
END;
$$;

COMMENT ON FUNCTION public.release_lease(TEXT, TEXT) IS
    'Drop a lease only while p_holder still holds it (#117).';

-- ── access: service-only ────────────────────────────────────────────────────

DO $$
DECLARE
    fn TEXT;
    r  TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.app_leases FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        EXECUTE 'GRANT ALL ON TABLE public.app_leases TO service_role';
    END IF;

    FOREACH fn IN ARRAY ARRAY[
        'public.claim_lease(text, text, integer)',
        'public.renew_lease(text, text, integer)',
        'public.release_lease(text, text)'
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
