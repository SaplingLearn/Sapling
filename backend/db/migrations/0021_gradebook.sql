-- 0021: gradebook re-keyed to enrollment. No user data, so drop/recreate to target shape.
-- 🔒 = column-encrypted (stays TEXT, decrypted at read via decrypt_numeric/decrypt_if_present).
-- ABSORBS the parallel `origin/Gradebook` work, re-expressed against the enrollment-keyed shape:
--   * drop-lowest policy (was course_categories.drop_lowest)        -> gradebook_categories.drop_lowest
--   * bell-curve policy (was user_courses.curve_*)                  -> enrollments.curve_*
--   * per-assignment curve stats + gradescope id (was assignments.*) -> assignments below
-- Gradescope credential/link tables live in 0027. See issues filed for the code rewire.

DROP TABLE IF EXISTS assignments CASCADE;
DROP TABLE IF EXISTS course_categories CASCADE;

-- Per-course curve policy lives on the enrollment row (was user_courses.curve_*).
ALTER TABLE enrollments
    ADD COLUMN curve_mode       TEXT NOT NULL DEFAULT 'raw' CHECK (curve_mode IN ('raw','curved')),
    ADD COLUMN curve_avg_target NUMERIC,
    ADD COLUMN curve_sd_delta   NUMERIC;

CREATE TABLE gradebook_categories (
    id            TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    enrollment_id TEXT NOT NULL REFERENCES enrollments(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    weight        NUMERIC NOT NULL,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    drop_lowest   INTEGER NOT NULL DEFAULT 0 CHECK (drop_lowest >= 0),   -- absorbed from 0019_gradebook_drops
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
    -- absorbed from origin/Gradebook (curve stats are plaintext NUMERIC class stats, not student-identifying)
    gradescope_assignment_id TEXT,
    curve_class_mean NUMERIC,
    curve_class_sd   NUMERIC,
    curve_avg_target NUMERIC,
    curve_sd_delta   NUMERIC,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_assignments_enrollment ON assignments(enrollment_id);
CREATE INDEX idx_assignments_due        ON assignments(due_date);
-- Gradescope idempotency key, re-targeted from course_id to enrollment_id (assignments are
-- now enrollment-scoped). Only enforced when a gradescope id is present.
CREATE UNIQUE INDEX idx_assignments_gradescope_id
    ON assignments(enrollment_id, gradescope_assignment_id)
    WHERE gradescope_assignment_id IS NOT NULL;

DROP TRIGGER IF EXISTS trg_gradebook_categories_updated_at ON gradebook_categories;
CREATE TRIGGER trg_gradebook_categories_updated_at BEFORE UPDATE ON gradebook_categories
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_assignments_updated_at ON assignments;
CREATE TRIGGER trg_assignments_updated_at BEFORE UPDATE ON assignments
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
