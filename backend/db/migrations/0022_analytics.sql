-- 0022: class analytics re-keyed to offering. The last free-text `semester` columns disappear.
-- No user data -> drop/recreate. course_context_service.py upserts these via on_conflict.

DROP TABLE IF EXISTS course_concept_stats CASCADE;
DROP TABLE IF EXISTS course_summary CASCADE;

CREATE TABLE offering_concept_stats (
    id                     TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    offering_id            TEXT NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE,
    concept_name           TEXT NOT NULL,
    student_count          INTEGER NOT NULL DEFAULT 0,
    avg_mastery_score      DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    pct_mastered           DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    pct_struggling         DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    pct_unexplored         DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    common_misconceptions  TEXT[] NOT NULL DEFAULT '{}',
    effective_explanations TEXT[] NOT NULL DEFAULT '{}',
    prerequisite_gaps      TEXT[] NOT NULL DEFAULT '{}',
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (offering_id, concept_name)
);

CREATE TABLE offering_summary (
    offering_id             TEXT PRIMARY KEY REFERENCES course_offerings(id) ON DELETE CASCADE,
    student_count           INTEGER NOT NULL DEFAULT 0,
    avg_class_mastery       DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    top_struggling_concepts TEXT[] NOT NULL DEFAULT '{}',
    top_mastered_concepts   TEXT[] NOT NULL DEFAULT '{}',
    summary_text            TEXT,
    summary_hash            TEXT,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS trg_offering_concept_stats_updated_at ON offering_concept_stats;
CREATE TRIGGER trg_offering_concept_stats_updated_at BEFORE UPDATE ON offering_concept_stats
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_offering_summary_updated_at ON offering_summary;
CREATE TRIGGER trg_offering_summary_updated_at BEFORE UPDATE ON offering_summary
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
