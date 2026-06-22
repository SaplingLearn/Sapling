-- ============================================================
-- Sapling — Supabase Schema (course_id migration)
-- Run this in: Supabase Dashboard → SQL Editor → New query
-- ============================================================

-- Users
CREATE TABLE IF NOT EXISTS users (
    id                    TEXT PRIMARY KEY,
    name                  TEXT NOT NULL,
    email                 TEXT,
    first_name            TEXT,
    last_name             TEXT,
    year                  TEXT,
    majors                TEXT[] DEFAULT '{}',
    minors                TEXT[] DEFAULT '{}',
    learning_style        TEXT,
    onboarding_completed  BOOLEAN NOT NULL DEFAULT false,
    streak_count          INTEGER DEFAULT 0,
    last_active_date      TEXT,
    room_id     TEXT,
    created_at  TIMESTAMPTZ DEFAULT now(),
    google_id   TEXT UNIQUE,
    avatar_url  TEXT,
    auth_provider TEXT DEFAULT 'google',
    is_approved BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id);

-- Canonical course catalog (no user_id — shared across all students)
CREATE TABLE IF NOT EXISTS courses (
    id              TEXT PRIMARY KEY,
    course_code     TEXT NOT NULL,
    course_name     TEXT NOT NULL,
    department      TEXT,
    credits         INTEGER,
    semester        TEXT DEFAULT 'Spring 2026',
    instructor_name TEXT,
    meeting_times   TEXT,
    location        TEXT,
    description     TEXT,
    syllabus_url    TEXT,
    school          TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Enrollment join table (user ↔ canonical course)
CREATE TABLE IF NOT EXISTS user_courses (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id),
    course_id       TEXT NOT NULL REFERENCES courses(id),
    color           TEXT,
    nickname        TEXT,
    enrolled_at     TIMESTAMPTZ DEFAULT now(),
    letter_scale    JSONB,
    syllabus_doc_id TEXT, -- FK declared after documents block
    UNIQUE (user_id, course_id)
);

CREATE INDEX IF NOT EXISTS idx_user_courses_user_id ON user_courses(user_id);

