-- ============================================================================
-- PROJECT-WIDE RLS LOCKDOWN  (#231)  — DRAFT, REVIEW BEFORE APPLYING
-- ============================================================================
-- WHY: 38 of 40 public tables have RLS disabled and the `anon` role holds full
-- DML (SELECT/INSERT/UPDATE/DELETE) on them. The anon key ships in the public
-- frontend bundle, so with the Data API (PostgREST) exposed, anyone with that
-- key can read/write the entire database directly — bypassing the FastAPI
-- backend and every `require_self` check (incl. self-assigning admin via
-- user_roles, reading every non-encrypted column, forging/deleting rows).
--
-- WHAT THIS DOES:
--   1. ENABLE ROW LEVEL SECURITY on every public table that lacks it (38).
--   2. REVOKE all DML from `anon` on every public table (40) — defense in depth.
-- With RLS enabled and NO policies, `anon`/`authenticated` (rolbypassrls=false)
-- are denied all rows; the backend's `service_role` (rolbypassrls=TRUE) is
-- UNAFFECTED. Verified: SELECT rolname, rolbypassrls FROM pg_roles → service_role=t.
--
-- ONE-TIME DDL — this is NOT a #197-runner migration; apply once, by hand, after
-- review. Idempotent: re-running ENABLE/REVOKE on an already-locked table is a
-- no-op.
--
-- ⚠️ EXPECTED BREAKAGE: anon realtime on room_messages stops working until the
-- option-(a) JWT bridge lands (see docs/security/realtime-jwt-bridge-design.md).
-- Accepted: the full-DB exposure outranks live chat updates.
--
-- `authenticated` grants are intentionally LEFT in place: RLS-with-no-policy
-- already denies that role today, and option (a) will add membership-scoped
-- SELECT policies for it (which still require the table-level grant to exist).
-- ============================================================================

BEGIN;

-- ── 1. Enable RLS on the 38 tables currently lacking it ─────────────────────
-- (achievement_cosmetics and achievement_triggers already have RLS enabled.)
ALTER TABLE public.achievements          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.admin_audit_log       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assignments           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cosmetics             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.course_categories     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.course_concept_stats  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.course_summary        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.courses               ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.documents             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.feedback              ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.flashcards            ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.graph_edges           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.graph_nodes           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.issue_reports         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.job_applications      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.messages              ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.newsletter_emails     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.note_concepts         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notes                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.oauth_tokens          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quiz_attempts         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quiz_context          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.role_cosmetics        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.roles                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.room_activity         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.room_members          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.room_messages         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.room_reactions        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.room_summaries        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rooms                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sessions              ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.study_guides          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_achievements     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_cosmetics        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_courses          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_roles            ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_settings         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.users                 ENABLE ROW LEVEL SECURITY;

-- ── 2. Revoke all anon DML across the public schema (all 40 tables) ─────────
-- anon should have NO table access going forward; the frontend uses anon only
-- for realtime (moving to a JWT under option (a)) and storage (separate track).
REVOKE SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public FROM anon;

-- Also stop FUTURE tables from silently re-granting anon (Supabase default
-- ALTER DEFAULT PRIVILEGES grants to anon). Without this, the next table
-- created reopens the hole.
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM anon;

COMMIT;

-- Post-apply verification lives in docs/security/rls-lockdown-plan.md.
