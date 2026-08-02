-- 0037: persist the Class Intel opt-out (#72).
--
-- The "Class intel" toggle (frontend SharedContextToggle) lived only in
-- localStorage and only gated the READ path — a per-request
-- use_shared_context flag on the tutor/quiz calls. The WRITE path,
-- course_context_service.update_course_context, kept aggregating EVERY
-- enrolled student's graph into offering_concept_stats / offering_summary,
-- so an opted-out student's mastery data still fed the shared class
-- aggregates. Option 1 on the issue: make the opt-out a persisted per-user
-- preference and enforce it at that single write chokepoint.
--
-- DEFAULT true = opted in, preserving current behavior for everyone who has
-- never touched the toggle; the service also treats a missing user_settings
-- row as opted in, matching this default.
ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS share_class_context BOOLEAN NOT NULL DEFAULT true;
