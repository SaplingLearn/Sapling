-- 20261108091912_learning_document_drafting.sql
-- Learning loop: per-document check-item drafting status (spec §13 A128).
--
-- Live, 2026-11-07: an upload's practice questions are drafted after the
-- upload returns (minutes of model calls on a background pool), and until the
-- first item landed the Learn screen told the student "No check items for this
-- course yet" — the same words it uses for a course that will never have any.
-- Nothing recorded that drafting was still under way, so nothing could say so.
--
-- documents.check_items_status — where the upload's drafting is:
--   'pending'      the upload hook set it (routes/documents.py::
--                  _index_then_check_items, before indexing) and no run has
--                  ended yet;
--   'done'         a run ended with every concept it attempted handled (items
--                  stored, already full, or nothing to draft from);
--   'unavailable'  a run ended with a model or check unavailable for some
--                  concept (a later run — the nightly backfill — drafts it);
--   'failed'       a run raised, or the drafting queue refused it.
-- NULL = never drafted: every row before A128, and every upload with the loop
-- off. Written by services/check_item_service.py (mark_drafting /
-- generate_for_document) and read by drafting_pending, which the loop's
-- /probe/next and /check/next ask only when the course has no servable item:
-- a 'pending' mark younger than CHECK_ITEM_DRAFT_PENDING_TTL_S makes them
-- answer `preparing`. A plaintext enum, never text from the document.
--
-- documents.check_items_at — when the status was set (the TTL's clock: a
-- 'pending' left behind by a crash or a deploy's dropped queue stops reading
-- as "preparing" once it is older than the TTL).
--
-- Additive and re-runnable. The CHECK is added NOT VALID: every existing row
-- is NULL (it cannot violate it), so no scan of documents under an ACCESS
-- EXCLUSIVE lock is needed; new writes are checked. Code may ship ahead of
-- this migration: a status write that names an absent column fails, logs a
-- WARNING and changes nothing, and the read answers "not pending".

ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS check_items_status text;
ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS check_items_at timestamptz;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'documents_check_items_status_check'
    ) THEN
        ALTER TABLE public.documents ADD CONSTRAINT documents_check_items_status_check
            CHECK (check_items_status IS NULL
                   OR check_items_status IN ('pending', 'done', 'failed', 'unavailable'))
            NOT VALID;
    END IF;
END $$;

-- The one read: a student's own pending uploads (drafting_pending). Partial,
-- so it holds only the few rows drafting right now.
CREATE INDEX IF NOT EXISTS idx_documents_check_items_pending
    ON public.documents (user_id)
    WHERE check_items_status = 'pending';

-- PostgREST resolves the new columns from its schema cache; the local stack
-- does not reliably reload on DDL (docs/local-supabase.md). NOTIFY is
-- delivered at COMMIT and is a no-op with no listener.
NOTIFY pgrst, 'reload schema';
