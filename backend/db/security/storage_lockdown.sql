-- ============================================================================
-- STORAGE HARDENING (#231). State of this file:
--   * Phase 1 (application_resumes → private): ALREADY APPLIED to prod on
--     2026-06-15 — the block below is an AFTER-THE-FACT RECORD, not a pending
--     action. Do NOT re-run it expecting a change; it is kept for the audit
--     trail (same convention as the RLS lockdown #232).
--   * Phase 2 (issues-media-files → private): NOT applied — DRAFT. Run via the
--     Supabase SQL editor AFTER review, and only after the issue-report upload
--     PR (Phase 2a) is deployed to prod.
-- See docs/security/storage-hardening-plan.md for the full sequenced plan.
--
-- Confirmed live 2026-06-15: storage.objects RLS is ENABLED; service_role
-- bypasses it (backend uploads keep working). The only frontend-anon storage
-- path is issues-media-files; application_resumes has no code reader at all.
-- ============================================================================

-- ── Phase 1 — application_resumes → private  [APPLIED 2026-06-15] ────────────
-- STATUS: DONE. Applied to prod on 2026-06-15 via MCP; verified public=false.
-- This block is a record of what was run, NOT a pending step — re-running it is
-- a no-op (bucket is already private). ~12-13 résumés (PII) were publicly
-- readable by URL (observed snapshot 2026-06-15; re-verify the exact count at
-- apply time). The bucket is written only by the backend (careers.py, service-role)
-- and read by NO code, so flipping it private broke nothing in the app.
BEGIN;
UPDATE storage.buckets SET public = false WHERE id = 'application_resumes';
COMMIT;
-- Rollback: UPDATE storage.buckets SET public = true WHERE id = 'application_resumes';
--
-- CDN NOTE: Supabase fronts public objects with Cloudflare. Fresh/un-cached
-- object URLs return 400 after the flip (origin is private), but a URL that was
-- fetched WHILE public stays a stale edge HIT (200) until it ages out — so
-- verify with a cache-buster (`?x=<unique>`), not the canonical public URL, or
-- the probe itself caches a stale 200. The résumé paths are random UUIDs stored
-- only in job_applications (now anon-locked by the RLS lockdown), so cached URLs
-- are undiscoverable; purge the storage cache or let it age for full hygiene.


-- ── Phase 2 — issues-media-files → private ──────────────────────────────────
-- ⚠️ DO NOT RUN until Phase 2a (route issue-report screenshots through the
-- backend + stop frontend anon storage use) is DEPLOYED to prod. Until then,
-- this breaks issue-report screenshot upload AND display (frontend uses the
-- anon key for both).
--
-- BEGIN;
-- UPDATE storage.buckets SET public = false WHERE id = 'issues-media-files';
-- DROP POLICY IF EXISTS "Allow uploads"     ON storage.objects;  -- anon INSERT (issues-media-files)
-- DROP POLICY IF EXISTS "Allow public read" ON storage.objects;  -- anon SELECT (issues-media-files)
-- COMMIT;


-- ── avatars — intentionally unchanged ───────────────────────────────────────
-- Backend service-role writes, public read for <img>, no anon INSERT policy.
