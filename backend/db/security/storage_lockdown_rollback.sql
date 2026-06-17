-- ============================================================================
-- ROLLBACK for storage_lockdown.sql (#231) — EMERGENCY USE ONLY
-- Restores the pre-hardening (public) state. Run only the phase(s) you applied.
-- ============================================================================

-- ── Rollback Phase 1 — application_resumes back to public ───────────────────
-- NOTE: Phase 1 was applied to prod on 2026-06-15. This restores the pre-
-- hardening (public) state — EMERGENCY USE ONLY; running it re-exposes résumé
-- PII by URL.
BEGIN;
UPDATE storage.buckets SET public = true WHERE id = 'application_resumes';
COMMIT;

-- ── Rollback Phase 2 — issues-media-files back to public + anon policies ─────
-- Only needed if Phase 2 was applied. DROP IF EXISTS before CREATE keeps this
-- idempotent (re-running won't fail on already-present policies).
-- BEGIN;
-- UPDATE storage.buckets SET public = true WHERE id = 'issues-media-files';
-- DROP POLICY IF EXISTS "Allow public read" ON storage.objects;
-- CREATE POLICY "Allow public read" ON storage.objects FOR SELECT TO public
--   USING (bucket_id = 'issues-media-files');
-- DROP POLICY IF EXISTS "Allow uploads" ON storage.objects;
-- CREATE POLICY "Allow uploads" ON storage.objects FOR INSERT TO public
--   WITH CHECK (bucket_id = 'issues-media-files');
-- COMMIT;