-- Per-(user, course) grading categories with weights
CREATE TABLE IF NOT EXISTS course_categories (
    id          TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    user_id     TEXT NOT NULL REFERENCES users(id),
    course_id   TEXT NOT NULL REFERENCES courses(id),
    name        TEXT NOT NULL,
    weight      NUMERIC NOT NULL,
    sort_order  INTEGER DEFAULT 0,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_course_categories_user_course
  ON course_categories(user_id, course_id);

-- Knowledge graph nodes
CREATE TABLE IF NOT EXISTS graph_nodes (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id),
    concept_name    TEXT NOT NULL,
    mastery_score   DOUBLE PRECISION DEFAULT 0.0,
    mastery_tier    TEXT DEFAULT 'unexplored',
    times_studied   INTEGER DEFAULT 0,
    last_studied_at TIMESTAMPTZ,
    subject         TEXT,
    course_id       TEXT REFERENCES courses(id),
    color           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    mastery_events  JSONB DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_graph_nodes_user_course ON graph_nodes(user_id, course_id);

-- Knowledge graph edges
CREATE TABLE IF NOT EXISTS graph_edges (
    id                TEXT PRIMARY KEY,
    user_id           TEXT NOT NULL,
    source_node_id    TEXT NOT NULL REFERENCES graph_nodes(id),
    target_node_id    TEXT NOT NULL REFERENCES graph_nodes(id),
    strength          DOUBLE PRECISION DEFAULT 0.5,
    created_at        TIMESTAMPTZ DEFAULT now(),
    relationship_type TEXT DEFAULT 'related'
);

-- graph_edges has no FK-backed index; graph render + cascade delete scan by
-- user_id and by either node endpoint (#160).
CREATE INDEX IF NOT EXISTS idx_graph_edges_user   ON graph_edges(user_id);
CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON graph_edges(source_node_id);
CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON graph_edges(target_node_id);

-- Learning sessions
CREATE TABLE IF NOT EXISTS sessions (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(id),
    mode         TEXT NOT NULL,
    topic        TEXT NOT NULL,
    course_id    TEXT REFERENCES courses(id),
    started_at   TIMESTAMPTZ DEFAULT now(),
    ended_at     TIMESTAMPTZ,
    summary_json TEXT, -- encrypted base64 text (AES-256-GCM via services/encryption.py)
    name         TEXT
);

-- History listing + profile stats filter user_id, order started_at desc (#176).
CREATE INDEX IF NOT EXISTS idx_sessions_user_started
    ON sessions(user_id, started_at DESC);

-- Chat messages within a session
CREATE TABLE IF NOT EXISTS messages (
    id                TEXT PRIMARY KEY,
    session_id        TEXT NOT NULL REFERENCES sessions(id),
    role              TEXT NOT NULL,
    content           TEXT NOT NULL,
    graph_update_json JSONB,
    created_at        TIMESTAMPTZ DEFAULT now()
);

-- Fastest-growing table; every chat load filters session_id, orders created_at (#161).
CREATE INDEX IF NOT EXISTS idx_messages_session_created
    ON messages(session_id, created_at);

-- Quiz attempts
CREATE TABLE IF NOT EXISTS quiz_attempts (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id),
    concept_node_id TEXT REFERENCES graph_nodes(id),
    score           INTEGER,
    total           INTEGER,
    difficulty      TEXT,
    questions_json  JSONB,
    answers_json    JSONB,
    completed_at    TIMESTAMPTZ
);

-- Achievement counts + history aggregations filter user_id (#178).
CREATE INDEX IF NOT EXISTS idx_quiz_attempts_user
    ON quiz_attempts(user_id);

-- Per-user per-concept quiz context (adaptive history for Gemini)
CREATE TABLE IF NOT EXISTS quiz_context (
    id              TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    user_id         TEXT NOT NULL REFERENCES users(id),
    concept_node_id TEXT NOT NULL REFERENCES graph_nodes(id),
    context_json    JSONB NOT NULL,
    updated_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, concept_node_id)
);

-- Assignments (from syllabus extraction or manual entry; gradebook-aware)
CREATE TABLE IF NOT EXISTS assignments (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id),
    title           TEXT NOT NULL,
    course_id       TEXT REFERENCES courses(id),
    due_date        TEXT,
    assignment_type TEXT,
    notes           TEXT,
    google_event_id TEXT,
    category_id     TEXT REFERENCES course_categories(id) ON DELETE SET NULL,
    points_possible TEXT, -- encrypted base64 text (AES-256-GCM via services/encryption.py)
    points_earned   TEXT, -- encrypted base64 text (AES-256-GCM via services/encryption.py)
    source          TEXT DEFAULT 'manual',
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_assignments_user_due ON assignments(user_id, due_date);

-- Documents (uploaded course materials)
CREATE TABLE IF NOT EXISTS documents (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(id),
    course_id    TEXT NOT NULL REFERENCES courses(id),
    file_name    TEXT NOT NULL,
    category     TEXT NOT NULL,
    summary      TEXT,
    flashcards   JSONB,
    concept_notes TEXT, -- encrypted base64 text (AES-256-GCM via services/encryption.py)
    created_at   TIMESTAMPTZ DEFAULT now(),
    processed_at TIMESTAMPTZ
);

-- Wire user_courses.syllabus_doc_id → documents(id) now that documents exists.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'user_courses_syllabus_doc_id_fkey'
  ) THEN
    ALTER TABLE user_courses
      ADD CONSTRAINT user_courses_syllabus_doc_id_fkey
      FOREIGN KEY (syllabus_doc_id) REFERENCES documents(id);
  END IF;
END $$;

-- Library listing filters user_id/created_at; study-guide context filters
-- user_id + course_id. The partial unique on (user_id, request_id) doesn't
-- serve a bare user_id scan (#177).
CREATE INDEX IF NOT EXISTS idx_documents_user_created
    ON documents(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_user_course
    ON documents(user_id, course_id);

-- Study guides
CREATE TABLE IF NOT EXISTS study_guides (
    id           TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    user_id      TEXT NOT NULL REFERENCES users(id),
    course_id    TEXT NOT NULL REFERENCES courses(id),
    exam_id      TEXT NOT NULL,
    generated_at TIMESTAMPTZ DEFAULT now(),
    content      JSONB NOT NULL
);

-- Cached-guide listing (user_id, generated_at) + cache-hit lookup
-- (user_id, course_id, exam_id) both full-scan without these (#178).
CREATE INDEX IF NOT EXISTS idx_study_guides_user
    ON study_guides(user_id, generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_study_guides_lookup
    ON study_guides(user_id, course_id, exam_id);

-- Per-concept aggregated course stats (across all enrolled students)
CREATE TABLE IF NOT EXISTS course_concept_stats (
    id                    TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    course_id             TEXT NOT NULL REFERENCES courses(id),
    concept_name          TEXT NOT NULL,
    semester              TEXT NOT NULL DEFAULT 'Spring 2026',
    student_count         INTEGER DEFAULT 0,
    avg_mastery_score     DOUBLE PRECISION DEFAULT 0.0,
    pct_mastered          DOUBLE PRECISION DEFAULT 0.0,
    pct_struggling        DOUBLE PRECISION DEFAULT 0.0,
    pct_unexplored        DOUBLE PRECISION DEFAULT 0.0,
    common_misconceptions TEXT[] DEFAULT '{}',
    effective_explanations TEXT[] DEFAULT '{}',
    prerequisite_gaps     TEXT[] DEFAULT '{}',
    updated_at            TIMESTAMPTZ DEFAULT now(),
    UNIQUE (course_id, concept_name, semester)
);

-- Course-wide summary (rolled up from course_concept_stats)
CREATE TABLE IF NOT EXISTS course_summary (
    course_id               TEXT NOT NULL REFERENCES courses(id),
    semester                TEXT NOT NULL DEFAULT 'Spring 2026',
    student_count           INTEGER DEFAULT 0,
    avg_class_mastery       DOUBLE PRECISION DEFAULT 0.0,
    top_struggling_concepts TEXT[] DEFAULT '{}',
    top_mastered_concepts   TEXT[] DEFAULT '{}',
    summary_text            TEXT,
    summary_hash            TEXT,
    updated_at              TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (course_id, semester)
);

-- Study rooms
CREATE TABLE IF NOT EXISTS rooms (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    invite_code TEXT UNIQUE NOT NULL,
    created_by  TEXT NOT NULL REFERENCES users(id),
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Room membership
CREATE TABLE IF NOT EXISTS room_members (
    room_id   TEXT NOT NULL REFERENCES rooms(id),
    user_id   TEXT NOT NULL REFERENCES users(id),
    joined_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (room_id, user_id)
);

-- Room activity feed
CREATE TABLE IF NOT EXISTS room_activity (
    id            TEXT PRIMARY KEY,
    room_id       TEXT NOT NULL REFERENCES rooms(id),
    user_id       TEXT NOT NULL REFERENCES users(id),
    activity_type TEXT NOT NULL,
    concept_name  TEXT,
    detail        TEXT,
    created_at    TIMESTAMPTZ DEFAULT now()
);

-- Google Calendar OAuth tokens
CREATE TABLE IF NOT EXISTS oauth_tokens (
    user_id       TEXT PRIMARY KEY REFERENCES users(id),
    access_token  TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at    TEXT NOT NULL
);

-- Room chat messages
CREATE TABLE IF NOT EXISTS room_messages (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id     TEXT NOT NULL REFERENCES rooms(id),
    user_id     TEXT NOT NULL REFERENCES users(id),
    user_name   TEXT NOT NULL,
    text        TEXT,
    image_url   TEXT,
    reply_to_id UUID REFERENCES room_messages(id),
    is_deleted  BOOLEAN NOT NULL DEFAULT FALSE,
    edited_at   TIMESTAMPTZ,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_room_messages_room_id ON room_messages(room_id, created_at);

-- Emoji reactions on room messages
CREATE TABLE IF NOT EXISTS room_reactions (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID NOT NULL REFERENCES room_messages(id) ON DELETE CASCADE,
    user_id    TEXT NOT NULL REFERENCES users(id),
    emoji      TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(message_id, user_id, emoji)
);

CREATE INDEX IF NOT EXISTS idx_room_reactions_message_id ON room_reactions(message_id);

-- Cached AI summaries for study rooms
CREATE TABLE IF NOT EXISTS room_summaries (
    room_id     TEXT PRIMARY KEY REFERENCES rooms(id),
    summary     TEXT NOT NULL,
    member_hash TEXT NOT NULL,
    updated_at  TIMESTAMPTZ DEFAULT now()
);

-- Flashcards
CREATE TABLE IF NOT EXISTS flashcards (
    id               TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL REFERENCES users(id),
    topic            TEXT NOT NULL,
    course_id        TEXT REFERENCES courses(id),
    front            TEXT NOT NULL,
    back             TEXT NOT NULL,
    times_reviewed   INTEGER DEFAULT 0,
    last_rating      INTEGER,
    last_reviewed_at TIMESTAMPTZ,
    created_at       TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_flashcards_user_topic ON flashcards(user_id, topic);
CREATE INDEX IF NOT EXISTS idx_flashcards_user_course ON flashcards(user_id, course_id);

-- Feedback
CREATE TABLE IF NOT EXISTS feedback (
    id               SERIAL PRIMARY KEY,
    user_id          TEXT NOT NULL,
    type             TEXT NOT NULL,
    rating           INTEGER NOT NULL,
    selected_options JSONB DEFAULT '[]',
    comment          TEXT,
    session_id       TEXT,
    topic            TEXT,
    created_at       TIMESTAMPTZ DEFAULT now()
);

-- Issue reports
CREATE TABLE IF NOT EXISTS issue_reports (
    id               SERIAL PRIMARY KEY,
    user_id          TEXT NOT NULL,
    topic            TEXT NOT NULL,
    description      TEXT NOT NULL,
    screenshot_urls  JSONB DEFAULT '[]',
    created_at       TIMESTAMPTZ DEFAULT now()
);

-- Job applications
CREATE TABLE IF NOT EXISTS job_applications (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    position       TEXT NOT NULL,
    full_name      TEXT NOT NULL,
    email          TEXT NOT NULL,
    phone          TEXT,
    linkedin_url   TEXT NOT NULL,
    resume         TEXT,
    portfolio_link TEXT,
    submitted_at   TIMESTAMPTZ DEFAULT now()
);

-- ══════════════════════════════════════════════════════════════════
-- Profile, Settings, Roles, Achievements, Cosmetics
-- ══════════════════════════════════════════════════════════════════

-- Profile columns on users (added via migration)
-- ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT UNIQUE;
-- ALTER TABLE users ADD COLUMN IF NOT EXISTS bio TEXT;
-- ALTER TABLE users ADD COLUMN IF NOT EXISTS location TEXT;
-- ALTER TABLE users ADD COLUMN IF NOT EXISTS website TEXT;
-- ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

-- User settings
CREATE TABLE IF NOT EXISTS user_settings (
    user_id                  TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    display_name             TEXT,
    username                 TEXT,
    bio                      TEXT,
    location                 TEXT,
    website                  TEXT,
    profile_visibility       TEXT DEFAULT 'public' CHECK (profile_visibility IN ('public', 'private')),
    activity_status_visible  BOOL DEFAULT true,
    notification_email       BOOL DEFAULT true,
    notification_push        BOOL DEFAULT false,
    notification_in_app      BOOL DEFAULT true,
    theme                    TEXT DEFAULT 'light' CHECK (theme IN ('light', 'dark')),
    font_size                TEXT DEFAULT 'medium' CHECK (font_size IN ('small', 'medium', 'large')),
    accent_color             TEXT,
    featured_role_id         UUID,
    featured_achievement_ids TEXT[] DEFAULT '{}',
    equipped_avatar_frame_id UUID,
    equipped_banner_id       UUID,
    equipped_name_color_id   UUID,
    equipped_title_id        UUID,
    created_at               TIMESTAMPTZ DEFAULT now(),
    updated_at               TIMESTAMPTZ DEFAULT now()
);

-- Roles
CREATE TABLE IF NOT EXISTS roles (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name             TEXT NOT NULL,
    slug             TEXT UNIQUE NOT NULL,
    color            TEXT NOT NULL,
    icon             TEXT,
    description      TEXT,
    is_staff_assigned BOOL DEFAULT true,
    is_earnable      BOOL DEFAULT false,
    display_priority INT DEFAULT 0,
    created_at       TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_roles (
    user_id    TEXT REFERENCES users(id) ON DELETE CASCADE,
    role_id    UUID REFERENCES roles(id) ON DELETE CASCADE,
    granted_at TIMESTAMPTZ DEFAULT now(),
    granted_by TEXT,
    PRIMARY KEY (user_id, role_id)
);

CREATE INDEX IF NOT EXISTS idx_user_roles_user_id ON user_roles(user_id);

-- Achievements
CREATE TABLE IF NOT EXISTS achievements (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    slug        TEXT UNIQUE NOT NULL,
    description TEXT,
    icon        TEXT,
    category    TEXT CHECK (category IN ('activity', 'social', 'milestone', 'special')),
    rarity      TEXT CHECK (rarity IN ('common', 'uncommon', 'rare', 'epic', 'legendary')),
    is_secret   BOOL DEFAULT false,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS achievement_triggers (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    achievement_id   UUID REFERENCES achievements(id) ON DELETE CASCADE,
    trigger_type     TEXT NOT NULL,
    trigger_threshold INT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_achievements (
    user_id        TEXT REFERENCES users(id) ON DELETE CASCADE,
    achievement_id UUID REFERENCES achievements(id) ON DELETE CASCADE,
    earned_at      TIMESTAMPTZ DEFAULT now(),
    is_featured    BOOL DEFAULT false,
    PRIMARY KEY (user_id, achievement_id)
);

CREATE TABLE IF NOT EXISTS achievement_cosmetics (
    achievement_id UUID REFERENCES achievements(id) ON DELETE CASCADE,
    cosmetic_id    UUID,
    PRIMARY KEY (achievement_id, cosmetic_id)
);

-- Cosmetics
CREATE TABLE IF NOT EXISTS cosmetics (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type          TEXT CHECK (type IN ('avatar_frame', 'banner', 'name_color', 'title')),
    name          TEXT NOT NULL,
    slug          TEXT UNIQUE NOT NULL,
    asset_url     TEXT,
    css_value     TEXT,
    rarity        TEXT CHECK (rarity IN ('common', 'uncommon', 'rare', 'epic', 'legendary')),
    unlock_source TEXT,
    created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS role_cosmetics (
    role_id     UUID REFERENCES roles(id) ON DELETE CASCADE,
    cosmetic_id UUID REFERENCES cosmetics(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, cosmetic_id)
);

CREATE TABLE IF NOT EXISTS user_cosmetics (
    user_id     TEXT REFERENCES users(id) ON DELETE CASCADE,
    cosmetic_id UUID REFERENCES cosmetics(id) ON DELETE CASCADE,
    unlocked_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (user_id, cosmetic_id)
);

-- Notetaker
-- notes.title and notes.body are AES-GCM encrypted at the application layer
-- (services/encryption.py). tags is plaintext text[] so PostgREST array
-- filters work for tag-based search. last_summary is the cached output of
-- the most recent /summarize action; null until the user runs it.
--
-- note_concepts is a junction table linking notes <-> graph_nodes.
-- ON DELETE CASCADE on note_id ensures deleting a note cleans up its
-- links. The graph_node FK is intentionally NOT a hard FK because
-- graph_nodes uses TEXT ids managed by application code (no enforced FK
-- pattern elsewhere in this codebase — see graph_edges.source_node_id).

CREATE TABLE notes (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    title TEXT,
    body TEXT,
    tags TEXT[] NOT NULL DEFAULT '{}',
    last_summary TEXT,
    last_summary_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_notes_user_updated
    ON notes (user_id, updated_at DESC);

CREATE INDEX idx_notes_user_course
    ON notes (user_id, course_id);

CREATE TABLE note_concepts (
    note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    concept_node_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (note_id, concept_node_id)
);

CREATE INDEX idx_note_concepts_concept
    ON note_concepts (concept_node_id);
