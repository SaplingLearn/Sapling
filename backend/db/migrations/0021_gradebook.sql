-- 0021: gradebook re-keyed to enrollment. No user data, so drop/recreate to target shape.
-- 🔒 = column-encrypted (stays TEXT, decrypted at read via decrypt_numeric/decrypt_if_present).

DROP TABLE IF EXISTS assignments CASCADE;
DROP TABLE IF EXISTS course_categories CASCADE;

CREATE TABLE gradebook_categories (
    id            TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    enrollment_id TEXT NOT NULL REFERENCES enrollments(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    weight        NUMERIC NOT NULL,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_gradebook_categories_enrollment ON gradebook_categories(enrollment_id);

CREATE TABLE assignments (
    id              TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    enrollment_id   TEXT REFERENCES enrollments(id) ON DELETE CASCADE,         -- nullable: calendar-only items
    category_id     TEXT REFERENCES gradebook_categories(id) ON DELETE SET NULL,
    title           TEXT NOT NULL,
    due_date        DATE,
    assignment_type TEXT CHECK (assignment_type IN ('homework','exam','reading','project','quiz','other')),
    notes           TEXT,            -- 🔒
    points_possible TEXT,            -- 🔒 (numeric semantics; decrypt_numeric at read)
    points_earned   TEXT,            -- 🔒
    source          TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','syllabus')),
    google_event_id TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_assignments_enrollment ON assignments(enrollment_id);
CREATE INDEX idx_assignments_due        ON assignments(due_date);

DROP TRIGGER IF EXISTS trg_gradebook_categories_updated_at ON gradebook_categories;
CREATE TRIGGER trg_gradebook_categories_updated_at BEFORE UPDATE ON gradebook_categories
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_assignments_updated_at ON assignments;
CREATE TRIGGER trg_assignments_updated_at BEFORE UPDATE ON assignments
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
