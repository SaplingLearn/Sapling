-- 20261108163653_learning_llm_usage_course_id.sql
-- Learning loop spec §13 A137: the course an llm_usage row's run served, when
-- the run site knows it (agents/usage.py::record_agent_usage(course_id=…)), so
-- the admin cost-per-learning-gain report (learning/cost_per_gain.py) can put
-- every loop dollar on its course.
--
-- A loop session names its course (sessions.offering_id), so a session row was
-- attributable already through its session_id (A92). The runs with no session
-- were not: check-item drafting and its alignment and key checks (course
-- assets, run on upload or by the backfill) and the post-test's grade and
-- decisions. Those run sites now record the abstract course id their deps
-- carry (the course the graph, the items and posttest_poses key on). Rows
-- written before this migration keep NULL: unknown, never inferred; the
-- report counts them as unattributed.
--
-- Additive and nullable: no default, no backfill, no index (the report reads a
-- created_at window). llm_usage's RLS and grants are table-level (0035) and
-- cover the new column unchanged. A deploy that reaches a database before this
-- migration drops the column from its inserts and retries
-- (services/events_service.py _OPTIONAL_COLUMNS), so no usage row is lost and
-- the budget caps keep reading every row; the admin report reads without it.
ALTER TABLE llm_usage ADD COLUMN IF NOT EXISTS course_id text;

-- PostgREST serves the new column from its schema cache; reload it (a no-op with
-- no listener).
NOTIFY pgrst, 'reload schema';
