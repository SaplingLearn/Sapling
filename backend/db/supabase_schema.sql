-- ============================================================
-- Sapling — Supabase Schema
-- Run this in: Supabase Dashboard → SQL Editor → New query
-- ============================================================

-- Users
CREATE TABLE IF NOT EXISTS users (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT,
    streak_count INTEGER DEFAULT 0,
    last_active_date TEXT,
    room_id     TEXT,
    created_at  TIMESTAMPTZ DEFAULT now(),
    google_id   TEXT UNIQUE,
    avatar_url  TEXT,
    auth_provider TEXT DEFAULT 'google',
    is_approved BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id);

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
    created_at      TIMESTAMPTZ DEFAULT now(),
    mastery_events  JSONB DEFAULT '[]'  -- array of {ts, delta, reason, event_type} — last 20 events
);

-- Knowledge graph edges
CREATE TABLE IF NOT EXISTS graph_edges (
    id                TEXT PRIMARY KEY,
    user_id           TEXT NOT NULL,
    source_node_id    TEXT NOT NULL REFERENCES graph_nodes(id),
    target_node_id    TEXT NOT NULL REFERENCES graph_nodes(id),
    strength          DOUBLE PRECISION DEFAULT 0.5,
    created_at        TIMESTAMPTZ DEFAULT now(),
    relationship_type TEXT DEFAULT 'related'  -- 'prerequisite' | 'builds_on' | 'related'
);

-- Migrations (run these if the table already exists)
-- ALTER TABLE graph_nodes ADD COLUMN IF NOT EXISTS mastery_events JSONB DEFAULT '[]';
-- ALTER TABLE graph_edges ADD COLUMN IF NOT EXISTS relationship_type TEXT DEFAULT 'related';

-- Courses
CREATE TABLE IF NOT EXISTS courses (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id),
    course_name TEXT NOT NULL,
    color       TEXT,
    created_at  TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, course_name)
);

-- Learning sessions
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id),
    mode        TEXT NOT NULL,
    topic       TEXT NOT NULL,
    started_at  TIMESTAMPTZ DEFAULT now(),
    ended_at    TIMESTAMPTZ,
    summary_json JSONB
);

-- Chat messages within a session
CREATE TABLE IF NOT EXISTS messages (
    id               TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL REFERENCES sessions(id),
    role             TEXT NOT NULL,
    content          TEXT NOT NULL,
    graph_update_json JSONB,
    created_at       TIMESTAMPTZ DEFAULT now()
);

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

-- Per-user per-concept quiz context (adaptive history for Gemini)
CREATE TABLE IF NOT EXISTS quiz_context (
    id              TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    user_id         TEXT NOT NULL REFERENCES users(id),
    concept_node_id TEXT NOT NULL REFERENCES graph_nodes(id),
    context_json    JSONB NOT NULL,
    updated_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, concept_node_id)
);

-- Assignments (from syllabus extraction or manual entry)
CREATE TABLE IF NOT EXISTS assignments (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id),
    title           TEXT NOT NULL,
    course_name     TEXT,
    due_date        TEXT NOT NULL,
    assignment_type TEXT,
    notes           TEXT,
    google_event_id TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
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
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id  UUID NOT NULL REFERENCES room_messages(id) ON DELETE CASCADE,
    user_id     TEXT NOT NULL REFERENCES users(id),
    emoji       TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now(),
    UNIQUE(message_id, user_id, emoji)
);

CREATE INDEX IF NOT EXISTS idx_room_reactions_message_id ON room_reactions(message_id);

-- Migrations (run if tables already exist without these columns):
-- ALTER TABLE room_messages ADD COLUMN IF NOT EXISTS reply_to_id UUID REFERENCES room_messages(id);
-- ALTER TABLE room_messages ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;
-- ALTER TABLE room_messages ADD COLUMN IF NOT EXISTS edited_at TIMESTAMPTZ;

-- Cached AI summaries for study rooms
CREATE TABLE IF NOT EXISTS room_summaries (
    room_id     TEXT PRIMARY KEY REFERENCES rooms(id),
    summary     TEXT NOT NULL,
    member_hash TEXT NOT NULL,
    updated_at  TIMESTAMPTZ DEFAULT now()
);

-- Shared course-level learning context (aggregated from all students, no Gemini)
CREATE TABLE IF NOT EXISTS course_context (
    course_name   TEXT PRIMARY KEY,
    context_json  JSONB NOT NULL,
    student_count INTEGER DEFAULT 0,
    updated_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS flashcards (
    id               TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL REFERENCES users(id),
    topic            TEXT NOT NULL,
    front            TEXT NOT NULL,
    back             TEXT NOT NULL,
    times_reviewed   INTEGER DEFAULT 0,
    last_rating      INTEGER,
    last_reviewed_at TIMESTAMPTZ,
    created_at       TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_flashcards_user_topic ON flashcards(user_id, topic);

CREATE TABLE public.flashcards (
  id text NOT NULL,
  user_id text NOT NULL,
  topic text NOT NULL,
  front text NOT NULL,
  back text NOT NULL,
  times_reviewed integer DEFAULT 0,
  last_rating integer,
  last_reviewed_at timestamp with time zone,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT flashcards_pkey PRIMARY KEY (id),
  CONSTRAINT flashcards_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id)
);

CREATE INDEX IF NOT EXISTS idx_flashcards_user_topic ON public.flashcards(user_id, topic);