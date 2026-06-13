-- ============================================================================
-- ROLLBACK for rls_lockdown.sql (#231)  — ⚠️ EMERGENCY USE ONLY
-- ============================================================================
-- This RESTORES THE INSECURE PRE-LOCKDOWN STATE (anon regains full DML; RLS off
-- on the 38 tables). Use ONLY if the lockdown breaks something critical and you
-- must revert immediately. Re-apply rls_lockdown.sql + the option-(a) policies
-- as soon as possible afterward.
--
-- Restores exactly what the lockdown changed:
--   - re-grants anon DML across the public schema (+ default privileges),
--   - disables RLS on the 38 tables that had it OFF before the lockdown.
-- It deliberately does NOT touch achievement_cosmetics / achievement_triggers,
-- which already had RLS enabled pre-lockdown.
-- ============================================================================

BEGIN;

-- Re-grant anon DML (the Supabase pre-lockdown default).
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO anon;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO anon;

-- Disable RLS on the 38 tables that were OFF before the lockdown.
ALTER TABLE public.achievements          DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.admin_audit_log       DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.assignments           DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.cosmetics             DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.course_categories     DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.course_concept_stats  DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.course_summary        DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.courses               DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.documents             DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.feedback              DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.flashcards            DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.graph_edges           DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.graph_nodes           DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.issue_reports         DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.job_applications      DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.messages              DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.newsletter_emails     DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.note_concepts         DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.notes                 DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.oauth_tokens          DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.quiz_attempts         DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.quiz_context          DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.role_cosmetics        DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.roles                 DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.room_activity         DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.room_members          DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.room_messages         DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.room_reactions        DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.room_summaries        DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.rooms                 DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.sessions              DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.study_guides          DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_achievements     DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_cosmetics        DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_courses          DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_roles            DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_settings         DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.users                 DISABLE ROW LEVEL SECURITY;

COMMIT;
