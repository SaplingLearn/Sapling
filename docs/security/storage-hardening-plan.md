# Storage hardening — PR-plan (#231)

**Status (updated 2026-07-01): most of this plan has SHIPPED. The résumé-PII exposure is closed. Only the final SQL lockdown of `issues-media-files` remains — now in `backend/db/migrations/0029_storage_lockdown_231.sql` (pending review + apply; not yet run on prod).**

### Already shipped
- `application_resumes` is **private** (`public=false`) — uploaded backend/service-key (`careers._upload_resume`, returns a path, not a public URL). Résumé PII is no longer publicly readable.
- Issue-report screenshots upload via the **auth-gated backend endpoint** `POST /api/issue-reports/screenshot` (service role, content-type + 5 MB size validated; `routes/feedback.py`); `ReportIssueFlow.tsx` no longer uses the anon storage client.
- The anon `"Allow uploads"` INSERT policy is **scoped to `issues-media-files`** (previously global / any-bucket).

## Live findings (Sapling prod, re-verified 2026-07-01, read-only)
Buckets that actually exist (3):

| Bucket | `public` | Written by | Read by | Residual issue |
|---|---|---|---|---|
| `issues-media-files` (issue-report screenshots) | **true** | backend service key (`feedback.py`, `POST /api/issue-reports/screenshot`) | dashboard / signed URL (intended) | **still `public=true` + 2 anon policies** — the last surface (2 objects, ~7 MB) |
| `application_resumes` (résumés) | **false** ✅ | backend service key (`careers.py`) | dashboard / signed URL | **fixed** (private) |
| `avatars` | true | backend service key (`storage_service.py`) | public `<img>` | intended public read |

`storage.objects` policies (2, both scoped to `issues-media-files`): `"Allow public read"` (anon SELECT) and `"Allow uploads"` (anon INSERT). The app no longer uses either — both dropped by migration 0029.

Note: `chat-images` and `cosmetic-assets` referenced in code **do not exist** — those upload paths are dead (separate cleanup; not a live exposure).

## Target state
All storage writes go through the **backend (service_role)**; private buckets are read via **backend-generated signed URLs**; only `avatars` stays public-read. After this, there are **no anon/public storage policies** — the anon storage surface is gone.

| Bucket | public | upload path | read path |
|---|---|---|---|
| `issues-media-files` | **false** | new backend endpoint (multipart → service-key upload), reusing `request_limits.read_within_limit` + content-type allowlist (the #220/#229 pattern) | backend signed URL (admin view) |
| `application_resumes` | **false** | already backend (`careers.py`) | backend signed URL (admin view) |
| `avatars` | true | already backend | public (unchanged) |

## Changes

### SQL (review before applying)
Canonical version now lives in `backend/db/migrations/0029_storage_lockdown_231.sql`
(also adds a 5 MB size limit + mime allowlist on `issues-media-files`, matching the
upload endpoint). Apply via `python -m db.migrate` (see the migration's privilege note).
```sql
UPDATE storage.buckets SET public = false WHERE id IN ('issues-media-files','application_resumes');  -- application_resumes already false → no-op
DROP POLICY IF EXISTS "Allow uploads"     ON storage.objects;  -- anon INSERT (unused by app now)
DROP POLICY IF EXISTS "Allow public read" ON storage.objects;  -- anon SELECT on issues-media-files
```
No new storage.objects policies are needed: backend uploads/reads use `service_role` (bypasses storage RLS). `avatars` stays `public=true` so its objects remain readable without a policy.

### Backend
- New `POST /api/issue-reports/screenshot` (auth-gated via `get_session_user_id`): accepts the file, validates type+size with the shared `request_limits` helpers, uploads to `issues-media-files` with the service key (mirror `careers._upload_resume`), returns the storage path (not a public URL).
- Signed-URL helper for private buckets (admin views of screenshots/résumés): backend issues a short-TTL signed URL via the storage REST API with the service key.

### Frontend
- `ReportIssueFlow.tsx`: stop using the anon `supabase.storage` client; POST the screenshot to the new backend endpoint. Removes a direct anon-key path (also shrinks the #231 surface).
- Admin résumé/screenshot views: fetch signed URLs from the backend instead of assuming public URLs.

## Verification
- `storage.buckets`: `issues-media-files` and `application_resumes` show `public=false`; `avatars` stays `true`.
- `pg_policies` (schema `storage`): the two `{public}` policies are gone.
- Anon upload attempt → denied. Public URL to a private-bucket object → 400/403; signed URL → 200.
- Issue-report flow and résumé upload still work end-to-end via the backend; avatars still render.

## Priority
`application_resumes` (résumé PII, publicly readable) is **equal priority** to the screenshots bucket — both flip to private first; the global public-INSERT policy is dropped in the same change.
