-- Library redesign: document folders, and editable per-document notes.
--
-- What this adds
-- --------------
-- public.document_folders: a named folder INSIDE a course, holding documents.
--   course_id  the ABSTRACT course (the id the HTTP boundary speaks), like
--              flashcard_sets.course_id, or NULL for a folder the student made
--              while no course was open ("No Course" in the Library). ON DELETE
--              CASCADE when set: a folder without its course means nothing.
--   name       PLAINTEXT label the student typed, like flashcard_sets.name.
--
-- public.documents.folder_id: which folder a document sits in, or NULL for
--   "loose in the course". ON DELETE SET NULL — deleting a folder keeps every
--   document, it only stops being filed (the Library says so in its toast).
--
-- public.documents.page_count: the Library's Pages column and its "Most Pages"
--   sort. Counted from the file itself at upload; NULL where it cannot be.
--
-- public.document_notes: the generated-then-edited notes document that the new
--   /library/{id}/notes page reads and autosaves. One row per (document, user).
--   title    🔒 the student's heading for the notes (defaults to the file name)
--   content  🔒 the editor's HTML body
--   final    read-only flag the "Finalize"/"Edit" header button toggles
-- Both 🔒 columns are AES-GCM encrypted by services/documents/doc_notes.py, the
-- same boundary services/notes_service.py keeps for `notes`. They hold study
-- content the student wrote, so they are encrypted — unlike the plaintext
-- labels above. services/account_bundle.py::ENCRYPTED gains an entry for them.
--
-- Access: both tables are owned directly (RLS bucket A,
-- docs/security/rls-step2-plan.md §1.2), the same shape as `flashcard_sets`:
-- RLS on; anon gets nothing; `authenticated` gets SELECT/INSERT/UPDATE/DELETE
-- behind own-row policies on `user_id = (SELECT app_auth.uid())`; service_role
-- gets ALL.
--
-- Idempotent (IF NOT EXISTS / guarded DO blocks / DROP POLICY IF EXISTS),
-- additive, touches no existing row.
--
-- Reverse (by hand, as the migration role):
--   ALTER TABLE public.documents DROP COLUMN IF EXISTS folder_id;
--   DROP TABLE IF EXISTS public.document_folders;
--   ALTER TABLE public.documents DROP COLUMN IF EXISTS page_count;
--   DROP TABLE IF EXISTS public.document_notes;
-- (Only the filing and the edited notes are lost; no document is.)

CREATE TABLE IF NOT EXISTS public.document_folders (
    id         TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id    TEXT NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
    course_id  TEXT          REFERENCES courses(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,                       -- plaintext label
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT document_folders_name_check CHECK (btrim(name) <> '')
);

COMMENT ON TABLE public.document_folders IS
    'Named folders inside a course that hold library documents. name is a plaintext label (like flashcard_sets.name).';
COMMENT ON COLUMN public.document_folders.course_id IS
    'The abstract course the folder lives in, or NULL for a folder under "No Course".';

CREATE INDEX IF NOT EXISTS idx_document_folders_user_course
    ON public.document_folders (user_id, course_id);
CREATE INDEX IF NOT EXISTS idx_document_folders_course
    ON public.document_folders (course_id);

ALTER TABLE public.documents
    ADD COLUMN IF NOT EXISTS folder_id TEXT
    REFERENCES document_folders(id) ON DELETE SET NULL;

COMMENT ON COLUMN public.documents.folder_id IS
    'The folder the document is filed in, or NULL for loose in the course. ON DELETE SET NULL: deleting a folder keeps its documents.';

CREATE INDEX IF NOT EXISTS idx_documents_folder
    ON public.documents (folder_id);

-- How many pages the uploaded file has, counted from the file itself at upload
-- time (PDF page objects, PPTX slide parts). NULL for a format with no fixed
-- pagination (DOCX repaginates at render time), for a file we could not parse,
-- and for every document uploaded before this migration -- the Library shows
-- an em dash for those and sorts them last under "Most Pages".
ALTER TABLE public.documents
    ADD COLUMN IF NOT EXISTS page_count INTEGER;

COMMENT ON COLUMN public.documents.page_count IS
    'Pages in the source file, counted at upload. NULL when unknown (DOCX, unparseable, or pre-dating the column).';

CREATE TABLE IF NOT EXISTS public.document_notes (
    document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    user_id     TEXT NOT NULL    REFERENCES users(id)     ON DELETE CASCADE,
    title       TEXT,                                 -- 🔒 AES-GCM
    content     TEXT,                                 -- 🔒 AES-GCM
    final       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.document_notes IS
    'The editable notes document for one library document. title/content are AES-GCM encrypted (study content the student wrote).';

CREATE INDEX IF NOT EXISTS idx_document_notes_user
    ON public.document_notes (user_id);

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['document_folders', 'document_notes'] LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger
             WHERE tgname = 'trg_' || t || '_updated_at'
               AND tgrelid = ('public.' || t)::regclass
        ) THEN
            EXECUTE format(
                'CREATE TRIGGER %I BEFORE UPDATE ON public.%I '
                'FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()',
                'trg_' || t || '_updated_at', t);
        END IF;
    END LOOP;
END $$;

-- ── access: owned directly (bucket A, the same shape as `flashcard_sets`) ──

ALTER TABLE public.document_folders ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.document_notes   ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    r TEXT;
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['document_folders', 'document_notes'] LOOP
        FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                EXECUTE format('REVOKE ALL ON TABLE public.%I FROM %I', t, r);
            END IF;
        END LOOP;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
            EXECUTE format('GRANT ALL ON TABLE public.%I TO service_role', t);
        END IF;
    END LOOP;
END $$;

DO $$
DECLARE
    t TEXT;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        RETURN;
    END IF;
    FOREACH t IN ARRAY ARRAY['document_folders', 'document_notes'] LOOP
        EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_select_own', t);
        EXECUTE format(
            'CREATE POLICY %I ON public.%I FOR SELECT TO authenticated '
            'USING (user_id = (SELECT app_auth.uid()))', t || '_select_own', t);
        EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_insert_own', t);
        EXECUTE format(
            'CREATE POLICY %I ON public.%I FOR INSERT TO authenticated '
            'WITH CHECK (user_id = (SELECT app_auth.uid()))', t || '_insert_own', t);
        EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_update_own', t);
        EXECUTE format(
            'CREATE POLICY %I ON public.%I FOR UPDATE TO authenticated '
            'USING (user_id = (SELECT app_auth.uid())) '
            'WITH CHECK (user_id = (SELECT app_auth.uid()))', t || '_update_own', t);
        EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_delete_own', t);
        EXECUTE format(
            'CREATE POLICY %I ON public.%I FOR DELETE TO authenticated '
            'USING (user_id = (SELECT app_auth.uid()))', t || '_delete_own', t);
        EXECUTE format(
            'GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
    END LOOP;
END $$;
