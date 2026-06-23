-- 0020: academics split — courses (catalog+offering+free-text term) -> abstract courses
--       + course_offerings (per-term) + terms FK; user_courses -> enrollments.
-- Data-preserving: the existing `courses` rows are the only catalog data and are transformed
-- in place (rename + reshape) rather than dropped. Runs identically on staging (empty) and
-- prod (real catalog).

-- 1. The existing `courses` table is already offering-shaped (semester/instructor/meeting/
--    location). Rename it to course_offerings; all inbound FKs follow the rename.
ALTER TABLE courses RENAME TO course_offerings;

-- 2. Add the offering's structural columns (nullable for now; backfilled below).
ALTER TABLE course_offerings ADD COLUMN IF NOT EXISTS course_id  TEXT;
ALTER TABLE course_offerings ADD COLUMN IF NOT EXISTS term_id    TEXT;
ALTER TABLE course_offerings ADD COLUMN IF NOT EXISTS section    TEXT;
ALTER TABLE course_offerings ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- 3. New abstract catalog table.
CREATE TABLE courses (
    id          TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    school_id   TEXT REFERENCES schools(id) ON DELETE RESTRICT,
    course_code TEXT NOT NULL,
    course_name TEXT NOT NULL,
    department  TEXT,
    credits     INTEGER,
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at  TIMESTAMPTZ,
    UNIQUE (school_id, course_code)
);

-- 4. One abstract course per distinct course_code (collapse offerings). Aggregates pick a
--    representative name/dept/credits/description per code.
INSERT INTO courses (id, course_code, course_name, department, credits, description)
SELECT gen_random_uuid()::text,
       course_code,
       max(course_name),
       max(department),
       max(credits),
       max(description)
FROM course_offerings
GROUP BY course_code;

-- 5. Point each offering at its abstract course and term.
UPDATE course_offerings o
   SET course_id = c.id
  FROM courses c
 WHERE c.course_code = o.course_code;

UPDATE course_offerings o
   SET term_id = t.id
  FROM terms t
 WHERE t.label = trim(o.semester);

-- Fail loudly if any offering's semester string had no matching term (add the terms row in 0019).
ALTER TABLE course_offerings ALTER COLUMN course_id SET NOT NULL;
ALTER TABLE course_offerings ALTER COLUMN term_id   SET NOT NULL;

-- 6. Drop the now-abstract columns + legacy free-text term/school from the offering.
ALTER TABLE course_offerings DROP COLUMN course_name;
ALTER TABLE course_offerings DROP COLUMN department;
ALTER TABLE course_offerings DROP COLUMN credits;
ALTER TABLE course_offerings DROP COLUMN description;
ALTER TABLE course_offerings DROP COLUMN semester;
ALTER TABLE course_offerings DROP COLUMN school;   -- free-text school retired; populate `schools` separately if needed

-- 7. Constrain the offering.
ALTER TABLE course_offerings ADD CONSTRAINT course_offerings_course_id_fkey
    FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE;
ALTER TABLE course_offerings ADD CONSTRAINT course_offerings_term_id_fkey
    FOREIGN KEY (term_id) REFERENCES terms(id) ON DELETE RESTRICT;
-- Plain UNIQUE (NULLs distinct): prevents exact dup sections, but legacy rows with an
-- unspecified (NULL) section — e.g. two sections of one course in a term — remain allowed.
ALTER TABLE course_offerings ADD CONSTRAINT course_offerings_unique
    UNIQUE (course_id, term_id, section);

-- 8. Enrollment: user_courses -> enrollments, course_id -> offering_id. The renamed table
--    keeps its data (none today), its user FK, and its UNIQUE(user_id, *) — all follow renames.
ALTER TABLE user_courses RENAME TO enrollments;
ALTER TABLE enrollments RENAME COLUMN course_id TO offering_id;
--    enrollments.offering_id now references course_offerings(id) (inherited from step 1's rename).
--    enrollments.syllabus_doc_id -> documents FK is re-established in 0025 (documents is recreated there).

-- Triggers
DROP TRIGGER IF EXISTS trg_courses_updated_at ON courses;
CREATE TRIGGER trg_courses_updated_at BEFORE UPDATE ON courses
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_course_offerings_updated_at ON course_offerings;
CREATE TRIGGER trg_course_offerings_updated_at BEFORE UPDATE ON course_offerings
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
