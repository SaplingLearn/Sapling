-- Library folders: per-student organisation of their own uploaded documents.
--
-- What this adds
-- --------------
-- public.library_folders: a named folder owned by one student, optionally
-- pinned to an abstract course (courses.id). The Library explorer nests a
-- course's folders under that course; a NULL course_id is a folder under
-- "Uncategorized".
--
-- documents.folder_id: which of the owner's folders a document sits in.
-- A documents row is already per-student (documents.user_id; the shared course
-- corpus lives in course_chunks, not here), so folder membership can live on
-- the row itself rather than in a per-user join table. ON DELETE SET NULL:
-- deleting a folder leaves its documents in their course.
--
-- The route layer (routes/library_folders.py) checks the folder and the
-- document belong to the same student and the same course before setting
-- folder_id; Postgres cannot express that cross-row rule as a plain FK.
--
-- RLS (bucket A, owned directly): own-row policies on library_folders keyed on
-- app_auth.uid(), matching the step-2b shape, plus the table grants and the
-- documents.folder_id column UPDATE grant `authenticated` needs once the
-- db_user_scope flag puts Library requests under the student's own token.
-- tests/integration/test_rls_lockdown_db.py and test_rls_policies_db.py list
-- the table in bucket A and folder_id among the documents UPDATE columns.
--
-- Reverse:
--   ALTER TABLE public.documents DROP COLUMN IF EXISTS folder_id;
--   DROP TABLE IF EXISTS public.library_folders;

CREATE TABLE IF NOT EXISTS public.library_folders (
    id          TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id     TEXT NOT NULL REFERENCES public.users(id)   ON DELETE CASCADE,
    course_id   TEXT          REFERENCES public.courses(id) ON DELETE SET NULL,
    name        TEXT NOT NULL CHECK (char_length(btrim(name)) BETWEEN 1 AND 120),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS library_folders_user_idx ON public.library_folders (user_id);

ALTER TABLE public.documents
    ADD COLUMN IF NOT EXISTS folder_id TEXT
        REFERENCES public.library_folders(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS documents_folder_idx
    ON public.documents (folder_id) WHERE folder_id IS NOT NULL;

ALTER TABLE public.library_folders ENABLE ROW LEVEL SECURITY;

-- Policies and grants only where the step-2a helpers and role exist (they do on
-- Supabase and the local stack; a bare Postgres replay skips them, like 2b/2c).
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated')
     AND EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'app_auth') THEN
    EXECUTE $q$DROP POLICY IF EXISTS library_folders_select_own ON public.library_folders$q$;
    EXECUTE $q$CREATE POLICY library_folders_select_own ON public.library_folders FOR SELECT TO authenticated
            USING (user_id = (SELECT app_auth.uid()))$q$;
    EXECUTE $q$DROP POLICY IF EXISTS library_folders_insert_own ON public.library_folders$q$;
    EXECUTE $q$CREATE POLICY library_folders_insert_own ON public.library_folders FOR INSERT TO authenticated
            WITH CHECK (user_id = (SELECT app_auth.uid()))$q$;
    EXECUTE $q$DROP POLICY IF EXISTS library_folders_update_own ON public.library_folders$q$;
    EXECUTE $q$CREATE POLICY library_folders_update_own ON public.library_folders FOR UPDATE TO authenticated
            USING (user_id = (SELECT app_auth.uid()))
            WITH CHECK (user_id = (SELECT app_auth.uid()))$q$;
    EXECUTE $q$DROP POLICY IF EXISTS library_folders_delete_own ON public.library_folders$q$;
    EXECUTE $q$CREATE POLICY library_folders_delete_own ON public.library_folders FOR DELETE TO authenticated
            USING (user_id = (SELECT app_auth.uid()))$q$;
    EXECUTE $q$GRANT SELECT, INSERT, UPDATE, DELETE ON public.library_folders TO authenticated$q$;
    EXECUTE $q$GRANT UPDATE (folder_id) ON public.documents TO authenticated$q$;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
    EXECUTE $q$GRANT ALL ON TABLE public.library_folders TO service_role$q$;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    EXECUTE $q$REVOKE ALL ON public.library_folders FROM anon$q$;
  END IF;
END
$$;
