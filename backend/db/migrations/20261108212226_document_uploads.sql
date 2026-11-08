-- Staged uploads for the queued upload pipeline (Trov #116, plan phase 2).
--
-- What this adds
-- --------------
-- public.document_uploads: one row per upload handed to the job queue
-- (`document.process`, services/document_jobs.py). The upload request stores
-- the file here, enqueues the job, and the SSE stream polls this row for
-- progress; the worker (`python -m worker`) reads the file back, extracts
-- the text, runs the document agents, persists the `documents` row and
-- records the outcome here. Nothing writes to it unless the `jobs_queue`
-- flag is on for the uploader (services/feature_flags.py, default off).
--
-- Why a table and not Supabase Storage: the worker is a separate process and
-- needs the raw bytes; a Storage bucket would be a new bucket + policies,
-- which is a bigger, separate decision. Bytes are held only until the upload
-- reaches a terminal stage — the worker (or the API, on its inline fallback)
-- sets `file_data` to NULL when it is done with them — and the API only
-- queues files up to a size cap (services/document_jobs.py,
-- QUEUED_UPLOAD_MAX_BYTES); larger ones run inline as before.
--
-- Columns 🔒 are column-encrypted by the backend (services/encryption.py):
--   file_data  base64(nonce || AES-GCM(raw file bytes))  (encrypt_bytes)
--   result     encrypt_json({"result": <DocumentProcessingResult>, "categories": [...]})
-- `progress` is plaintext and holds counts and the category label only
-- (char_count, category, is_syllabus, concept_count, merged_count) — the same
-- facts `documents.category` and the `document.*` events already store in
-- plaintext; never text, summary or concept names.
--
-- stage (one-way except the documented retry):
--   queued              waiting for a worker
--   extracting          worker claimed it; text extraction (OCR) running
--   classifying         classifier agent running
--   extracting_concepts summary/concept/syllabus agents running
--   merging             concepts being merged into the course graph
--   saving              persisting the documents row
--   done                the documents row exists (document_id); terminal
--   failed              terminal; error_code says why (fixed codes only)
--   inline              the API took the upload back (no worker picked it up
--                       in time) and ran it in the request; terminal here
-- A client retry with the same X-Request-ID on a `failed`/`inline` row resets
-- it to `queued` with the re-sent file (compare-and-swap on the stage).
--
-- (user_id, request_id) is unique: the request id is the idempotency key, as
-- it is for `documents` (0018).
--
-- Access: service-only (RLS bucket E, docs/security/rls-step2-plan.md): RLS
-- on, no policies, nothing granted to anon/authenticated. Only the backend
-- (service_role) reads or writes it.
--
-- Idempotent (IF NOT EXISTS / guarded DO blocks), additive, touches no
-- existing data.
--
-- Reverse (by hand, as the migration role). Turn `jobs_queue` off first and
-- let in-flight uploads finish:
--   SELECT stage, count(*) FROM public.document_uploads GROUP BY 1;
--   DROP TABLE IF EXISTS public.document_uploads;
-- (Only staged uploads and their encrypted outcomes are lost; every finished
-- upload is a `documents` row.)

CREATE TABLE IF NOT EXISTS public.document_uploads (
    id           TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id      TEXT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    offering_id  TEXT NOT NULL REFERENCES public.course_offerings(id) ON DELETE CASCADE,
    course_id    TEXT NOT NULL,
    request_id   TEXT NOT NULL,
    file_name    TEXT NOT NULL,
    content_type TEXT,
    file_size    INTEGER NOT NULL DEFAULT 0,
    file_data    TEXT,            -- 🔒 cleared at a terminal stage
    stage        TEXT NOT NULL DEFAULT 'queued',
    progress     JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_code   TEXT,
    document_id  TEXT REFERENCES public.documents(id) ON DELETE SET NULL,
    result       TEXT,            -- 🔒
    job_id       UUID,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT document_uploads_stage_check CHECK (stage IN (
        'queued', 'extracting', 'classifying', 'extracting_concepts',
        'merging', 'saving', 'done', 'failed', 'inline')),
    CONSTRAINT document_uploads_error_code_check
        CHECK (error_code IS NULL OR error_code ~ '^[a-z_]{1,40}$'),
    CONSTRAINT document_uploads_file_size_check CHECK (file_size >= 0),
    CONSTRAINT document_uploads_user_request_key UNIQUE (user_id, request_id)
);

COMMENT ON TABLE public.document_uploads IS
    'Uploads staged for the document.process job (#116). Service-only. file_data/result are column-encrypted; file_data is cleared at a terminal stage.';
COMMENT ON COLUMN public.document_uploads.progress IS
    'Plaintext: counts and the category label only, never document content.';

CREATE INDEX IF NOT EXISTS idx_document_uploads_user ON public.document_uploads (user_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
         WHERE tgname = 'trg_document_uploads_updated_at'
           AND tgrelid = 'public.document_uploads'::regclass
    ) THEN
        CREATE TRIGGER trg_document_uploads_updated_at BEFORE UPDATE ON public.document_uploads
            FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
    END IF;
END $$;

-- ── access: service-only ────────────────────────────────────────────────────

ALTER TABLE public.document_uploads ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.document_uploads FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT ALL ON TABLE public.document_uploads TO service_role;
    END IF;
END $$;
