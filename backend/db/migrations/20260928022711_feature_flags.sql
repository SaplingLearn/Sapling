-- #620 feature flags (ADR 0029). Flags are DECLARED in code
-- (backend/services/feature_flags.py::REGISTRY); these tables hold only their
-- configuration. Variant validity is enforced by the app, not the DB.
CREATE TABLE IF NOT EXISTS feature_flags (
    key              TEXT PRIMARY KEY CHECK (key ~ '^[a-z][a-z0-9_]{1,62}$'),
    default_variant  TEXT NOT NULL,
    rollout_percent  SMALLINT NOT NULL DEFAULT 0 CHECK (rollout_percent BETWEEN 0 AND 100),
    rollout_variant  TEXT,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by       TEXT REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS feature_flag_targets (
    flag_key     TEXT NOT NULL REFERENCES feature_flags(key) ON DELETE CASCADE,
    target_type  TEXT NOT NULL CHECK (target_type IN ('user', 'role')),
    target_id    TEXT NOT NULL,
    variant      TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by   TEXT REFERENCES users(id) ON DELETE SET NULL,
    PRIMARY KEY (flag_key, target_type, target_id)
);

-- PostHog analytics stays ON once keys are set; admins can switch it off.
INSERT INTO feature_flags (key, default_variant) VALUES ('product_analytics', 'on')
ON CONFLICT (key) DO NOTHING;

-- Backend-only. The backend reaches PostgREST with the service_role key
-- (db/connection.py: SUPABASE_SERVICE_KEY), but Supabase's default privileges
-- grant anon and authenticated full DML on every new public table, and the
-- frontend ships the anon key -- so without this, anyone holding it could flip
-- a flag or add themselves a rule. Guarded because those roles are Supabase's:
-- a plain Postgres has none of them, and an unguarded REVOKE naming one aborts
-- the whole migration. Same idiom as 20260921063714_document_index_status.sql.
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON feature_flags, feature_flag_targets FROM %I', r);
        END IF;
    END LOOP;
END $$;
