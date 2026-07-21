-- 0032: observability tables (issue #115) — the two tables backing the site
-- logging + usage-tracking system.
--
--   events     — flexible, high-volume analytics / audit / error events.
--   llm_usage  — structured per-call LLM token + cost rows, queried with
--                SUM/GROUP BY for billing rollups.
--
-- Notes / deviations from the original issue spec:
--   * Ids and user_id are TEXT, not uuid, to match the rest of this schema
--     (users.id is TEXT, e.g. 'user_andres'); a uuid user_id column could not
--     hold the existing text ids. Same gen_random_uuid()::text PK style as
--     0026_ops.sql.
--   * No FK on user_id. These are append-only, high-write analytics tables and
--     user_id is intentionally nullable (system/anonymous actors); we don't
--     want a per-row FK check on the write path or cascade coupling to the
--     users lifecycle. Kept as a plain nullable column.
--   * NO raw-content columns. Sensitive content is represented only by
--     content_fp (a 16-hex sha256 fingerprint). Never store message text,
--     document text, or names here.
--   * admin_audit_log is deliberately untouched — events complements it.
--
-- Idempotent (IF NOT EXISTS throughout) so it is safe to re-run.

-- ── events ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS events (
    id          TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    event_type  TEXT NOT NULL,                 -- dotted taxonomy: document.upload, auth.login, error.5xx
    category    TEXT NOT NULL,                 -- usage | audit | error
    user_id     TEXT,                          -- actor; NULL for anonymous/system
    request_id  TEXT,                          -- correlates to RequestIDMiddleware + Logfire
    payload     JSONB NOT NULL DEFAULT '{}',   -- type-specific metadata (counts, ids, status_code, duration_ms…)
    content_fp  TEXT,                          -- sha256 fingerprint (16 hex) — never raw content
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_events_user_created  ON events (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_type_created  ON events (event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_cat_created   ON events (category, created_at DESC);

-- ── llm_usage ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS llm_usage (
    id                TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id           TEXT,                    -- per-user rollups; NULL for system
    request_id        TEXT,
    feature           TEXT NOT NULL,           -- quiz | chat_tutor | document | notes …
    task              TEXT,                    -- matches agents/_providers.py task slots
    model             TEXT NOT NULL,           -- e.g. gemini-2.5-flash
    provider          TEXT NOT NULL DEFAULT 'gemini',
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens      INTEGER NOT NULL DEFAULT 0,
    cost_usd          NUMERIC(12,6),           -- NULL when the model isn't priced
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_llm_usage_user_created    ON llm_usage (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_usage_feature_created ON llm_usage (feature, created_at DESC);
