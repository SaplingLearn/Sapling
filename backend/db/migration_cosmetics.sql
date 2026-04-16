-- Migration: Cosmetics system
-- Creates cosmetics, role_cosmetics, user_cosmetics tables with seed data
-- Adds FK constraints to user_settings

CREATE TABLE IF NOT EXISTS cosmetics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type TEXT CHECK (type IN ('avatar_frame', 'banner', 'name_color', 'title')),
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    asset_url TEXT,
    css_value TEXT,
    rarity TEXT CHECK (rarity IN ('common', 'uncommon', 'rare', 'epic', 'legendary')),
    unlock_source TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS role_cosmetics (
    role_id UUID REFERENCES roles(id) ON DELETE CASCADE,
    cosmetic_id UUID REFERENCES cosmetics(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, cosmetic_id)
);

CREATE TABLE IF NOT EXISTS user_cosmetics (
    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    cosmetic_id UUID REFERENCES cosmetics(id) ON DELETE CASCADE,
    unlocked_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (user_id, cosmetic_id)
);

-- Seed default cosmetics
INSERT INTO cosmetics (type, name, slug, asset_url, css_value, rarity, unlock_source) VALUES
    ('avatar_frame', 'Default Frame', 'default_frame', NULL, NULL, 'common', 'default'),
    ('banner', 'Default Banner', 'default_banner', NULL, NULL, 'common', 'default'),
    ('title', 'Classic', 'classic_title', NULL, NULL, 'common', 'default')
ON CONFLICT (slug) DO NOTHING;

-- Add foreign key constraints to user_settings
ALTER TABLE user_settings
    ADD CONSTRAINT fk_user_settings_avatar_frame
    FOREIGN KEY (equipped_avatar_frame_id) REFERENCES cosmetics(id);

ALTER TABLE user_settings
    ADD CONSTRAINT fk_user_settings_banner
    FOREIGN KEY (equipped_banner_id) REFERENCES cosmetics(id);

ALTER TABLE user_settings
    ADD CONSTRAINT fk_user_settings_name_color
    FOREIGN KEY (equipped_name_color_id) REFERENCES cosmetics(id);

ALTER TABLE user_settings
    ADD CONSTRAINT fk_user_settings_title
    FOREIGN KEY (equipped_title_id) REFERENCES cosmetics(id);

ALTER TABLE user_settings
    ADD CONSTRAINT fk_user_settings_featured_role
    FOREIGN KEY (featured_role_id) REFERENCES roles(id);
