-- 20261108051912_learning_item_alignment.sql
-- Learning loop check-item alignment (spec §13 A119). A drafted item is
-- stored only after an alignment check (agents/check_items_verify.py) has
-- answered, per item, whether its question asks for each rubric criterion
-- and which course concept it tests; code drops an unasked criterion,
-- re-tags the item to the concept it tests, or rejects it
-- (learning/item_alignment.py). What changed is recorded in the A113
-- lint_flags column beside the linter's codes (rubric_unasked_dropped,
-- concept_retagged), so the admin review queue lists it.
--
-- check_items.aligned_at — when the alignment check last passed the row.
-- NULL = never checked: every row stored before A119 (and one stored without
-- the check, which only tests and evals do). The alignment backfill
-- (scripts/backfill_check_item_alignment.py) reads `aligned_at IS NULL` by
-- default. A timestamp, never text, so the column is plaintext. Only the
-- generation write and the backfill touch it: no request-path read selects
-- it.

ALTER TABLE public.check_items ADD COLUMN IF NOT EXISTS aligned_at timestamptz;

-- PostgREST resolves the new column from its schema cache; the local stack
-- does not reliably reload on DDL (docs/local-supabase.md). NOTIFY is
-- delivered at COMMIT and is a no-op with no listener.
NOTIFY pgrst, 'reload schema';
