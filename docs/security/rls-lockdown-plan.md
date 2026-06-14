# Project-wide RLS lockdown — apply & verification plan (#231)

**Status: APPLIED to production 2026-06-13.** Anon is confirmed locked out
(direct REST calls to `users`/`oauth_tokens`/`user_roles`/etc. now return
`permission denied`, SQLSTATE 42501). This doc is the record of what was applied
and how it was verified. The SQL scripts (`rls_lockdown.sql` apply,
`rls_lockdown_rollback.sql` emergency revert) live in **PR #232** as the applied
record — intentionally NOT merged to `main` (the change went straight to prod;
nothing re-runs them from the repo).

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
2. **anon has no table DML left:**
   ```sql
   SELECT count(*) AS anon_grants
   FROM information_schema.role_table_grants
   WHERE table_schema='public' AND grantee='anon'
     AND privilege_type IN ('SELECT','INSERT','UPDATE','DELETE');
   -- expect: anon_grants = 0
   ```
3. **anon is blocked at the REST endpoint** (the actual exposure): with the
   public anon key,
   ```
   curl -s -o /dev/null -w "%{http_code}\n" \
     "https://jxqcmjqtjlpuxfrxmrdv.supabase.co/rest/v1/users?select=id&limit=1" \
     -H "apikey: <ANON_KEY>" -H "Authorization: Bearer <ANON_KEY>"
   ```
   Expect **401** (or `[]` with permission-denied), not a row. Repeat for
   `user_roles`, `oauth_tokens`, `messages`.
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
- Storage hardening is a separate track (`docs/security/storage-hardening-plan.md`).
- The 2 already-RLS tables (`achievement_cosmetics`, `achievement_triggers`)
  have RLS on but **no policies** — confirm nothing legitimately reads them via
  anon (the backend uses service_role, so it's unaffected).
