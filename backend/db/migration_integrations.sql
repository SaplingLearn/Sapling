-- Integrations: external service connections and sync log.
-- Idempotent — safe to re-run.

-- 1. One row per (user, provider) — stores credentials and connection state.
CREATE TABLE IF NOT EXISTS external_connections (
  id           TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
  user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider     TEXT NOT NULL,           -- 'gradescope' | 'blackboard' | 'piazza'
  credentials  TEXT,                    -- AES-256-GCM encrypted JSON blob
  status       TEXT NOT NULL DEFAULT 'active', -- 'active' | 'error' | 'disconnected'
  last_synced_at TIMESTAMPTZ,
  created_at   TIMESTAMPTZ DEFAULT now(),
  updated_at   TIMESTAMPTZ DEFAULT now(),
  UNIQUE (user_id, provider)
);

CREATE INDEX IF NOT EXISTS idx_external_connections_user
  ON external_connections(user_id);

-- 2. One row per sync attempt — append-only audit log.
CREATE TABLE IF NOT EXISTS external_sync_events (
  id             TEXT PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
  user_id        TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider       TEXT NOT NULL,
  status         TEXT NOT NULL,   -- 'success' | 'error'
  courses_synced INTEGER DEFAULT 0,
  assignments_synced INTEGER DEFAULT 0,
  error_message  TEXT,
  created_at     TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_external_sync_events_user_provider
  ON external_sync_events(user_id, provider);