-- ============================================================================
-- STORAGE HARDENING (#231) — DRAFT. Apply via the Supabase SQL editor AFTER
-- review, in the phased order below. Do NOT run Phase 2 until the issue-report
-- upload PR (Phase 2a) is deployed to prod. See
-- docs/security/storage-hardening-plan.md.
--
-- Confirmed live 2026-06-15: storage.objects RLS is ENABLED; service_role
-- bypasses it (backend uploads keep working). The only frontend-anon storage
-- path is issues-media-files; application_resumes has no code reader at all.
-- ============================================================================

-- ── Phase 1 — application_resumes → private (no app change; apply now) ───────
-- 13 résumés (PII) are publicly readable by URL. The bucket is written only by
-- the backend (careers.py, service-role) and read by NO code, so flipping it
-- private breaks nothing in the app.
UPDATE storage.buckets SET public = false WHERE id = 'application_resumes';
-- Rollback: UPDATE storage.buckets SET public = true WHERE id = 'application_resumes';


-- ── Phase 2 — issues-media-files → private ──────────────────────────────────
-- ⚠️ DO NOT RUN until Phase 2a (route issue-report screenshots through the
-- backend + stop frontend anon storage use) is DEPLOYED to prod. Until then,
-- this breaks issue-report screenshot upload AND display (frontend uses the
-- anon key for both).
--
-- BEGIN;
-- UPDATE storage.buckets SET public = false WHERE id = 'issues-media-files';
-- DROP POLICY "Allow uploads"     ON storage.objects;  -- anon INSERT (issues-media-files)
-- DROP POLICY "Allow public read" ON storage.objects;  -- anon SELECT (issues-media-files)
-- COMMIT;


-- ── avatars — intentionally unchanged ───────────────────────────────────────
-- Backend service-role writes, public read for <img>, no anon INSERT policy.
