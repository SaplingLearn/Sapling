-- 0025: study & sessions — FKs, indexes, real types, enums, offering scoping. No user data ->
-- drop/recreate. Class artifacts reference the OFFERING; concept links reference graph_nodes.
-- 🔒 = column-encrypted (stays TEXT).

DROP TABLE IF EXISTS messages CASCADE;
DROP TABLE IF EXISTS sessions CASCADE;
DROP TABLE IF EXISTS note_concepts CASCADE;
DROP TABLE IF EXISTS notes CASCADE;
DROP TABLE IF EXISTS quiz_context CASCADE;
DROP TABLE IF EXISTS quiz_attempts CASCADE;
DROP TABLE IF EXISTS study_guides CASCADE;
DROP TABLE IF EXISTS flashcards CASCADE;
DROP TABLE IF EXISTS documents CASCADE;   -- also drops enrollments.syllabus_doc_id FK; re-added at end

CREATE TABLE documents (
    id            TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id       TEXT NOT NULL REFERENCES users(id)            ON DELETE CASCADE,
    offering_id   TEXT NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE,
    file_name     TEXT NOT NULL,
    category      TEXT NOT NULL CHECK (category IN
                    ('syllabus','lecture_notes','slides','reading','assignment','study_guide','other')),
    summary       TEXT,            -- 🔒
    concept_notes TEXT,            -- 🔒
    flashcards    JSONB,
    request_id    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at  TIMESTAMPTZ,
    deleted_at    TIMESTAMPTZ
);
CREATE INDEX idx_documents_user     ON documents(user_id);
CREATE INDEX idx_documents_offering ON documents(offering_id);

CREATE TABLE notes (
    id              TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id         TEXT NOT NULL REFERENCES users(id)            ON DELETE CASCADE,   -- FK added (#180)
    offering_id     TEXT NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE,   -- FK added (#180)
    title           TEXT,            -- 🔒
    body            TEXT,            -- 🔒
    tags            TEXT[] NOT NULL DEFAULT '{}',
    last_summary    TEXT,            -- 🔒
    last_summary_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ
);
CREATE INDEX idx_notes_user     ON notes(user_id);
CREATE INDEX idx_notes_offering ON notes(offering_id);

CREATE TABLE note_concepts (
    note_id         TEXT NOT NULL REFERENCES notes(id)       ON DELETE CASCADE,
    concept_node_id TEXT NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,   -- FK added
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (note_id, concept_node_id)
);

CREATE TABLE flashcards (
    id               TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id          TEXT NOT NULL REFERENCES users(id)            ON DELETE CASCADE,
    offering_id      TEXT REFERENCES course_offerings(id)          ON DELETE SET NULL,
    topic            TEXT NOT NULL,
    front            TEXT NOT NULL,
    back             TEXT NOT NULL,
    times_reviewed   INTEGER NOT NULL DEFAULT 0,
    last_rating      INTEGER,
    last_reviewed_at TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_flashcards_user ON flashcards(user_id);

CREATE TABLE sessions (
    id           TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id      TEXT NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
    offering_id  TEXT REFERENCES course_offerings(id) ON DELETE SET NULL,   -- nullable: general tutoring
    mode         TEXT NOT NULL CHECK (mode IN ('socratic','expository','teachback')),
    topic        TEXT NOT NULL,
    name         TEXT,
    summary_json TEXT,             -- 🔒
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at     TIMESTAMPTZ
);
CREATE INDEX idx_sessions_user ON sessions(user_id);

CREATE TABLE messages (
    id                TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    session_id        TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role              TEXT NOT NULL,     -- 'user' / 'assistant' (set in code; left unconstrained)
    content           TEXT NOT NULL,     -- 🔒
    graph_update_json JSONB,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_messages_session ON messages(session_id, created_at);

CREATE TABLE quiz_attempts (
    id              TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id         TEXT NOT NULL REFERENCES users(id)       ON DELETE CASCADE,
    concept_node_id TEXT REFERENCES graph_nodes(id)          ON DELETE SET NULL,
    score           INTEGER,
    total           INTEGER,
    difficulty      TEXT CHECK (difficulty IN ('easy','medium','hard')),
    questions_json  JSONB,
    answers_json    JSONB,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_quiz_attempts_user    ON quiz_attempts(user_id);
CREATE INDEX idx_quiz_attempts_concept ON quiz_attempts(concept_node_id);

CREATE TABLE quiz_context (
    id              TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id         TEXT NOT NULL REFERENCES users(id)       ON DELETE CASCADE,
    concept_node_id TEXT NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    context_json    JSONB NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE study_guides (
    id           TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id      TEXT NOT NULL REFERENCES users(id)            ON DELETE CASCADE,
    offering_id  TEXT NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE,
    exam_id      TEXT NOT NULL,
    content      JSONB NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_study_guides_user ON study_guides(user_id);

-- Re-establish the enrollment -> document back-reference (dropped with documents above).
ALTER TABLE enrollments ADD CONSTRAINT enrollments_syllabus_doc_id_fkey
    FOREIGN KEY (syllabus_doc_id) REFERENCES documents(id) ON DELETE SET NULL;

-- Triggers (mutable tables)
DROP TRIGGER IF EXISTS trg_notes_updated_at ON notes;
CREATE TRIGGER trg_notes_updated_at BEFORE UPDATE ON notes
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_quiz_context_updated_at ON quiz_context;
CREATE TRIGGER trg_quiz_context_updated_at BEFORE UPDATE ON quiz_context
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
