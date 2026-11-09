-- 20261108073631_learning_item_keys.sql
-- Learning loop check-item key verification (spec §13 A124). A check item's
-- answer key is drafted by a model from classmates' uploads and nobody
-- reviews it before it grades students; wrong-answer feedback then releases
-- that key as the solution. Before a drafted item is stored, a model of
-- another family solves it blind (agents/check_items_solve.py) and code
-- compares its answer with the key (learning/item_keys.py): agreement sets
-- the existing check_items.canonical_verified; a dispute stores the item
-- HELD (key_disputed / key_unsolved in the A113 lint_flags column) — never
-- served until staff confirm or retire it in the review queue.
--
-- 1. check_items.key_checked_at — when the key check last ran on the row
--    (agreed or held). NULL = never checked: every row stored before A124
--    (and one stored without the check, which only tests and evals do). The
--    key backfill (scripts/backfill_check_item_keys.py) reads
--    `key_checked_at IS NULL` by default. A timestamp, never text, so the
--    column is plaintext. Only the generation write and the backfills touch
--    it: no request-path read selects it.
--
-- 2. check_item_audits — staff's verdict on one course item's key
--    (course_id, question_hash): 'correct', 'wrong' or 'ambiguous', from a
--    stratified audit sample (learning/item_audit.py; GET
--    /api/admin/check-items/audit/sample, scripts/audit_check_item_keys.py).
--    The latest verdict wins; key_status is the key's status at its FIRST
--    audit (verified / held / unverified), so the per-status key-error rates
--    stay a measurement of the key check. The stratum (concept_key, format,
--    difficulty) and the item id are copied in, so a verdict outlives the
--    item it judged (an item found wrong is often retired). No foreign key
--    to check_items for the same reason. Hashes, ids, enums and timestamps
--    only. Backend-only.

ALTER TABLE public.check_items ADD COLUMN IF NOT EXISTS key_checked_at timestamptz;

CREATE TABLE IF NOT EXISTS check_item_audits (
  course_id     text        NOT NULL,
  question_hash text        NOT NULL,
  item_id       text        NOT NULL,
  concept_key   text        NOT NULL,
  format        text        NOT NULL,
  difficulty    smallint    NOT NULL,
  key_status    text        NOT NULL CHECK (key_status IN ('verified','held','unverified')),
  verdict       text        NOT NULL CHECK (verdict IN ('correct','wrong','ambiguous')),
  audited_by    text        REFERENCES users(id) ON DELETE SET NULL,
  audited_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (course_id, question_hash)
);

-- Backend-only (the 20261108041639_learning_item_quality.sql idiom): RLS with
-- no policy denies every non-bypass role; service_role (the backend) bypasses
-- it. Role statements are guarded because those roles are Supabase's: a plain
-- Postgres has none of them, and an unguarded REVOKE naming one aborts the
-- whole migration.
ALTER TABLE check_item_audits ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE check_item_audits FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE check_item_audits FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE check_item_audits TO service_role;
    END IF;
END $$;

-- PostgREST resolves the new column and table from its schema cache; the
-- local stack does not reliably reload on DDL (docs/local-supabase.md). NOTIFY
-- is delivered at COMMIT and is a no-op with no listener.
NOTIFY pgrst, 'reload schema';
