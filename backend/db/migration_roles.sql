-- Migration: Roles system
-- Creates roles and user_roles tables with seed data

CREATE TABLE IF NOT EXISTS roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    color TEXT NOT NULL,
    icon TEXT,
    description TEXT,
    is_staff_assigned BOOL DEFAULT true,
    is_earnable BOOL DEFAULT false,
    display_priority INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_roles (
    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    role_id UUID REFERENCES roles(id) ON DELETE CASCADE,
    granted_at TIMESTAMPTZ DEFAULT now(),
    granted_by TEXT,
    PRIMARY KEY (user_id, role_id)
);

CREATE INDEX IF NOT EXISTS idx_user_roles_user_id ON user_roles(user_id);

-- Seed roles
INSERT INTO roles (name, slug, color, icon, description, is_staff_assigned, is_earnable, display_priority) VALUES
    ('Early Adopter', 'early-adopter', '#e8a33a', NULL, 'Joined during the closed alpha', false, true, 10),
    ('Moderator', 'moderator', '#3b82f6', NULL, 'Community moderator', true, false, 80),
    ('Admin', 'admin', '#dc2626', NULL, 'Platform administrator', true, false, 100),
    ('Verified', 'verified', '#22c55e', NULL, 'Verified student account', true, false, 50),
    ('VIP', 'vip', '#8b5cf6', NULL, 'VIP member', true, false, 60)
ON CONFLICT (slug) DO NOTHING;
