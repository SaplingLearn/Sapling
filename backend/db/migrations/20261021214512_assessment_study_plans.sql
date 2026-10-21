-- Assessment scope, topic edits and scheduled sessions contain private student
-- material. The service encrypts the entire content payload before storage.
CREATE TABLE assessment_study_plans (
    id UUID PRIMARY KEY,
    enrollment_id TEXT NOT NULL REFERENCES enrollments(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX assessment_study_plans_enrollment_idx
    ON assessment_study_plans(enrollment_id, created_at DESC);
ALTER TABLE assessment_study_plans ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON assessment_study_plans FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON assessment_study_plans TO service_role;
