-- Staged Gradescope syncs for the queued sync (Trov #116, plan phase 2).
--
-- What this adds
-- --------------
-- public.gradescope_syncs: one row per Gradescope sync handed to the job queue
-- (`gradescope.sync`, services/gradescope_jobs.py). POST
-- /api/gradescope/sync/{course} resolves the link as before, stages a row
-- here, enqueues the job and waits (bounded) on this row; the worker
-- (`python -m worker`) loads the stored credentials, logs in to Gradescope,
-- scrapes the course's assignments, upserts the gradebook, records the
-- outcome on gradescope_credentials exactly as the inline route does, and
-- writes the counts or a fixed error code here. The request answers from
-- that, with the same JSON / status codes as the inline route. Nothing writes
-- to this table unless the `jobs_queue` flag is on for the student
-- (services/feature_flags.py, default off).
--
-- Nothing secret lives here: no password, no cookie, no Gradescope text. The
-- job payload carries only this row's id; the worker reads the encrypted
-- credentials from gradescope_credentials as the inline path does.
-- `counts` is plaintext {inserted, updated, skipped, failed} integers;
-- `error_code` is a fixed code (CHECKed to [a-z_]), never an upstream message.
--
-- stage:
--   queued    waiting for a worker
--   running   a worker claimed it (compare-and-swap from queued)
--   done      finished; `counts` holds the result (terminal)
--   failed    terminal; `error_code` says why
--   inline    the API took it back (no worker picked it up within the
--             pickup grace) and ran the sync in the request (terminal here)
--
-- At most one ACTIVE (queued/running) row per (user_id, enrollment_id): a
-- second sync of the same course while one is in flight attaches to it
-- instead of starting another login + scrape.
--
-- Access: service-only (RLS bucket E, docs/security/rls-step2-plan.md): RLS
-- on, no policies, nothing granted to anon/authenticated. Only the backend
-- (service_role) reads or writes it. Rows go with the account (users CASCADE)
-- and with the enrollment (an admin wipe deletes enrollments; CASCADE).
--
-- Idempotent (IF NOT EXISTS / guarded DO blocks), additive, touches no
-- existing data.
--
-- Reverse (by hand, as the migration role). Turn `jobs_queue` off first and
-- let in-flight syncs finish:
--   SELECT stage, count(*) FROM public.gradescope_syncs GROUP BY 1;
--   DROP TABLE IF EXISTS public.gradescope_syncs;
-- (Only sync bookkeeping is lost; the synced grades live in `assignments` and
-- the last outcome on `gradescope_credentials`.)

CREATE TABLE IF NOT EXISTS public.gradescope_syncs (
    id                   TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id              TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    enrollment_id        TEXT NOT NULL REFERENCES enrollments(id) ON DELETE CASCADE,
    link_id              TEXT,
    gradescope_course_id TEXT NOT NULL,
    stage                TEXT NOT NULL DEFAULT 'queued',
    error_code           TEXT,
    counts               JSONB,
    job_id               UUID,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT gradescope_syncs_stage_check
        CHECK (stage IN ('queued', 'running', 'done', 'failed', 'inline')),
    CONSTRAINT gradescope_syncs_error_code_check
        CHECK (error_code IS NULL OR error_code ~ '^[a-z_]{1,40}$')
);

COMMENT ON TABLE public.gradescope_syncs IS
    'Gradescope syncs staged for the gradescope.sync job (#116). Service-only. No secrets: ids, counts and fixed error codes.';

CREATE UNIQUE INDEX IF NOT EXISTS gradescope_syncs_active_key
    ON public.gradescope_syncs (user_id, enrollment_id)
    WHERE stage IN ('queued', 'running');

CREATE INDEX IF NOT EXISTS idx_gradescope_syncs_user ON public.gradescope_syncs (user_id);
CREATE INDEX IF NOT EXISTS idx_gradescope_syncs_enrollment ON public.gradescope_syncs (enrollment_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
         WHERE tgname = 'trg_gradescope_syncs_updated_at'
           AND tgrelid = 'public.gradescope_syncs'::regclass
    ) THEN
        CREATE TRIGGER trg_gradescope_syncs_updated_at BEFORE UPDATE ON public.gradescope_syncs
            FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
    END IF;
END $$;

-- ── access: service-only ────────────────────────────────────────────────────

ALTER TABLE public.gradescope_syncs ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.gradescope_syncs FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT ALL ON TABLE public.gradescope_syncs TO service_role;
    END IF;
END $$;
