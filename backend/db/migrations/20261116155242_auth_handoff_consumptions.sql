-- Single-use OAuth handoff tokens (sec2 M2: login CSRF / session fixation).
--
-- What this adds
-- --------------
-- public.auth_handoff_consumptions: one row per OAuth handoff token the
--   session BFF has exchanged for a session cookie, keyed by the SHA-256 (hex)
--   of the token's random `jti` claim. The app hashes the jti before it gets
--   here (services/auth/handoff.py); the raw jti, the token and the user id
--   are never stored. Service-only (RLS bucket E): RLS on, no policies,
--   nothing granted to anon or authenticated. Rows are ephemeral (a handoff
--   lives at most 600 s) and carry no content.
--
-- public.consume_auth_handoff(p_jti_hash, p_ttl_sec) -> boolean
--   One atomic statement: INSERT the jti hash, or take over a row whose
--   expiry has passed. TRUE the first time a jti is consumed, FALSE when an
--   unexpired row for it exists (a replay). The primary key serialises two
--   replicas exchanging the same handoff: exactly one gets TRUE. About 1% of
--   calls also delete up to 500 rows that expired over an hour ago (SKIP
--   LOCKED), so the table stays small. SECURITY INVOKER, search_path pinned
--   to '', EXECUTE for service_role only.
--
-- Callers: POST /api/auth/handoff/exchange (routes/auth.py), which fails
-- CLOSED (503) if this function is missing or unreachable: until it is
-- applied, the new session BFF cannot sign anyone in. Apply before deploying
-- the frontend.
--
-- Idempotent (IF NOT EXISTS / OR REPLACE / guarded DO blocks), additive,
-- touches no existing data. Not in the account wipe/bundle: transient
-- infrastructure, not study data, and keyed by no user.
--
-- Reverse (by hand, as the migration role; sign-in then fails closed):
--   DROP FUNCTION IF EXISTS public.consume_auth_handoff(text, integer);
--   DROP TABLE IF EXISTS public.auth_handoff_consumptions;

CREATE TABLE IF NOT EXISTS public.auth_handoff_consumptions (
    jti_hash    TEXT PRIMARY KEY,
    consumed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    expires_at  TIMESTAMPTZ NOT NULL,
    CONSTRAINT auth_handoff_consumptions_jti_hash_check
        CHECK (jti_hash ~ '^[0-9a-f]{64}$')
);

COMMENT ON TABLE public.auth_handoff_consumptions IS
    'OAuth handoff tokens already exchanged for a session (sec2 M2), by sha256(jti). Written only by consume_auth_handoff(). Service-only; ephemeral.';

CREATE INDEX IF NOT EXISTS auth_handoff_consumptions_expires_at_idx
    ON public.auth_handoff_consumptions (expires_at);

ALTER TABLE public.auth_handoff_consumptions ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION public.consume_auth_handoff(
    p_jti_hash TEXT,
    p_ttl_sec  INTEGER
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
    IF p_jti_hash IS NULL OR p_jti_hash !~ '^[0-9a-f]{64}$'
       OR p_ttl_sec IS NULL OR p_ttl_sec NOT BETWEEN 1 AND 3600 THEN
        RAISE EXCEPTION 'consume_auth_handoff: invalid arguments'
            USING ERRCODE = '22023';
    END IF;

    IF pg_catalog.random() < 0.01 THEN
        DELETE FROM public.auth_handoff_consumptions c
         WHERE c.jti_hash IN (
             SELECT o.jti_hash
               FROM public.auth_handoff_consumptions o
              WHERE o.expires_at < v_now - INTERVAL '1 hour'
              ORDER BY o.expires_at
              LIMIT 500
              FOR UPDATE SKIP LOCKED);
    END IF;

    INSERT INTO public.auth_handoff_consumptions AS c (jti_hash, consumed_at, expires_at)
    VALUES (p_jti_hash, v_now, v_now + pg_catalog.make_interval(secs => p_ttl_sec))
    ON CONFLICT (jti_hash) DO UPDATE
        SET consumed_at = EXCLUDED.consumed_at,
            expires_at  = EXCLUDED.expires_at
        WHERE c.expires_at <= v_now
    RETURNING c.jti_hash INTO v_got;

    RETURN v_got IS NOT NULL;
END;
$$;

COMMENT ON FUNCTION public.consume_auth_handoff(TEXT, INTEGER) IS
    'Consume an OAuth handoff jti (sec2 M2): TRUE the first time, FALSE on a replay.';

DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.auth_handoff_consumptions FROM %I', r);
            EXECUTE format(
                'REVOKE ALL ON FUNCTION public.consume_auth_handoff(text, integer) FROM %I', r);
        END IF;
    END LOOP;
    EXECUTE 'REVOKE ALL ON FUNCTION public.consume_auth_handoff(text, integer) FROM PUBLIC';
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        EXECUTE 'GRANT ALL ON TABLE public.auth_handoff_consumptions TO service_role';
        EXECUTE 'GRANT EXECUTE ON FUNCTION public.consume_auth_handoff(text, integer) TO service_role';
    END IF;
END $$;
