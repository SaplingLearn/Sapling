# Storage hardening — sequenced plan (#231)

> ⚠️ **DO NOT MERGE / DO NOT APPLY.** This is a plan/record document. The Phase 1
> SQL is an after-the-fact record (already applied); the Phase 2b SQL is a draft
> to run by hand via the Supabase SQL editor after review — nothing here should be
> "merged and run" as a migration.

**Status (per phase):**
- **Phase 1 (`application_resumes` → private): ✅ APPLIED to prod 2026-06-15.**
  Done via MCP; `public=false` verified. The SQL block in
  `backend/db/security/storage_lockdown.sql` for Phase 1 is an after-the-fact
  **record**, not a pending action.
- **Phase 2a (route issue-report screenshots through the backend): ✅ LANDED on `main`.**
  `backend/routes/feedback.py` defines `POST /api/issue-reports/screenshot`
  (auth-gated via `get_session_user_id` → 401; type/size-validated via
  `services/request_limits.read_within_limit`; service-role upload returning the
  storage **path**), `frontend/src/components/ReportIssueFlow.tsx` POSTs the file
  to that endpoint instead of using `supabase.storage`, and
  `backend/tests/test_issue_screenshot_auth.py` is the regression test. Verify
  it is deployed to prod before Phase 2b.
- **Phase 2b (`issues-media-files` → private + drop anon policies): ⏳ NOT applied — DRAFT for review.**
  This is the only remaining storage step. Run the Phase 2b SQL only after the
  deployed 2a is confirmed working in prod.

Nothing in Phase 2b has touched live. Re-confirmed live against the Sapling
project (`jxqcmjqtjlpuxfrxmrdv`) on 2026-06-15 — supersedes the earlier version
of this doc, which had two wrong claims (noted below).

