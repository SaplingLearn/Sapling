-- Learning loop spec §13 A116: node_mastery_events.grader_backend names the
-- provider that graded. 20260927093149_learning_grader_backend.sql allowed
-- ('deterministic','gemini','gemini_second','jev') and agents/grader.py wrote
-- 'gemini' / 'gemini_second' whatever model the grader slots ran, so with
-- SAPLING_MODEL_GRADER=claude-* every evidence row named Gemini while
-- llm_usage named Claude. The grader now writes 'claude' / 'claude_second' for
-- a run on a claude-* slot; this widens the CHECK to admit them.
--
-- Historical rows are not relabelled: a row written as 'gemini' keeps it.
-- (Rows graded by Claude before this change cannot be told apart in this
-- table; llm_usage, by session_id and time, is the only record of them.)
--
-- Matches on the constraint BODY, not an assumed name (the
-- 20260828172725_assignments_source_check_by_definition.sql lesson: a DROP by
-- the default name no-ops on a suffixed variant, and the narrow CHECK stays
-- enforced beside the wide one). The inline CHECK's default name is
-- node_mastery_events_grader_backend_check; the widened one keeps it.
--
-- Idempotent: on a re-run the first block matches nothing (every grader_backend
-- CHECK already names 'claude_second') and the guarded ADD is skipped.

DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT c.conname
    FROM pg_constraint c
    WHERE c.conrelid = 'public.node_mastery_events'::regclass
      AND c.contype = 'c'
      AND pg_get_constraintdef(c.oid) ILIKE '%grader_backend%'
      AND pg_get_constraintdef(c.oid) NOT ILIKE '%claude_second%'
  LOOP
    EXECUTE format('ALTER TABLE public.node_mastery_events DROP CONSTRAINT %I', r.conname);
    RAISE NOTICE 'dropped narrow node_mastery_events.grader_backend CHECK: %', r.conname;
  END LOOP;
END $$;

-- NOT VALID for lock behaviour, not data: the old list is a strict subset of
-- this one, so no existing row can violate it, and a validating ADD would hold
-- ACCESS EXCLUSIVE on the append-only evidence journal (every grade writes to
-- it) for a full-table scan that buys nothing. New and updated rows are
-- checked either way. The same choice 0042 and 20260828172725 make.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conrelid = 'public.node_mastery_events'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) ILIKE '%grader_backend%'
      AND pg_get_constraintdef(oid) ILIKE '%claude_second%'
  ) THEN
    ALTER TABLE public.node_mastery_events
      ADD CONSTRAINT node_mastery_events_grader_backend_check
      CHECK (grader_backend IS NULL OR grader_backend IN ('deterministic','gemini','gemini_second','claude','claude_second','jev')) NOT VALID;
  END IF;
END $$;
