-- 0029: Storage hardening (#231) — final lockdown of the last anon storage surface.
--
-- Most of #231 already shipped: issue-report screenshots now upload via the
-- auth-gated backend endpoint POST /api/issue-reports/screenshot (service role,
-- size + mime validated; routes/feedback.py); the frontend no longer uses the
-- anon storage client (ReportIssueFlow.tsx); and application_resumes is already
-- private (backend/service-key upload via routes/careers.py, returns a path).
-- `avatars` stays public (intended public read). This migration closes what's left.
--
-- Verified against prod (read-only) before writing:
--   * storage.buckets: issues-media-files public=true; application_resumes
--     ALREADY public=false; avatars public=true.
--   * storage.objects policies (both scoped to issues-media-files):
--     "Allow public read" (anon SELECT) and "Allow uploads" (anon INSERT).
-- So the UPDATE on application_resumes is a no-op, and the app's live paths
-- (service-role upload + dashboard/signed-URL review) do not depend on the anon
-- policies being dropped.
--
-- Idempotent / safe across environments: the WHERE-clauses affect zero rows
-- where a bucket is absent (local/fresh), and DROP POLICY IF EXISTS no-ops when
-- the policy is already gone.
--
-- PRIVILEGES: this touches the Supabase-managed `storage` schema. The migrate
-- runner connects over SUPABASE_DB_URL as the DB owner (`postgres`), which on
-- Supabase can alter storage.buckets and drop storage.objects policies (same
-- role the dashboard SQL editor uses). If a locked-down environment's role lacks
-- those privileges, apply this file with a storage-privileged role instead.

-- 1. Make the screenshot bucket private. application_resumes is already private
--    (kept here so a fresh environment converges to the same end state).
update storage.buckets
   set public = false
 where id in ('issues-media-files', 'application_resumes');

-- 2. Defence in depth: cap size + restrict mime on issues-media-files to match
--    the upload endpoint (MAX_SCREENSHOT_BYTES = 5 MB; ALLOWED_SCREENSHOT_TYPES).
--    Existing objects are grandfathered; the limit applies to new uploads.
update storage.buckets
   set file_size_limit = 5242880,  -- 5 MB
       allowed_mime_types = array['image/png', 'image/jpeg', 'image/webp', 'image/gif']
 where id = 'issues-media-files';

-- 3. Drop the anonymous storage.objects policies the app no longer relies on.
--    Uploads go through the service-role backend endpoint; screenshots are
--    reviewed via the Supabase dashboard / a backend signed URL — never a public
--    URL — so removing anon SELECT/INSERT breaks nothing.
drop policy if exists "Allow uploads"     on storage.objects;  -- anon INSERT into issues-media-files
drop policy if exists "Allow public read" on storage.objects;  -- anon SELECT on issues-media-files
