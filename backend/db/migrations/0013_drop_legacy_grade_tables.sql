-- Drop unused parallel gradebook schema before applying migration_gradebook.sql.
--
-- These three tables exist in the live DB but have NEVER been referenced from
-- the codebase (verified via repo-wide grep). They were created out-of-band
-- and overlap with the new design (course_categories, assignments.points_*,
-- user_courses.letter_scale). All three were empty at the time of this drop.
--
-- Apply order: this file first, then migration_gradebook.sql.

DROP TABLE IF EXISTS grade_items;
DROP TABLE IF EXISTS grade_categories;
DROP TABLE IF EXISTS grade_scales;
