-- ============================================================================
-- ROLLBACK for storage_lockdown.sql (#231) — EMERGENCY USE ONLY
-- Restores the pre-hardening (public) state. Run only the phase(s) you applied.
-- ============================================================================

-- ── Rollback Phase 1 — application_resumes back to public ───────────────────
UPDATE storage.buckets SET public = true WHERE id = 'application_resumes';

-- ── Rollback Phase 2 — issues-media-files back to public + anon policies ─────
-- Only needed if Phase 2 was applied.
-- BEGIN;
-- UPDATE storage.buckets SET public = true WHERE id = 'issues-media-files';
-- CREATE POLICY "Allow public read" ON storage.objects FOR SELECT TO public
--   USING (bucket_id = 'issues-media-files');
-- CREATE POLICY "Allow uploads" ON storage.objects FOR INSERT TO public
--   WITH CHECK (bucket_id = 'issues-media-files');
-- COMMIT;
