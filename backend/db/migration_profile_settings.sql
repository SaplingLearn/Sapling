-- Migration: Profile & Settings
-- Adds profile fields to users and creates user_settings table

-- Add profile columns to users
ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT UNIQUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS bio TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS location TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS website TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

-- User settings table
CREATE TABLE IF NOT EXISTS user_settings (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    display_name TEXT,
    username TEXT,
    bio TEXT,
    location TEXT,
    website TEXT,
    profile_visibility TEXT DEFAULT 'public' CHECK (profile_visibility IN ('public', 'private')),
    activity_status_visible BOOL DEFAULT true,
    notification_email BOOL DEFAULT true,
    notification_push BOOL DEFAULT false,
    notification_in_app BOOL DEFAULT true,
    theme TEXT DEFAULT 'light' CHECK (theme IN ('light', 'dark')),
    font_size TEXT DEFAULT 'medium' CHECK (font_size IN ('small', 'medium', 'large')),
    accent_color TEXT,
    featured_role_id UUID,
    featured_achievement_ids TEXT[] DEFAULT '{}',
    equipped_avatar_frame_id UUID,
    equipped_banner_id UUID,
    equipped_name_color_id UUID,
    equipped_title_id UUID,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
