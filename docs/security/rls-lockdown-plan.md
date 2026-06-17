# Project-wide RLS lockdown — apply & verification plan (#231)

**Status: DRAFT for review. Do not apply until reviewed.** One-time DDL, not a
`#197`-runner migration. Scripts: `backend/db/security/rls_lockdown.sql` (apply),
`backend/db/security/rls_lockdown_rollback.sql` (emergency revert).

## Why this is safe for the backend
The backend authenticates to Supabase with `SUPABASE_SERVICE_KEY` → the
`service_role`, which has **`rolbypassrls = true`** (verified live: `SELECT
rolname, rolbypassrls FROM pg_roles` → `service_role=t`, `anon=f`,
`authenticated=f`). RLS does not apply to row-bypass roles, so **every backend
query keeps working unchanged**. RLS only constrains `anon`/`authenticated`,
which is exactly the public-anon-key path we're closing.

## Expected breakage (accepted)
Anon realtime on `room_messages` stops delivering once RLS is on / anon DML is
revoked. This stays broken until the **option (a)** JWT bridge lands
(`docs/security/realtime-jwt-bridge-design.md`). Per decision, the full-DB
exposure outranks live chat updates. The #230 display fix already re-fetches via
the (service-role) REST endpoint, so chat still works on load/refresh — only the
live push is paused.

## Test-first on a branch (if available)
Supabase branching wasn't reachable via the MCP for this project (`list_branches`
errored), so it may be on a plan/permission that doesn't expose it. If you have
branching:
1. Create a dev branch in the dashboard.
2. Run `rls_lockdown.sql` against the branch.
3. Run the verification below pointed at the branch.
4. Merge the branch (or apply the same SQL to prod) once green.

If branching is unavailable: apply to prod during a low-traffic window with
`rls_lockdown_rollback.sql` open and ready. The change is transactional
(`BEGIN/COMMIT`) and fast (DDL only, no table rewrites).

## Pre-apply snapshot (record for diffing)
```sql
SELECT count(*) FILTER (WHERE relrowsecurity) AS rls_on,
       count(*) FILTER (WHERE NOT relrowsecurity) AS rls_off
FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind='r';
-- expected before: rls_on=2, rls_off=38
```

## Apply
Run `backend/db/security/rls_lockdown.sql`.

## Post-apply verification checklist
1. **RLS now on for all public tables:**
   ```sql
   SELECT count(*) FILTER (WHERE NOT relrowsecurity) AS still_off
   FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind='r';
   -- expect: still_off = 0
   ```
2. **anon has no table DML left (RECURRING — wire into CI/cron as a blocking check):**
   ```sql
   SELECT count(*) AS anon_grants
   FROM information_schema.role_table_grants
   WHERE table_schema='public' AND grantee='anon'
     AND privilege_type IN ('SELECT','INSERT','UPDATE','DELETE');
   -- expect: anon_grants = 0
   ```
   This must not just pass once. The `ALTER DEFAULT PRIVILEGES ... REVOKE ...
   FROM anon` in `rls_lockdown.sql` is scoped per creating role, so a future
   migration that creates a table as a role NOT covered by a `FOR ROLE` clause
   will silently re-grant anon and reopen the hole with no error. **Wire this
   exact query into CI and/or a scheduled cron as a BLOCKING assertion**
   (`anon_grants = 0`; fail/alert on any non-zero result). Concretely:
   - **CI:** run it (via the Supabase MCP `execute_sql`, `psql`, or a small
     script) on every migration/deploy that touches the schema, and fail the
     pipeline if `anon_grants > 0`.
   - **Cron:** run it on a recurring schedule (e.g. daily) against prod and
     alert on any non-zero result, to catch out-of-band table creation.
   If it ever trips, find the creating role (see the discovery query in
   `rls_lockdown.sql`) and add a matching `FOR ROLE <role>` REVOKE line there.
3. **anon is blocked at the REST endpoint** (the actual exposure): with the
   public anon key,
   ```
   curl -s -w "\n%{http_code}\n" \
     "https://jxqcmjqtjlpuxfrxmrdv.supabase.co/rest/v1/users?select=id&limit=1" \
     -H "apikey: <ANON_KEY>" -H "Authorization: Bearer <ANON_KEY>"
   ```
   **The pass condition is "no row returned", which has TWO valid shapes — do
   not misread the empty-result shape as a failure:**
   - **`401` / `403` with a `permission denied` error body** — this is what the
     anon DML **REVOKE** (plan §2) forces, and it's the strongest signal.
   - **`200` with an empty array `[]`** — this is what **RLS-enabled-with-no-policy**
     produces on its own: PostgREST runs the SELECT, RLS filters out every row,
     and you get `200 []` (NOT a 401). A `200 []` here is still a PASS — anon got
     zero data. It only becomes the *expected* result if you test RLS in
     isolation (e.g. before/without the REVOKE).
   So: PASS = a permission-denied error **OR** an empty result (`[]`); FAIL =
   any actual row data comes back. (Capture the body, not just the status code,
   precisely so `200 []` isn't mistaken for `200 <rows>`.) Repeat for
   `user_roles`, `oauth_tokens`, `messages`. After the REVOKE is applied the
   permission-denied form is expected; before it (RLS only) the `200 []` form is.
4. **Backend still works (service_role):**
   - `cd backend && python -m pytest tests/ -q` (suite is hermetic; sanity only).
   - Hit live read + write endpoints against the target DB and confirm normal
     behavior, e.g. `GET /api/auth/me` (read), a calendar/gradebook create
     (write), a notes save. All should succeed exactly as before (service_role
     bypasses RLS).
5. **Realtime is paused (expected):** open a room — messages still load and
   refresh via REST; live push is down until option (a). No errors beyond the
   subscription returning nothing.

## Rollback
If something critical breaks: run
`backend/db/security/rls_lockdown_rollback.sql` (re-grants anon, disables RLS on
the 38). ⚠️ This restores the insecure state — re-apply the lockdown + option
(a) as soon as the issue is understood.

## Follow-ups (not in this script)
- `authenticated` keeps its grants (RLS-with-no-policy denies it today); option
  (a) adds membership-scoped policies for it on `room_messages`.
- Storage hardening is a separate track. **PR #238 supersedes the storage plan**
  — treat `docs/security/storage-hardening-plan.md` as carried here in an OLD
  state and **NOT the source of truth**. #238 corrects two factual errors in the
  copy in this PR (there is no global any-bucket public INSERT — the policy is
  scoped to `issues-media-files`; and `avatars` needs no change) and adds the
  sequenced phasing. Use #238 for storage.
- The 2 already-RLS tables (`achievement_cosmetics`, `achievement_triggers`)
  have RLS on but **no policies** — confirm nothing legitimately reads them via
  anon (the backend uses service_role, so it's unaffected).
