-- M8 (sec2 AI hardening): "common class mistakes" must not come from one student.
--
-- `offering_concept_stats.common_misconceptions` / `prerequisite_gaps` are read
-- by every classmate's quiz agent (agents/tools/graph_read.py::
-- read_misconceptions_for_course). They were built from each student's quiz
-- notes with no floor on how many students said the same thing, so one
-- student's written quiz answers could write what the class's quiz agent
-- treats as a shared misconception.
--
-- services/course_context_service.py now keeps an entry only when at least
-- MIN_MISTAKE_CONTRIBUTORS (3) distinct students' notes contain it, and stamps
-- the floor it used on the row here. The reader serves a row's arrays only
-- when this column is at or above that floor, so a row aggregated before this
-- change (NULL) is never served; the next aggregation pass rebuilds it under
-- the rule.
--
-- Additive and nullable: safe in either deploy order. Code ahead of the
-- migration: the upsert names an unknown column and the refresh fails (the job
-- retries), and the reader's filter on it fails, which the tool degrades to
-- "no class misconceptions". Migration ahead of code: old code never writes
-- the column, so every row stays NULL and the new reader serves nothing until
-- the new aggregation runs. Neither order serves an n=1 mistake.
--
-- The table already has RLS on, its own enrolled-student SELECT policy
-- (20261108094129_rls_policies.sql) and no anon access; a new column inherits
-- all of it, and it holds a small integer, nothing personal.
ALTER TABLE offering_concept_stats
    ADD COLUMN IF NOT EXISTS min_mistake_contributors SMALLINT;

COMMENT ON COLUMN offering_concept_stats.min_mistake_contributors IS
    'Distinct-student floor the misconception/weak-area arrays were built under '
    '(services/course_context_service.py::MIN_MISTAKE_CONTRIBUTORS). NULL = built '
    'before the floor existed; never served.';
