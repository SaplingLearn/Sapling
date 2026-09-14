-- Repairs 0025 (#529): quiz_context lost UNIQUE (user_id, concept_node_id).
--
-- 0001_baseline_schema.sql created the table with that UNIQUE inline;
-- 0025_study_integrity.sql dropped and recreated quiz_context (lines 108-114)
-- WITHOUT it. services/quiz_context_service.py's upsert names those columns in
-- on_conflict, so PostgREST rejected every write with 42P10 — and because the
-- caller swallowed the exception, the adaptive-context loop was silently dead
-- from 2026-06-23 until this repair. Staging and prod both measured 0 rows and
-- 0 duplicate pairs on 2026-08-12 (the very first write already failed, so
-- nothing accumulated), but local replicas replay independently — dedup anyway.

-- Keep the newest row per (user_id, concept_node_id); report what was removed.
DO $$
DECLARE removed integer;
BEGIN
    DELETE FROM quiz_context qc
    USING quiz_context newer
    WHERE qc.user_id = newer.user_id
      AND qc.concept_node_id = newer.concept_node_id
      AND (qc.updated_at < newer.updated_at
           OR (qc.updated_at = newer.updated_at AND qc.id < newer.id));
    GET DIAGNOSTICS removed = ROW_COUNT;
    RAISE NOTICE 'quiz_context dedup before UNIQUE restore: % duplicate row(s) removed', removed;
END $$;

-- Idempotent restore. Named explicitly (0001's inline UNIQUE got the default
-- name quiz_context_user_id_concept_node_id_key; this repair gets its own so
-- its origin is greppable).
ALTER TABLE quiz_context
    DROP CONSTRAINT IF EXISTS quiz_context_user_concept_key;
ALTER TABLE quiz_context
    ADD CONSTRAINT quiz_context_user_concept_key UNIQUE (user_id, concept_node_id);