> ℹ️ **Note (vs `main`):** this plan document already exists on `main` (it landed
> via the #231 remediation-plan PR), so this PR is a **modification** of the
> existing file, not a new add. The branch is also behind `main`, which already
> carries Phase 2a; the status above reflects `main`, not this stale branch.

## Live findings (re-confirmed via MCP + code)

Three buckets exist (`storage.objects` RLS is **enabled**; `service_role` bypasses it):

| Bucket | `public` | objects | Written by | Read by (in code) |
|---|---|---|---|---|
| `application_resumes` (résumé PII) | **true** | all objects are résumés¹ | backend service-role (`careers.py::_upload_resume`) | **nothing** — no code reads it |
| `issues-media-files` (issue screenshots) | **true** | issue screenshots | **frontend anon** (`ReportIssueFlow.tsx`) | **frontend anon** `getPublicUrl` |
| `avatars` | true | avatars | backend service-role (`storage_service.py`) | public `<img>` |

¹ The `application_resumes` bucket is written only by `careers.py::_upload_resume`
(service-role) and read by nothing, so **every object in it is a résumé**. The
exact object count varies as applications come in; this doc deliberately does not
pin a number — it is irrelevant to the hardening decision (the whole bucket holds
PII regardless of count).

`storage.objects` policies (only two, **both scoped to one bucket**):
- `"Allow public read"` — SELECT, `{public}`, `USING bucket_id='issues-media-files'`
- `"Allow uploads"` — INSERT, `{public}`, `WITH CHECK bucket_id='issues-media-files'`

### Corrections to the previous draft
- ❌ "a public INSERT with **no restriction** → anyone can upload to **any** bucket." **Wrong.** The INSERT policy has `WITH CHECK bucket_id='issues-media-files'`, so anon writes are scoped to that one bucket. There is **no global public-INSERT**.
- ❌ "`avatars` → revoke the blanket public INSERT." **Wrong / moot.** There is no anon INSERT policy touching `avatars`; its writes are backend service-role. **`avatars` needs no change.**
- `chat-images` / `cosmetic-assets` referenced in `Social.tsx` / `Admin.tsx` **don't exist** as buckets — those upload paths are dead code (separate cleanup; not a live exposure).

### The critical access-pattern fact (decides what can break)
The **only live frontend-anon storage path is `issues-media-files`** (ReportIssueFlow uploads with the anon key and reads via `getPublicUrl`). `application_resumes` is written by the backend (service-role) and **read by nothing in the codebase**. `avatars` is backend-written, public-read. So:
- Locking `application_resumes` breaks **no app path**.
- Locking `issues-media-files` breaks the issue-report screenshot upload+display **unless** that flow moves to the backend first.

---

## Sequenced remediation

### Phase 1 — `application_resumes` → private  ✅ APPLIED 2026-06-15
This was the priority (a bucket of résumé PII, publicly readable by URL; see the
findings table above) and the
safest: nothing in the app reads this bucket, and the upload is service-role
(unaffected by the public flag or RLS). Applied via MCP; `public=false`
confirmed. Verified closed: a fresh/cache-busted anon GET of a résumé returns
**400**, and an un-probed résumé returns **400** (origin private).

**CDN caveat (learned during verification):** Supabase fronts public objects
with Cloudflare. A résumé URL that was fetched *while the bucket was public*
stays a stale edge **HIT (200)** until it ages out — verifying via the canonical
public URL caches a stale 200. Check the origin with a **cache-buster**
(`?x=<unique>`) instead. Practical residual exposure is ~nil: the only cached
URL is the one our own verification probed, and résumé paths are random UUIDs
stored only in `job_applications`, which the RLS lockdown already made
anon-inaccessible — so cached URLs are undiscoverable. Recommend purging the
storage CDN cache (dashboard) or letting it age out for full hygiene.

- **Applied 2026-06-15 (Supabase, via MCP) — recorded here, do not re-run:**
  ```sql
  UPDATE storage.buckets SET public = false WHERE id = 'application_resumes';
  ```
- **Rollback:** `UPDATE storage.buckets SET public = true WHERE id = 'application_resumes';`
- **Why nothing breaks:** `careers.py` writes with the service key (bypasses the
  public flag); no code constructs or reads a résumé URL. Résumés remain
  reachable to the team via the Supabase dashboard / a service-role signed URL.
- **Verification (the storage equivalent of the DB curl flipping to 401):**
  pick any résumé path from `storage.objects` (bucket `application_resumes`) and
  hit its public URL:
  ```
  curl -s -o /dev/null -w "%{http_code}\n" \
    "https://jxqcmjqtjlpuxfrxmrdv.supabase.co/storage/v1/object/public/application_resumes/<path>"
  ```
  **200 before, 400 after** (private bucket no longer serves `/object/public/`).
  Confirmed: post-flip a careers upload still succeeds (service-role path
  unchanged).
- **No app deploy was required** (and none is now — this phase is complete).
- **Future (only if in-app résumé viewing is ever added):** a backend
  signed-URL endpoint. Not needed now — there is no current reader.

### Phase 2 — `issues-media-files` → private (app change SHIPPED first; Supabase flip remains)
This bucket is read+written by the frontend with the anon key, so the policy
flip must come **after** the app stops using anon storage, or issue-report
uploads/displays break. The app change (2a) has already landed on `main`; the
Supabase flip (2b) is the remaining step.

- **Step 2a — app code (PR + deploy):  ✅ LANDED on `main`.**
  - **Backend:** `POST /api/issue-reports/screenshot` exists in
    `backend/routes/feedback.py` — auth-gated (`get_session_user_id` → 401),
    validates content-type + size via `services/request_limits.read_within_limit`
    + an image allowlist (the #220/#229 pattern), uploads to `issues-media-files`
    with the service key (mirrors `careers._upload_resume`), returns the storage
    **path** (not a public URL).
  - **Frontend:** `frontend/src/components/ReportIssueFlow.tsx` no longer uses
    `supabase.storage`; it POSTs the file to that endpoint and stores the
    returned path.
  - **Regression test (failed pre-fix → 404):**
    `backend/tests/test_issue_screenshot_auth.py` asserts the endpoint requires
    auth (401) and bounds type (415) / size (413).
  - **Before 2b:** confirm 2a is **deployed to prod** and the issue-report flow
    works end-to-end (the code is on `main`; verify the deploy).
- **Step 2b — Supabase-side (dashboard SQL), AFTER 2a is verified live:**
  ```sql
  BEGIN;
  UPDATE storage.buckets SET public = false WHERE id = 'issues-media-files';
  DROP POLICY IF EXISTS "Allow uploads"     ON storage.objects;  -- anon INSERT (issues-media-files)
  DROP POLICY IF EXISTS "Allow public read" ON storage.objects;  -- anon SELECT (issues-media-files)
  COMMIT;
  ```
- **Rollback (2b):**
  ```sql
  BEGIN;
  UPDATE storage.buckets SET public = true WHERE id = 'issues-media-files';
  DROP POLICY IF EXISTS "Allow public read" ON storage.objects;
  CREATE POLICY "Allow public read" ON storage.objects FOR SELECT TO public
    USING (bucket_id = 'issues-media-files');
  DROP POLICY IF EXISTS "Allow uploads" ON storage.objects;
  CREATE POLICY "Allow uploads" ON storage.objects FOR INSERT TO public
    WITH CHECK (bucket_id = 'issues-media-files');
  COMMIT;
  ```
- **Verification:** anon upload to `issues-media-files` → **denied** (403); anon
  read of an existing object's public URL → **denied** (400/403); the backend
  upload endpoint (service-role) succeeds; a signed URL serves the object (200).

### `avatars` — NO change
Already correct: backend service-role writes, public read for `<img>`, no anon
INSERT policy. Leave it.

---

## What's app-code vs Supabase-side, and the order
1. **Phase 1 (Supabase only):** flip `application_resumes` private. ✅ **DONE — applied 2026-06-15.** No deploy.
2. **Phase 2a (app-code PR + deploy):** route issue-report screenshots through the backend; stop frontend anon storage use. ✅ **LANDED on `main`** (`feedback.py` endpoint, `ReportIssueFlow.tsx`, `test_issue_screenshot_auth.py`). Verify the prod deploy before 2b.
3. **Phase 2b (Supabase only):** flip `issues-media-files` private + drop its two `{public}` policies. *Pending — the only remaining step; run only after the deployed 2a is verified in prod.*

The SQL lives in `backend/db/security/storage_lockdown.sql` (+ rollback): the
Phase 1 block is the **applied record** (like the RLS lockdown's #232); the
Phase 2b block is **draft — do not run until reviewed**, and not until the
deployed 2a is verified in prod.

## Relationship to the existing doc on `main` and to #232

This plan document already lives on `main` (it landed via the #231
remediation-plan PR), so this PR **modifies** the existing file — there is no
add/add scenario, and the storage-plan content is already merged. The earlier
#232 branch carried its own (older) copy of this file; that copy has been
superseded by the version on `main`. There is therefore no merge-order
constraint to manage here: keep this PR scoped to the genuine delta over `main`
(the status corrections above), and let `main` remain the source of truth for the
plan content.
