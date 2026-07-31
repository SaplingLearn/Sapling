-- 0043: gamification — XP ledger, level curve, friends.
--
-- xp_events is append-only and authoritative; users.total_xp/level are caches
-- recomputed by services/xp_service.py and always rederivable from it.

CREATE TABLE IF NOT EXISTS xp_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rule_key        TEXT NOT NULL,
    amount          INT  NOT NULL,
    source_type     TEXT,
    source_id       TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_xp_events_user_time ON xp_events(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS xp_rules (
    key        TEXT PRIMARY KEY,
    label      TEXT NOT NULL,
    amount     INT  NOT NULL,
    enabled    BOOL NOT NULL DEFAULT true,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO xp_rules (key, label, amount) VALUES
    ('session_completed',      'Completed a study session', 25),
    ('quiz_completed',         'Completed a quiz',          30),
    ('flashcards_reviewed_10', 'Reviewed 10 flashcards',     5),
    ('document_uploaded',      'Uploaded a document',       15),
    ('note_created',           'Created a note',            10),
    ('daily_goal_met',         'Hit the daily XP goal',     20)
ON CONFLICT (key) DO NOTHING;

CREATE TABLE IF NOT EXISTS growth_stages (
    slug            TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    blurb           TEXT NOT NULL,
    min_level       INT  NOT NULL,
    xp_to_complete  INT,            -- NULL for the terminal stage
    sort_order      INT  NOT NULL
);

INSERT INTO growth_stages (slug, name, blurb, min_level, xp_to_complete, sort_order) VALUES
    ('bare',     'Bare Soil',     'Nothing planted yet. Just open ground, turned over and waiting.',                  1,   200,  0),
    ('soil',     'Fallow Soil',   'Rich, quiet earth. Everything begins here, potential resting beneath the surface.', 5,   300,  1),
    ('seed',     'Seed',          'A seed settles in. The first thread-thin roots reach down, feeling for a foothold.', 10,  500,  2),
    ('sprout',   'Sprout',        'A pale shoot cracks the surface and, without hesitating, turns toward the light.',  15,  800,  3),
    ('seedling', 'Seedling',      'Two first leaves unfurl on either side. Small, but unmistakably its own.',          20, 1200,  4),
    ('sapling',  'Sapling',       'Standing on its own now, putting down roots and reaching for the light.',           25, 2000,  5),
    ('young',    'Young Tree',    'Bark begins to harden along the trunk, and the first true branches take shape.',    30, 3200,  6),
    ('branch',   'Branching Out', 'Limbs spread wide and confident, and the first tight buds appear along them.',      35, 4800,  7),
    ('bloom',    'In Bloom',      'Blossoms open all across the crown, a bright, showy season of full growth.',        40, 7000,  8),
    ('fruit',    'Fruit-Bearing', 'Heavy with fruit and alive with visitors. Growth that now feeds more than itself.', 45,10000,  9),
    ('old',      'Old Growth',    'A towering crown years in the making, rooted deep, sheltering all beneath it.',     50, NULL, 10)
ON CONFLICT (slug) DO NOTHING;

-- Friends. Rows are written symmetrically on accept so "my friends" is a plain
-- equality filter with no OR — PostgREST expresses that far more cheaply.
CREATE TABLE IF NOT EXISTS friendships (
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    friend_id  TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, friend_id),
    CHECK (user_id <> friend_id)
);

CREATE TABLE IF NOT EXISTS friend_requests (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    to_user_id   TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status       TEXT NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'accepted', 'declined')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    responded_at TIMESTAMPTZ,
    UNIQUE (from_user_id, to_user_id),
    CHECK (from_user_id <> to_user_id)
);
CREATE INDEX IF NOT EXISTS idx_friend_requests_to ON friend_requests(to_user_id, status);

ALTER TABLE users ADD COLUMN IF NOT EXISTS total_xp       INT DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS level          INT DEFAULT 1;
ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_goal_xp  INT DEFAULT 50;
ALTER TABLE users ADD COLUMN IF NOT EXISTS longest_streak INT DEFAULT 0;

ALTER TABLE achievements ADD COLUMN IF NOT EXISTS xp_reward  INT DEFAULT 0;
ALTER TABLE achievements ADD COLUMN IF NOT EXISTS icon_url   TEXT;
ALTER TABLE achievements ADD COLUMN IF NOT EXISTS sort_order INT DEFAULT 0;

-- 'draft' badges are visible and editable in the admin wiki but are never
-- served to users, never trigger-evaluated, and never counted in "N of M".
-- This is what lets a badge be authored before its trigger exists.
ALTER TABLE achievements ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'live';
ALTER TABLE achievements DROP CONSTRAINT IF EXISTS achievements_status_check;
ALTER TABLE achievements ADD CONSTRAINT achievements_status_check
    CHECK (status IN ('draft', 'live'));
CREATE INDEX IF NOT EXISTS idx_achievements_status ON achievements(status);
