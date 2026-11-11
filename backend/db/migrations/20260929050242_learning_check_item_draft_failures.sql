-- 20260929050242_learning_check_item_draft_failures.sql
-- Learning loop PKG-04, post-hoc (owner decision A38, low-severity 2): bounded
-- redrafting. A concept whose drafts always fail validation was redrafted on
-- every upload and every backfill. This table counts a concept's consecutive
-- failed drafting passes against source_fp, a fingerprint of the passages the
-- pass drafted from (services/check_item_service._source_fingerprint). At
-- CHECK_ITEM_REDRAFT_MAX_FAILURES failures on an unchanged source the concept is
-- skipped; a pass that stores an item resets failures to 0, and a changed
-- source starts the count over. Course assets like check_items (A2): keyed on
-- (course_id, concept_key), no student id, no free text, nothing encrypted.
-- The bookkeeping fails open: a missing table or a failed read/write drafts.
CREATE TABLE IF NOT EXISTS check_item_draft_failures (
  course_id    text NOT NULL,
  concept_key  text NOT NULL,
  failures     int NOT NULL DEFAULT 0 CHECK (failures >= 0),
  source_fp    text NOT NULL,          -- sha256 over the drafted-from passages' ids + texts
  updated_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (course_id, concept_key)
);
