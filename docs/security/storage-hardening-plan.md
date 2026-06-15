# Storage hardening — sequenced plan (#231)

**Status: DRAFT for review. Nothing applied to prod.** Re-confirmed live against
the Sapling project (`jxqcmjqtjlpuxfrxmrdv`) on 2026-06-15 — supersedes the
earlier version of this doc, which had two wrong claims (noted below).

## Live findings (re-confirmed via MCP + code)

Three buckets exist (`storage.objects` RLS is **enabled**; `service_role` bypasses it):

| Bucket | `public` | objects | Written by | Read by (in code) |
|---|---|---|---|---|
| `application_resumes` (résumé PII) | **true** | **13** | backend service-role (`careers.py::_upload_resume`) | **nothing** — no code reads it |
| `issues-media-files` (issue screenshots) | **true** | 2 | **frontend anon** (`ReportIssueFlow.tsx`) | **frontend anon** `getPublicUrl` |
| `avatars` | true | 2 | backend service-role (`storage_service.py`) | public `<img>` |

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

### Phase 1 — `application_resumes` → private (Supabase-side only, NO app change)
This is the priority (13 résumés, PII, publicly readable by URL) and the safest:
nothing in the app reads this bucket, and the upload is service-role (unaffected
by the public flag or RLS).

- **Apply (Supabase dashboard SQL editor):**
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
  Confirm a careers upload still succeeds (service-role path unchanged).
- **No app deploy required.** Can apply immediately after you approve this plan.
- **Future (only if in-app résumé viewing is ever added):** a backend
  signed-URL endpoint. Not needed now — there is no current reader.

### Phase 2 — `issues-media-files` → private (app change SHIPS + DEPLOYS first, THEN Supabase)
This bucket is read+written by the frontend with the anon key, so the policy
flip must come **after** the app stops using anon storage, or issue-report
uploads/displays break.

- **Step 2a — app code (PR + deploy), BEFORE any policy change:**
  - **Backend:** new `POST /api/issue-reports/screenshot`, auth-gated
    (`get_session_user_id` → 401), validates content-type + size via
    `services/request_limits.read_within_limit` + an image allowlist (the
    #220/#229 pattern), uploads to `issues-media-files` with the service key
    (mirror `careers._upload_resume`), returns the storage **path** (not a
    public URL). Add a signed-URL read endpoint (or include short-TTL signed
    URLs when serving `issue_reports.screenshot_urls`).
  - **Frontend:** `ReportIssueFlow.tsx` stops using `supabase.storage` (anon);
    POSTs the file to the new endpoint and stores the returned path. Any
    screenshot display fetches a signed URL from the backend.
  - **Negative test (fails pre-fix), per conventions:** the new endpoint returns
    401 unauthenticated and rejects bad type/size; and `ReportIssueFlow` no
    longer references the anon `supabase.storage` client. Scoped commit,
    sole-authored, no trailers.
  - **Deploy 2a to prod (backend + frontend) and verify the issue-report flow
    works end-to-end** before doing 2b.
- **Step 2b — Supabase-side (dashboard SQL), AFTER 2a is live:**
  ```sql
  BEGIN;
  UPDATE storage.buckets SET public = false WHERE id = 'issues-media-files';
  DROP POLICY "Allow uploads"     ON storage.objects;  -- anon INSERT (issues-media-files)
  DROP POLICY "Allow public read" ON storage.objects;  -- anon SELECT (issues-media-files)
  COMMIT;
  ```
- **Rollback (2b):**
  ```sql
  BEGIN;
  UPDATE storage.buckets SET public = true WHERE id = 'issues-media-files';
  CREATE POLICY "Allow public read" ON storage.objects FOR SELECT TO public
    USING (bucket_id = 'issues-media-files');
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
1. **Phase 1 (Supabase only):** flip `application_resumes` private. *Apply now (post-review).* No deploy.
2. **Phase 2a (app-code PR + deploy):** route issue-report screenshots through the backend; stop frontend anon storage use. Negative test.
3. **Phase 2b (Supabase only):** flip `issues-media-files` private + drop its two `{public}` policies. *Only after 2a is deployed and verified.*

The draft SQL lives in `backend/db/security/storage_lockdown.sql` (+ rollback),
kept as the applied record like the RLS lockdown's #232 — **do not merge/run
until reviewed**, and 2b not until 2a ships.
