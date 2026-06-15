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

-- ── Phase 1 — application_resumes → private  [APPLIED 2026-06-15] ────────────
-- 12 résumés (PII) were publicly readable by URL. The bucket is written only by
-- the backend (careers.py, service-role) and read by NO code, so flipping it
-- private broke nothing in the app. Applied via MCP; verified public=false.
UPDATE storage.buckets SET public = false WHERE id = 'application_resumes';
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
-- DROP POLICY "Allow uploads"     ON storage.objects;  -- anon INSERT (issues-media-files)
-- DROP POLICY "Allow public read" ON storage.objects;  -- anon SELECT (issues-media-files)
-- COMMIT;


-- ── avatars — intentionally unchanged ───────────────────────────────────────
-- Backend service-role writes, public read for <img>, no anon INSERT policy.
