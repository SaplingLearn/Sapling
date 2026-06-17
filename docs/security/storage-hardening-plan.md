# Storage hardening — PR-plan (#231)

> ⚠️ **SUPERSEDED BY PR #238 — do not use this file as the source of truth for
> storage.** This copy is an OLD version of the storage plan. PR #238 re-verified
> the live state and corrected two factual errors below:
> 1. The public INSERT policy is **not** a global any-bucket upload — it is
>    scoped `WITH CHECK bucket_id = 'issues-media-files'`. There is **no** global
>    public-INSERT policy.
> 2. `avatars` has **no** anon INSERT policy and **needs no change** (the line
>    below implying a blanket INSERT revoke does not apply to it).
> #238 also adds the correct sequenced phasing (résumés private first; backend
> endpoint + frontend change before flipping `issues-media-files`). **For any
> storage work, follow #238**, not this file. Retained here only as the historical
> record of what #232 originally carried.

**Status: DRAFT plan for review. Nothing applied. SUPERSEDED — see #238.**

## Live findings (Sapling prod, read-only)
Buckets that actually exist (3):

| Bucket | `public` | Written by | Read by | Issue |
|---|---|---|---|---|
| `issues-media-files` (issue-report screenshots) | **true** | frontend **anon key** (`ReportIssueFlow.tsx`) | `getPublicUrl` (public) | anon upload + public read |
| `application_resumes` (résumés) | **true** | backend service key (`careers.py`) | `getPublicUrl` (public) | **résumé PII publicly readable** |
| `avatars` | true | backend service key (`storage_service.py`) | public `<img>` | intended public read |

`storage.objects` policies: `"Allow public read"` (SELECT, `{public}`, `issues-media-files`) and **`"Allow uploads"` (INSERT, `{public}`, no bucket/auth restriction)** → anyone can upload to **any** bucket, unauthenticated, unbounded (no size limit on `issues-media-files`/`application_resumes`).

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
```sql
BEGIN;
UPDATE storage.buckets SET public = false WHERE id IN ('issues-media-files','application_resumes');
DROP POLICY IF EXISTS "Allow uploads"     ON storage.objects;  -- kills the global public INSERT
DROP POLICY IF EXISTS "Allow public read" ON storage.objects;  -- issues-media-files public read
COMMIT;
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
