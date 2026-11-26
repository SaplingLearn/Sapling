-- Saved study items (the Tutor session panel's "Saved" tab; Tutor redesign,
-- owner decision 2026-11-26).
--
-- What this adds
-- --------------
-- public.tutor_saved_items: one row per thing a student saved from a tutor
-- session (an explanation, a worked example) to come back to: its session,
-- the session's course, a short title and the saved text.
--
--   session_id  the session it was saved from. ON DELETE CASCADE: deleting a
--               session deletes what was saved from it.
--   course_id   the ABSTRACT course (the id the HTTP boundary speaks), copied
--               from the session when saved, so a course's saved items list
--               without a join. ON DELETE CASCADE, like flashcard_sets.
--   title       🔒 TEXT (services/encryption.py, bound to the row id).
--   content     🔒 TEXT: the saved text, a tutor message's content, which is
--               itself encrypted in messages.content.
--
-- Access: owned directly (RLS bucket A, docs/security/rls-step2-plan.md §1.2),
-- exactly like `flashcard_sets` (20261112060028): RLS on; anon gets nothing;
-- `authenticated` gets SELECT/INSERT/UPDATE/DELETE behind own-row policies on
-- `user_id = (SELECT app_auth.uid())`; service_role gets ALL.
--
-- Account data: wiped by services/account_wipe.py and copied by
-- services/account_bundle.py (re-sealed per row; course_id remapped).
--
-- Idempotent, additive, touches no existing data.
--
-- Reverse (by hand, as the migration role):
--   DROP TABLE IF EXISTS public.tutor_saved_items;   -- drops its policies and indexes

CREATE TABLE IF NOT EXISTS public.tutor_saved_items (
    id         TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id    TEXT NOT NULL REFERENCES public.users(id)    ON DELETE CASCADE,
    session_id TEXT NOT NULL REFERENCES public.sessions(id) ON DELETE CASCADE,
    course_id  TEXT          REFERENCES public.courses(id)  ON DELETE CASCADE,
    title      TEXT NOT NULL,                       -- 🔒
    content    TEXT NOT NULL,                       -- 🔒
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.tutor_saved_items IS
    'What a student saved from a tutor session (the Saved tab). title/content are encrypted (services/encryption.py).';

-- The panel lists one session's items; the milestone page and the wipe list a user's.
CREATE INDEX IF NOT EXISTS idx_tutor_saved_items_user_session
    ON public.tutor_saved_items (user_id, session_id);
-- The sessions and courses ON DELETE CASCADEs look rows up by them alone.
CREATE INDEX IF NOT EXISTS idx_tutor_saved_items_session
    ON public.tutor_saved_items (session_id);
CREATE INDEX IF NOT EXISTS idx_tutor_saved_items_course
    ON public.tutor_saved_items (course_id);

-- ── access: owned directly (bucket A, the same shape as `flashcard_sets`) ───

ALTER TABLE public.tutor_saved_items ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.tutor_saved_items FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT ALL ON TABLE public.tutor_saved_items TO service_role;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        RETURN;
    END IF;
    EXECUTE $q$DROP POLICY IF EXISTS tutor_saved_items_select_own ON public.tutor_saved_items$q$;
    EXECUTE $q$CREATE POLICY tutor_saved_items_select_own ON public.tutor_saved_items FOR SELECT TO authenticated
            USING (user_id = (SELECT app_auth.uid()))$q$;
    EXECUTE $q$DROP POLICY IF EXISTS tutor_saved_items_insert_own ON public.tutor_saved_items$q$;
    EXECUTE $q$CREATE POLICY tutor_saved_items_insert_own ON public.tutor_saved_items FOR INSERT TO authenticated
            WITH CHECK (user_id = (SELECT app_auth.uid()))$q$;
    EXECUTE $q$DROP POLICY IF EXISTS tutor_saved_items_update_own ON public.tutor_saved_items$q$;
    EXECUTE $q$CREATE POLICY tutor_saved_items_update_own ON public.tutor_saved_items FOR UPDATE TO authenticated
            USING (user_id = (SELECT app_auth.uid()))
            WITH CHECK (user_id = (SELECT app_auth.uid()))$q$;
    EXECUTE $q$DROP POLICY IF EXISTS tutor_saved_items_delete_own ON public.tutor_saved_items$q$;
    EXECUTE $q$CREATE POLICY tutor_saved_items_delete_own ON public.tutor_saved_items FOR DELETE TO authenticated
            USING (user_id = (SELECT app_auth.uid()))$q$;
    EXECUTE $q$GRANT SELECT, INSERT, UPDATE, DELETE ON public.tutor_saved_items TO authenticated$q$;
END $$;
