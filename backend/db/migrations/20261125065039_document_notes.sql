-- Library redesign: editable per-document notes.
--
-- What this adds
-- --------------
-- public.document_notes: the generated-then-edited notes document that the
--   /library/{id}/notes page reads and autosaves. One row per (document, user).
--   title    🔒 the student's heading for the notes (defaults to the file name)
--   content  🔒 the editor's HTML body
--   final    read-only flag the "Finalize"/"Edit" header button toggles
-- Both 🔒 columns are AES-GCM encrypted by services/documents/doc_notes.py, the
-- same boundary services/notes_service.py keeps for `notes`. They hold study
-- content the student wrote, so they are encrypted — unlike the plaintext
-- folder labels. services/account_bundle.py::ENCRYPTED gains an entry for them.
--
-- Access: the table is owned directly (RLS bucket A,
-- docs/security/rls-step2-plan.md §1.2), the same shape as `flashcard_sets`:
-- RLS on; anon gets nothing; `authenticated` gets SELECT/INSERT/UPDATE/DELETE
-- behind own-row policies on `user_id = (SELECT app_auth.uid())`; service_role
-- gets ALL.
--
-- Idempotent (IF NOT EXISTS / guarded DO blocks / DROP POLICY IF EXISTS),
-- additive, touches no existing row.
--
-- Reverse (by hand, as the migration role):
--   DROP TABLE IF EXISTS public.document_notes;
-- (Only the edited notes are lost; no document is.)

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
    FOREACH t IN ARRAY ARRAY['document_notes'] LOOP
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

ALTER TABLE public.document_notes ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    r TEXT;
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['document_notes'] LOOP
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
    FOREACH t IN ARRAY ARRAY['document_notes'] LOOP
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
