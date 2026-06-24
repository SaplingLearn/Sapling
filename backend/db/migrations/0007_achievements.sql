-- Migration: Achievements system
-- Creates achievements, triggers, user_achievements, and achievement_cosmetics tables

CREATE TABLE IF NOT EXISTS achievements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    description TEXT,
    icon TEXT,
    category TEXT CHECK (category IN ('activity', 'social', 'milestone', 'special')),
    rarity TEXT CHECK (rarity IN ('common', 'uncommon', 'rare', 'epic', 'legendary')),
    is_secret BOOL DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS achievement_triggers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    achievement_id UUID REFERENCES achievements(id) ON DELETE CASCADE,
    trigger_type TEXT NOT NULL,
    trigger_threshold INT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_achievements (
    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    achievement_id UUID REFERENCES achievements(id) ON DELETE CASCADE,
    earned_at TIMESTAMPTZ DEFAULT now(),
    is_featured BOOL DEFAULT false,
    PRIMARY KEY (user_id, achievement_id)
);

CREATE TABLE IF NOT EXISTS achievement_cosmetics (
    achievement_id UUID REFERENCES achievements(id) ON DELETE CASCADE,
    cosmetic_id UUID,
    PRIMARY KEY (achievement_id, cosmetic_id)
);

-- Seed achievements
INSERT INTO achievements (name, slug, description, icon, category, rarity, is_secret) VALUES
    ('First Steps', 'first_login', 'Log in for the first time', NULL, 'milestone', 'common', false),
    ('Week Warrior', 'streak_7', 'Maintain a 7-day study streak', NULL, 'activity', 'uncommon', false),
    ('Monthly Master', 'streak_30', 'Maintain a 30-day study streak', NULL, 'activity', 'rare', false),
    ('Document Collector', 'documents_5', 'Upload 5 documents', NULL, 'milestone', 'common', false),
    ('Library Builder', 'documents_25', 'Upload 25 documents', NULL, 'milestone', 'uncommon', false),
    ('Quiz Enthusiast', 'quizzes_10', 'Complete 10 quizzes', NULL, 'activity', 'uncommon', false),
    ('Flashcard Fanatic', 'flashcards_50', 'Create 50 flashcards', NULL, 'activity', 'rare', false),
    ('Social Butterfly', 'rooms_joined_10', 'Join 10 study rooms', NULL, 'social', 'uncommon', false),
    ('Conversation Starter', 'post_count_50', 'Send 50 messages in study rooms', NULL, 'social', 'rare', false),
    ('Early Adopter', 'early_adopter', 'Joined during the closed alpha', NULL, 'special', 'legendary', false)
ON CONFLICT (slug) DO NOTHING;

-- Seed triggers for each achievement
INSERT INTO achievement_triggers (achievement_id, trigger_type, trigger_threshold)
SELECT id, 'login_streak', 1 FROM achievements WHERE slug = 'first_login'
ON CONFLICT DO NOTHING;

INSERT INTO achievement_triggers (achievement_id, trigger_type, trigger_threshold)
SELECT id, 'login_streak', 7 FROM achievements WHERE slug = 'streak_7'
ON CONFLICT DO NOTHING;

INSERT INTO achievement_triggers (achievement_id, trigger_type, trigger_threshold)
SELECT id, 'login_streak', 30 FROM achievements WHERE slug = 'streak_30'
ON CONFLICT DO NOTHING;

INSERT INTO achievement_triggers (achievement_id, trigger_type, trigger_threshold)
SELECT id, 'documents_uploaded', 5 FROM achievements WHERE slug = 'documents_5'
ON CONFLICT DO NOTHING;

INSERT INTO achievement_triggers (achievement_id, trigger_type, trigger_threshold)
SELECT id, 'documents_uploaded', 25 FROM achievements WHERE slug = 'documents_25'
ON CONFLICT DO NOTHING;

INSERT INTO achievement_triggers (achievement_id, trigger_type, trigger_threshold)
SELECT id, 'quizzes_completed', 10 FROM achievements WHERE slug = 'quizzes_10'
ON CONFLICT DO NOTHING;

INSERT INTO achievement_triggers (achievement_id, trigger_type, trigger_threshold)
SELECT id, 'flashcards_created', 50 FROM achievements WHERE slug = 'flashcards_50'
ON CONFLICT DO NOTHING;

INSERT INTO achievement_triggers (achievement_id, trigger_type, trigger_threshold)
SELECT id, 'rooms_joined', 10 FROM achievements WHERE slug = 'rooms_joined_10'
ON CONFLICT DO NOTHING;

INSERT INTO achievement_triggers (achievement_id, trigger_type, trigger_threshold)
SELECT id, 'post_count', 50 FROM achievements WHERE slug = 'post_count_50'
ON CONFLICT DO NOTHING;

INSERT INTO achievement_triggers (achievement_id, trigger_type, trigger_threshold)
SELECT id, 'manual_admin_grant', 1 FROM achievements WHERE slug = 'early_adopter'
ON CONFLICT DO NOTHING;
