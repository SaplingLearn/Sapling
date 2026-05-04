-- Migration: Admin portal — audit log + last_sign_in tracking
-- Run once in Supabase SQL editor.

CREATE TABLE IF NOT EXISTS admin_audit_log (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id     TEXT NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    action       TEXT NOT NULL,           -- e.g. 'user.approve', 'role.assign'
    target_type  TEXT NOT NULL,           -- 'user' | 'role' | 'achievement' | 'cosmetic' | 'allowlist' | 'trigger' | 'role_cosmetic' | 'achievement_cosmetic'
    target_id    TEXT,                    -- nullable for actions without a single target
    payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_admin_audit_log_created_at
    ON admin_audit_log (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_admin_audit_log_actor
    ON admin_audit_log (actor_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_admin_audit_log_target
    ON admin_audit_log (target_type, target_id);

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS last_sign_in_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_users_created_at
    ON users (created_at DESC);
