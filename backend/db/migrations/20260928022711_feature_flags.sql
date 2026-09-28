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
