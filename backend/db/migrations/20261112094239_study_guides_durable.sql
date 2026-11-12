-- Study guides become durable documents (docs/design/study-guide-redesign.md §2).
--
-- What this changes
-- -----------------
-- public.study_guides used to be a cache: one row per (user, offering, exam),
-- deleted whenever the offering's documents changed. It is now the student's
-- own document: several per class, for an exam, an assignment or the whole
-- course, kept until the student's account data is wiped. The table is
-- reshaped in place. NO ROW IS DELETED OR REWRITTEN: an existing row keeps its
-- id, content and generated_at and only gains the defaults below.
--
--   exam_id          now NULLABLE. The `assignments` row the guide is for (an
--                    exam or an assignment); NULL for a whole-course guide.
--                    Still no foreign key: the assignment can be deleted on
--                    its own and the guide stays.
--   scope_kind       'exam' | 'assignment' | 'course' (default 'exam', which is
--                    what every existing row is). 'course' exactly when
--                    exam_id IS NULL.
--   goal             'practice' | 'review' | 'exam_prep' (default 'exam_prep').
--   depth            'cram' | 'standard' | 'deep' (default 'standard').
--   use_history      whether the guide was written with the student's mastery
--                    and quiz history (default true).
--   status           'generating' | 'ready' | 'failed' (default 'ready').
--   format           1 = a pre-redesign row, content {exam, due_date, overview,
--                    topics}; 2 = models/study_guide.py::GuideContent. Default
--                    1, so every existing row, and any row written by code
--                    deployed before this migration, is marked as the old
--                    shape. services/study_guides/store.py writes 2.
--   previous_content 🔒 the content replaced by the last Update or Regenerate.
--   material_ids     JSONB array of the documents.id values the guide was made
--                    from (default []). No foreign key, like exam_id.
--   read_sections    JSONB array of the section ids marked read (default []).
--   answers          🔒 {block_id: {option_id, correct}}: the student's first
--                    answer to each check question.
--   feedback         'yes' | 'no' | NULL.
--   saved_at         set = saved to the Library.
--   generating_at    the generation claim: a run holds the guide while this is
--                    newer than five minutes (services/study_guides/store.py).
--   generated_at     now NULLABLE: NULL until the first generation finishes.
--                    The DEFAULT now() stays for code deployed before this
--                    migration; the store sends NULL itself.
--   created_at       backfilled from generated_at, then NOT NULL DEFAULT now().
--   updated_at       the same backfill; kept current by the shared
--                    set_updated_at trigger. The store uses it as the
--                    compare-and-set key for the once-only answer write.
--
-- 🔒 = encrypted by the app (services/encryption.py::encrypt_json), stored as a
-- JSON string of ciphertext, exactly like `content`. previous_content and
-- answers are NULL until first written.
--
-- Also here:
--   * the unique index study_guides_user_offering_exam_key is dropped where an
--     environment built it, and ensure_study_guides_unique_key()
--     (20261109023732) is dropped: a student may now keep several guides for
--     one exam;
--   * idx_study_guides_user (user_id) is replaced by
--     idx_study_guides_user_created (user_id, created_at DESC), which serves
--     the home's "this user's guides, newest first" and every lookup by user
--     the old index served (the users ON DELETE CASCADE, the account wipe).
--
-- Access: unchanged, and nothing to add. study_guides is owned directly (RLS
-- bucket A): the own-row policies in 20261108094129_rls_policies.sql are per
-- row, and the grants (service_role ALL; authenticated SELECT, INSERT, UPDATE,
-- DELETE in 20261108094130_rls_authenticated_grants.sql) are TABLE-level, so
-- they cover the new columns. There is no column-level grant on this table.
--
-- Deploy order: this migration BEFORE the code that reads the new columns.
-- Code deployed before it keeps working afterwards: it writes only id,
-- user_id, offering_id, exam_id, content and generated_at, and every new
-- column has a default or is nullable. (That older code still deletes an
-- offering's guides on upload until it is replaced.)
--
-- Idempotent (IF NOT EXISTS / IF EXISTS / DROP-then-ADD constraints / a
-- guarded trigger; the backfill matches no row on a second run).
--
-- Reverse (by hand, as the migration role). The new columns hold student
-- state (saved, read, answers, the previous version), and format-2 content
-- cannot be read by the pre-redesign code, so reversing loses data:
--   DROP TRIGGER IF EXISTS trg_study_guides_updated_at ON public.study_guides;
--   DROP INDEX IF EXISTS public.idx_study_guides_user_created;
--   CREATE INDEX IF NOT EXISTS idx_study_guides_user ON public.study_guides (user_id);
--   ALTER TABLE public.study_guides
--       DROP CONSTRAINT IF EXISTS study_guides_scope_kind_check,
--       DROP CONSTRAINT IF EXISTS study_guides_scope_exam_check,
--       DROP CONSTRAINT IF EXISTS study_guides_goal_check,
--       DROP CONSTRAINT IF EXISTS study_guides_depth_check,
--       DROP CONSTRAINT IF EXISTS study_guides_status_check,
--       DROP CONSTRAINT IF EXISTS study_guides_format_check,
--       DROP CONSTRAINT IF EXISTS study_guides_feedback_check,
--       DROP CONSTRAINT IF EXISTS study_guides_material_ids_check,
--       DROP CONSTRAINT IF EXISTS study_guides_read_sections_check;
--   -- Rows the old shape cannot hold have to go first (a product call):
--   --   DELETE FROM public.study_guides
--   --    WHERE format <> 1 OR exam_id IS NULL OR generated_at IS NULL;
--   ALTER TABLE public.study_guides
--       ALTER COLUMN exam_id SET NOT NULL,
--       ALTER COLUMN generated_at SET NOT NULL,
--       DROP COLUMN IF EXISTS scope_kind, DROP COLUMN IF EXISTS goal,
--       DROP COLUMN IF EXISTS depth, DROP COLUMN IF EXISTS use_history,
--       DROP COLUMN IF EXISTS status, DROP COLUMN IF EXISTS format,
--       DROP COLUMN IF EXISTS previous_content, DROP COLUMN IF EXISTS material_ids,
--       DROP COLUMN IF EXISTS read_sections, DROP COLUMN IF EXISTS answers,
--       DROP COLUMN IF EXISTS feedback, DROP COLUMN IF EXISTS saved_at,
--       DROP COLUMN IF EXISTS generating_at, DROP COLUMN IF EXISTS created_at,
--       DROP COLUMN IF EXISTS updated_at;
--   -- ensure_study_guides_unique_key(): re-create it from
--   -- 20261109023732_study_guides_unique_key.sql if the unique key is wanted.

-- ── columns ─────────────────────────────────────────────────────────────────

ALTER TABLE public.study_guides
    ALTER COLUMN exam_id DROP NOT NULL,
    ALTER COLUMN generated_at DROP NOT NULL;

ALTER TABLE public.study_guides
    ADD COLUMN IF NOT EXISTS scope_kind       TEXT     NOT NULL DEFAULT 'exam',
    ADD COLUMN IF NOT EXISTS goal             TEXT     NOT NULL DEFAULT 'exam_prep',
    ADD COLUMN IF NOT EXISTS depth            TEXT     NOT NULL DEFAULT 'standard',
    ADD COLUMN IF NOT EXISTS use_history      BOOLEAN  NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS status           TEXT     NOT NULL DEFAULT 'ready',
    ADD COLUMN IF NOT EXISTS format           SMALLINT NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS previous_content JSONB,                       -- 🔒
    ADD COLUMN IF NOT EXISTS material_ids     JSONB    NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS read_sections    JSONB    NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS answers          JSONB,                       -- 🔒
    ADD COLUMN IF NOT EXISTS feedback         TEXT,
    ADD COLUMN IF NOT EXISTS saved_at         TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS generating_at    TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS created_at       TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS updated_at       TIMESTAMPTZ;

-- An existing guide was made, and last changed, when it was generated. This
-- runs before the updated_at trigger below exists, so it stamps nothing else.
UPDATE public.study_guides
   SET created_at = COALESCE(created_at, generated_at, now()),
       updated_at = COALESCE(updated_at, generated_at, now())
 WHERE created_at IS NULL OR updated_at IS NULL;

ALTER TABLE public.study_guides
    ALTER COLUMN created_at SET DEFAULT now(),
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN updated_at SET DEFAULT now(),
    ALTER COLUMN updated_at SET NOT NULL;

-- ── checks ──────────────────────────────────────────────────────────────────

ALTER TABLE public.study_guides
    DROP CONSTRAINT IF EXISTS study_guides_scope_kind_check,
    DROP CONSTRAINT IF EXISTS study_guides_scope_exam_check,
    DROP CONSTRAINT IF EXISTS study_guides_goal_check,
    DROP CONSTRAINT IF EXISTS study_guides_depth_check,
    DROP CONSTRAINT IF EXISTS study_guides_status_check,
    DROP CONSTRAINT IF EXISTS study_guides_format_check,
    DROP CONSTRAINT IF EXISTS study_guides_feedback_check,
    DROP CONSTRAINT IF EXISTS study_guides_material_ids_check,
    DROP CONSTRAINT IF EXISTS study_guides_read_sections_check;

ALTER TABLE public.study_guides
    ADD CONSTRAINT study_guides_scope_kind_check
        CHECK (scope_kind IN ('exam', 'assignment', 'course')),
    -- A whole-course guide names no assignment; every other guide names one.
    ADD CONSTRAINT study_guides_scope_exam_check
        CHECK ((scope_kind = 'course') = (exam_id IS NULL)),
    ADD CONSTRAINT study_guides_goal_check
        CHECK (goal IN ('practice', 'review', 'exam_prep')),
    ADD CONSTRAINT study_guides_depth_check
        CHECK (depth IN ('cram', 'standard', 'deep')),
    ADD CONSTRAINT study_guides_status_check
        CHECK (status IN ('generating', 'ready', 'failed')),
    ADD CONSTRAINT study_guides_format_check
        CHECK (format IN (1, 2)),
    ADD CONSTRAINT study_guides_feedback_check
        CHECK (feedback IS NULL OR feedback IN ('yes', 'no')),
    ADD CONSTRAINT study_guides_material_ids_check
        CHECK (jsonb_typeof(material_ids) = 'array'),
    ADD CONSTRAINT study_guides_read_sections_check
        CHECK (jsonb_typeof(read_sections) = 'array');

COMMENT ON TABLE public.study_guides IS
    'A student''s study guides: durable, several per class, for an exam, an assignment or the whole course. content, previous_content and answers are app-encrypted.';
COMMENT ON COLUMN public.study_guides.exam_id IS
    'The assignment the guide is for (an exam or an assignment), or NULL for a whole-course guide. No FK: the assignment can be deleted independently.';
COMMENT ON COLUMN public.study_guides.format IS
    '1 = pre-redesign content {exam, due_date, overview, topics}; 2 = GuideContent (models/study_guide.py).';
COMMENT ON COLUMN public.study_guides.generating_at IS
    'The generation claim: held while newer than five minutes; NULL when no run holds the guide.';
COMMENT ON COLUMN public.study_guides.generated_at IS
    'When the last generation finished; NULL until the first one does.';

-- ── the per-exam unique key goes ────────────────────────────────────────────

DROP INDEX IF EXISTS public.study_guides_user_offering_exam_key;
DROP FUNCTION IF EXISTS public.ensure_study_guides_unique_key();

-- ── indexes and the updated_at trigger ──────────────────────────────────────

-- The home lists one user's guides newest first; the users ON DELETE CASCADE
-- and the account wipe look rows up by user alone (the leading column).
CREATE INDEX IF NOT EXISTS idx_study_guides_user_created
    ON public.study_guides (user_id, created_at DESC);
DROP INDEX IF EXISTS public.idx_study_guides_user;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
         WHERE tgname = 'trg_study_guides_updated_at'
           AND tgrelid = 'public.study_guides'::regclass
    ) THEN
        CREATE TRIGGER trg_study_guides_updated_at BEFORE UPDATE ON public.study_guides
            FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
    END IF;
END $$;
