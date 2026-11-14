-- Saved flashcard sets (the Flashcards home screen).
--
-- What this adds
-- --------------
-- public.flashcard_sets: one row per named selection a student saved on the
-- Flashcards home screen: a course, the concept names ticked in it, and a
-- couple of study options. A set does NOT own cards: `flashcards` rows are
-- matched to a set's concepts by topic name on the client, so deleting a set
-- deletes no card and deleting a card changes no set.
--
--   course_id  the ABSTRACT course (the id the HTTP boundary speaks), not an
--              offering: a set is "these concepts of this course", whichever
--              term the cards were made in. ON DELETE CASCADE: a set without
--              its course means nothing.
--   concepts   JSONB array of concept-name strings (1-100, validated by
--              services/flashcards/sets.py; the CHECK pins only the shape).
--   options    JSONB object; the app reads `only_due` / `shuffle` (booleans)
--              and fills in defaults for a key that is absent.
--   exam_id    the assignment the set is for, or NULL. Deliberately NO foreign
--              key: an exam can be deleted on its own and the set stays (the
--              same choice as study_guides.exam_id). The app checks the
--              assignment is the caller's when it is set.
--
-- Not encrypted, on purpose: `name` and `concepts` are PLAINTEXT, like
-- flashcards.topic and graph_nodes.concept_name. They are labels (a title the
-- student typed, and concept names that already sit in plaintext on the
-- student's own graph nodes), not study content. Card text stays where it is,
-- encrypted, in flashcards.front/back. Nothing here is a 🔒 column, so
-- services/account_bundle.py::ENCRYPTED has no entry for this table.
--
-- Access: owned directly (RLS bucket A, docs/security/rls-step2-plan.md §1.2),
-- exactly like `flashcards` (20261108094129_rls_policies.sql +
-- 20261108094130_rls_authenticated_grants.sql): RLS on; anon gets nothing;
-- `authenticated` gets SELECT/INSERT/UPDATE/DELETE, each behind an own-row
-- policy on `user_id = (SELECT app_auth.uid())`; service_role gets ALL. The
-- backend reads and writes it through `table()` as the request's own scope
-- (service role with `db_user_scope` off, the student's token under enforce).
--
-- Idempotent (IF NOT EXISTS / guarded DO blocks / DROP POLICY IF EXISTS),
-- additive, touches no existing data.
--
-- Reverse (by hand, as the migration role):
--   DROP TABLE IF EXISTS public.flashcard_sets;   -- drops its policies, index and trigger
-- (Only saved selections are lost; no card is.)

CREATE TABLE IF NOT EXISTS public.flashcard_sets (
    id         TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id    TEXT NOT NULL REFERENCES public.users(id)   ON DELETE CASCADE,
    course_id  TEXT NOT NULL REFERENCES public.courses(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,                       -- plaintext label
    concepts   JSONB NOT NULL,                      -- plaintext concept names
    options    JSONB NOT NULL DEFAULT '{}'::jsonb,
    exam_id    TEXT,                                -- assignments.id; no FK on purpose
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT flashcard_sets_name_check CHECK (btrim(name) <> ''),
    CONSTRAINT flashcard_sets_concepts_check CHECK (jsonb_typeof(concepts) = 'array'),
    CONSTRAINT flashcard_sets_options_check CHECK (jsonb_typeof(options) = 'object')
);

COMMENT ON TABLE public.flashcard_sets IS
    'Saved flashcard selections: a name, a course, concept names and options. Owns no cards. name/concepts are plaintext labels (like flashcards.topic).';
COMMENT ON COLUMN public.flashcard_sets.exam_id IS
    'The assignment the set is for, or NULL. No FK: the exam can be deleted independently.';

-- The list route (a user's sets, optionally one course), the per-user cap, the
-- users ON DELETE CASCADE and the account wipe all look rows up by user.
CREATE INDEX IF NOT EXISTS idx_flashcard_sets_user_course
    ON public.flashcard_sets (user_id, course_id);
-- The courses ON DELETE CASCADE looks rows up by course alone.
CREATE INDEX IF NOT EXISTS idx_flashcard_sets_course
    ON public.flashcard_sets (course_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
         WHERE tgname = 'trg_flashcard_sets_updated_at'
           AND tgrelid = 'public.flashcard_sets'::regclass
    ) THEN
        CREATE TRIGGER trg_flashcard_sets_updated_at BEFORE UPDATE ON public.flashcard_sets
            FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
    END IF;
END $$;

-- ── access: owned directly (bucket A, the same shape as `flashcards`) ───────

ALTER TABLE public.flashcard_sets ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.flashcard_sets FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT ALL ON TABLE public.flashcard_sets TO service_role;
    END IF;
END $$;

-- Policies and grants for `authenticated`, as docs/security/rls-step2/gen_policies.py
-- writes them for every bucket-A table. Skipped on a bare Postgres without the
-- Supabase roles, like the step-2b/2c migrations.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        RETURN;
    END IF;
    EXECUTE $q$DROP POLICY IF EXISTS flashcard_sets_select_own ON public.flashcard_sets$q$;
    EXECUTE $q$CREATE POLICY flashcard_sets_select_own ON public.flashcard_sets FOR SELECT TO authenticated
            USING (user_id = (SELECT app_auth.uid()))$q$;
    EXECUTE $q$DROP POLICY IF EXISTS flashcard_sets_insert_own ON public.flashcard_sets$q$;
    EXECUTE $q$CREATE POLICY flashcard_sets_insert_own ON public.flashcard_sets FOR INSERT TO authenticated
            WITH CHECK (user_id = (SELECT app_auth.uid()))$q$;
    EXECUTE $q$DROP POLICY IF EXISTS flashcard_sets_update_own ON public.flashcard_sets$q$;
    EXECUTE $q$CREATE POLICY flashcard_sets_update_own ON public.flashcard_sets FOR UPDATE TO authenticated
            USING (user_id = (SELECT app_auth.uid()))
            WITH CHECK (user_id = (SELECT app_auth.uid()))$q$;
    EXECUTE $q$DROP POLICY IF EXISTS flashcard_sets_delete_own ON public.flashcard_sets$q$;
    EXECUTE $q$CREATE POLICY flashcard_sets_delete_own ON public.flashcard_sets FOR DELETE TO authenticated
            USING (user_id = (SELECT app_auth.uid()))$q$;
    EXECUTE $q$GRANT SELECT, INSERT, UPDATE, DELETE ON public.flashcard_sets TO authenticated$q$;
END $$;
