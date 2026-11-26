-- Concepts a student took out of a course (the Tutor's course setup, "Untick
-- any that aren't part of your course"; Tutor redesign, owner decision
-- 2026-11-26).
--
-- What this adds
-- --------------
-- public.course_concept_exclusions: one row per (student, course, concept)
-- the student removed in course setup. The concept's graph node is deleted
-- at the same time (services/graph_service.py::delete_node); this row is what
-- keeps it out: apply_graph_update skips a new concept whose normalized name
-- is excluded for that student and course, so a later upload of the same
-- material does not bring it back.
--
--   course_id    the ABSTRACT course. ON DELETE CASCADE.
--   concept_key  the concept's name, normalized as graph_service does
--                (`_normalize_concept`). PLAINTEXT on purpose, like
--                graph_nodes.concept_name: a label, not study content.
--
-- Access: owned directly (RLS bucket A), the same shape as flashcard_sets
-- (20261112060028). Account data: wiped (services/account_wipe.py) and copied
-- by the bundle (services/account_bundle.py, course_id remapped).
--
-- Idempotent, additive, touches no existing data.
--
-- Reverse (by hand, as the migration role):
--   DROP TABLE IF EXISTS public.course_concept_exclusions;
-- (Removed concepts may come back with a later upload.)

CREATE TABLE IF NOT EXISTS public.course_concept_exclusions (
    id          TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id     TEXT NOT NULL REFERENCES public.users(id)   ON DELETE CASCADE,
    course_id   TEXT NOT NULL REFERENCES public.courses(id) ON DELETE CASCADE,
    concept_key TEXT NOT NULL,                      -- plaintext, normalized
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT course_concept_exclusions_key_check CHECK (btrim(concept_key) <> ''),
    CONSTRAINT course_concept_exclusions_unique UNIQUE (user_id, course_id, concept_key)
);

COMMENT ON TABLE public.course_concept_exclusions IS
    'Concepts a student removed from a course in course setup; apply_graph_update does not re-create them.';

-- The unique constraint's index serves the (user, course) read; the courses
-- ON DELETE CASCADE looks rows up by course alone.
CREATE INDEX IF NOT EXISTS idx_course_concept_exclusions_course
    ON public.course_concept_exclusions (course_id);

ALTER TABLE public.course_concept_exclusions ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.course_concept_exclusions FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT ALL ON TABLE public.course_concept_exclusions TO service_role;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        RETURN;
    END IF;
    EXECUTE $q$DROP POLICY IF EXISTS course_concept_exclusions_select_own ON public.course_concept_exclusions$q$;
    EXECUTE $q$CREATE POLICY course_concept_exclusions_select_own ON public.course_concept_exclusions FOR SELECT TO authenticated
            USING (user_id = (SELECT app_auth.uid()))$q$;
    EXECUTE $q$DROP POLICY IF EXISTS course_concept_exclusions_insert_own ON public.course_concept_exclusions$q$;
    EXECUTE $q$CREATE POLICY course_concept_exclusions_insert_own ON public.course_concept_exclusions FOR INSERT TO authenticated
            WITH CHECK (user_id = (SELECT app_auth.uid()))$q$;
    EXECUTE $q$DROP POLICY IF EXISTS course_concept_exclusions_update_own ON public.course_concept_exclusions$q$;
    EXECUTE $q$CREATE POLICY course_concept_exclusions_update_own ON public.course_concept_exclusions FOR UPDATE TO authenticated
            USING (user_id = (SELECT app_auth.uid()))
            WITH CHECK (user_id = (SELECT app_auth.uid()))$q$;
    EXECUTE $q$DROP POLICY IF EXISTS course_concept_exclusions_delete_own ON public.course_concept_exclusions$q$;
    EXECUTE $q$CREATE POLICY course_concept_exclusions_delete_own ON public.course_concept_exclusions FOR DELETE TO authenticated
            USING (user_id = (SELECT app_auth.uid()))$q$;
    EXECUTE $q$GRANT SELECT, INSERT, UPDATE, DELETE ON public.course_concept_exclusions TO authenticated$q$;
END $$;
