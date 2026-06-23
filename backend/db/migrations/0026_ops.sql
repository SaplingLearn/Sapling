-- 0026: ops cleanup — add the missing user FKs and retire the integer-sequence PKs for
-- convention consistency (text/uuid like the rest). No user data -> drop/recreate.

DROP TABLE IF EXISTS feedback CASCADE;
DROP TABLE IF EXISTS issue_reports CASCADE;

CREATE TABLE feedback (
    id               TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id          TEXT NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
    session_id       TEXT REFERENCES sessions(id)          ON DELETE SET NULL,
    type             TEXT NOT NULL,
    rating           INTEGER NOT NULL,
    selected_options JSONB NOT NULL DEFAULT '[]',
    comment          TEXT,
    topic            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_feedback_user ON feedback(user_id);

CREATE TABLE issue_reports (
    id              TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    topic           TEXT NOT NULL,
    description     TEXT NOT NULL,
    screenshot_urls JSONB NOT NULL DEFAULT '[]',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_issue_reports_user ON issue_reports(user_id);
