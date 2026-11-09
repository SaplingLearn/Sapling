# Runbook: rolling out `db_user_scope` (RLS step 2d and the shadow → enforce ladder)

Ticket #115. Design: `docs/security/rls-step2-plan.md` (§2 identity, §4.4 flag,
§6 rollout). Release context: `docs/releases/2026-11-architecture-hardening.md`
§4 (flag ladder), §7 (rollback), §8 (human-only steps).

The `db_user_scope` flag (`off` / `shadow` / `enforce`) decides whether a
request's PostgREST calls run as the service role or as the student, with a
JWT the backend mints (`db/user_jwt.py`) and RLS applied. This runbook takes it
from `off` to `enforce` at 100%, staging first, then prod.

Who does what: steps marked **[Andres]** happen in the Supabase or Railway
dashboards. Everything else is a command or a read of the shadow report.

---

## 0. Before you start

- [ ] Migrations 2a, 2b and 2c are applied on the target environment
      (`20261108092633_rls_app_auth_helpers.sql`,
      `20261108094129_rls_policies.sql`,
      `20261108094130_rls_authenticated_grants.sql`). On staging they apply
      when they merge to `main` (`migrate-staging.yml`). Check with the
      read-only `dotenv -f .env.staging run -- python scripts/migration_drift_report.py`
      (none of the three listed under PENDING), or look for the three basenames
      in `schema_migrations`.
- [ ] The code that ships the flag (#818) and this report are deployed. The flag
      is `off` (its default), so nothing changes yet.
- [ ] Supabase Auth signups are off on the project (release doc §8). It is not
      required for safety, because `app_auth.uid()` only trusts `iss=sapling-api`,
      but it removes a whole class of token.

## 1. What shadow measures (the report)

Under `shadow` every request still runs as the service role, and students
always get the service-role answer. On top of that:

| Signal | When | Kind |
|---|---|---|
| A sampled **read** (`select`, `select_with_count`, and the read-only rpc `match_course_chunks`) is run again as the student on a background pool, and the row counts and `id` sets are compared. | sampled, default 10% | `fewer_rows`, `more_rows`, `different_ids`, `error` (with HTTP `status` and PostgREST `code`) |
| A **write** (`insert`/`update`/`upsert`/`delete`) or write rpc names another user: in an owner column of the rows it writes (`user_id`, or the table's own owner column: `rooms.owner_id`, `course_chunks.uploader_id`, `room_bans.banned_by`, `users.id`; both sides of `friendships`/`friend_requests`), in an `eq.`/`in.(…)`/`neq.`/`not.` filter on one, or as an rpc user parameter (`p_user_id`, …). Writes are never run twice; this is what is known about a write without running it again. **A heuristic** — see "What an empty report does not prove" below. | every write | `write_other_user` |
| A request with **no session subject** reached the DB from a path not marked service. Under `enforce` this is a 500. | every query (counted every time; under shadow LOGGED once per route + table per process) | `no_subject` (event `db.unscoped_query`) |
| Under **enforce**, PostgREST refused a user-scoped call (403 / 42501). | every refusal | `denied` (event `db.rls_denied`) |

Every row above produces three things:

1. **One WARNING log line**, always in the same field order, never with row
   contents, raw paths or error messages (`no_subject` under shadow: the first
   occurrence per route + table per process only, so an anonymous page does not
   flood the log; the event and the tally still count every one):

   ```
   db_user_scope.divergence event=db.rls_shadow_divergence kind=fewer_rows mode=shadow method=GET route=/api/notes/{note_id} target=notes op=select status=- code=- service_rows=2 scoped_rows=1 request_id=6f0c... user=user_1234
   ```

2. **One `events` row** (category `system`), with `event_type`
   `db.rls_shadow_divergence`, `db.unscoped_query` or `db.rls_denied` and the
   same fields in `payload`. Every worker writes these, and they survive deploys.

3. **A count** in the process's in-memory tally (`db/scope_report.py`). The tally
   also keeps two things the events do not:
   - `shadow_reads` coverage counts: `sampled`, `compared`, `agreed`, `diverged`,
     `skipped_busy` (the pool already had 4 comparisons in flight) and
     `transport_error`. Use them to tell "no divergences" apart from "nothing was
     compared".
   - `unverified_writes`: every (route, table, op) write or non-read-only rpc
     that ran during shadow. Shadow cannot verify these. Under enforce they hit
     the INSERT/UPDATE/DELETE policies and grants, so each one must be covered by
     the cross-user matrix (`tests/integration/test_cross_user_matrix_db.py`)
     or by an enforce run before it reaches students.

### Reading the report

**Admin endpoint** (admin session, read-only):

```
GET /api/admin/analytics/db-scope?hours=24&limit=50
```

The simplest way to call it is to open
`https://<staging frontend>/api/admin/analytics/db-scope?hours=24` in a browser
where you are signed in as an admin. The request is same-origin, so the session
cookie is sent. The response has:

- `top`: the `events` rows from the window, grouped by (event, kind, mode,
  method, route, target, op, status, code). Each group has `count`, distinct
  `users`, `first_seen`/`last_seen` and up to 3 `sample_request_ids`. This view
  covers every worker. The grouping is done in Python, so the scan is bounded:
  at most `scan_cap` (20 000) events, newest first, and `hours` at most 168.
  `truncated: true` means the window held more and `top` covers only the newest
  `scan_cap` events — narrow `hours`, or use the SQL below, which has no cap.
  (Follow-up: a SQL `GROUP BY` function behind the endpoint would remove the cap.)
- `process`: the tally of the worker that served this request since it booted
  (`pid`, `since`). Each uvicorn worker has its own tally, so a reload can show a
  different `pid`. Its divergence rows carry the same key fields as `top`
  (normalised by one function, `scope_report.key_of`), so a group can be matched
  across the two views; an absent `status`/`code` is `null` in both.

**SQL** (Supabase SQL editor, read-only):

```sql
SELECT event_type,
       payload->>'kind'   AS kind,   payload->>'method' AS method,
       payload->>'route'  AS route,  payload->>'table'  AS target,
       payload->>'op'     AS op,
       coalesce(payload->>'status', payload->>'error') AS status,
       payload->>'code'   AS code,
       count(*) AS n, count(DISTINCT user_id) AS users, max(created_at) AS last_seen
  FROM events
 WHERE event_type IN ('db.rls_shadow_divergence', 'db.unscoped_query', 'db.rls_denied')
   AND created_at > now() - interval '24 hours'
 GROUP BY 1, 2, 3, 4, 5, 6, 7, 8
 ORDER BY n DESC
 LIMIT 50;
```

**Logs.** These lines go to stdout, which means Railway's log view. Logfire
receives spans only, not stdlib log lines, so it does not have them. Search
Railway's log explorer for the literal token `db_user_scope.divergence`. To
group a saved log export (`railway logs` output or a download):

```bash
grep -o 'db_user_scope.divergence .*' railway.log \
  | sed -E 's/ (service_rows|scoped_rows|request_id|user)=[^ ]*//g' \
  | sort | uniq -c | sort -rn | head -30
```

That gives the top divergences by event, kind, method, route, table, op and
code. To follow one occurrence, take its `request_id`: it matches the
`X-Request-ID` response header and the request's access log line.

### What an empty report does not prove

An empty `top` means none of the CHECKS fired. It does not mean enforce is safe:

- **Reads are sampled** (default 10%). Check `shadow_reads.compared`: a route
  nobody hit, or hit only unsampled, was never compared.
- **Writes are never run as the student.** `write_other_user` is a heuristic
  over owner columns, filters and rpc user parameters, and it is one-sided: a
  hit is a real signal, silence is not proof. It cannot see a write keyed by a
  row id alone (`id=eq.<another student's row>`), a table whose policy goes
  through a parent row (`messages` via `sessions`, `note_concepts`,
  `node_mastery_events`, `quiz_responses`, the enrollment-keyed gradebook
  tables), `room_members` (a room owner may remove others), or an rpc that takes
  the user any other way. Whether those writes pass WITH CHECK / USING is only
  known when they run user-scoped.
- **Every route in `unverified_writes` is exactly that: unverified.**

So the gate before ANY enforce step (admins included) is not the report alone:

1. The cross-user matrix (`tests/integration/test_cross_user_matrix_db.py`,
   parametrized over `off` and `enforce`) green in the CI **integration lane**,
   with no new `KNOWN_LEAKS` entry and every write route of `unverified_writes`
   covered by a matrix case or an explicit integration test under enforce.
2. The Chapter 1 E2E lane green.
3. Then the report clean as described in §5.

### What each kind usually means, and the fix

| Kind | Usually | Fix |
|---|---|---|
| `error` with `status=401` (code `PGRST301` or similar) | PostgREST does not trust our token: the kid/key is not current, or the key is wrong. | **Stop.** Go back to §2–§4. Under enforce this is a 503 for every student. |
| `error` with `status=403`, `code=42501` | Missing grant (2c) on that table or column. | Add the grant in a new migration, or mark the path service if it really is cross-user. |
| `error` with `status=400`, `code=22P02` | A policy casts `sub` to uuid (`auth.uid()`). | The policy must use `app_auth.uid()`. |
| `fewer_rows` / `different_ids` on the student's own pages | The SELECT policy is narrower than what the route reads. Often the route legitimately reads a classmate's or a shared row. | Widen the policy if the read is legitimate for that student, otherwise mark the call `service_scope()` (and list it in `tests/test_service_scope_allowlist.py` with a reason). |
| `fewer_rows` on `rpc/match_course_chunks` | Plan §6.3 #1: RLS filters after the ANN scan, so the student gets fewer than `match_count` chunks. | Measure the ratio. A consistent recall loss blocks enforce for the tutor/quiz routes. |
| `more_rows` | Rare. Most often a write landed between the two reads. | Ignore isolated ones. A repeated one means a policy is wider than the service query's own filter: investigate. |
| `write_other_user` | The route writes or targets another user's row (friend requests, owner transfer, aggregates). Under enforce that is a 403 (WITH CHECK) or a silent no-op (USING). | `service_scope()` with an allowlist entry, or a policy that allows it. |
| `no_subject` | A public or pre-session route is not marked service. Under enforce it returns 500. | `Depends(service_route)` on the endpoint, plus an allowlist entry. |
| `denied` (enforce) | Same as 403 above, but a student actually saw a 404. | Same fixes. Under a rollout, consider the kill switch first (§7). |

Service-scope opt-outs and policies change through review, never by hand:
`tests/test_service_scope_allowlist.py` fails on an unlisted opt-out, and
policies/grants are append-only migrations that reach staging through
`migrate-staging.yml`.

---

## 2. Step 2d: our ES256 signing key (staging first)

Background (plan §2.2, addendum): both projects have migrated to Supabase
signing keys. The current key is Supabase-managed ES256, and its private half
cannot be extracted. The legacy HS256 secret is listed as a previous key. To
mint tokens PostgREST accepts, we import our own ES256 key and make it current.
Sapling does not use Supabase Auth, so rotating signs nobody out. The legacy
anon and service keys keep verifying as long as the legacy secret is not
revoked.

**Use a different key per environment.** Never copy staging's key to prod.

1. **Generate** on your machine, in a directory outside the repo:

   ```bash
   supabase gen signing-key --algorithm ES256 > sapling-staging-es256.jwk.json
   ```

   This produces one private JWK: `kty: "EC"`, `crv: "P-256"`, `x`, `y`, `d`,
   and a `kid`. If the CLI is unavailable, any P-256 private JWK works. Make sure
   it has a `kid`: `db/user_jwt.py` copies it into the token header, and Supabase
   picks the verification key by it. Do not commit the file. Delete it once it
   is in the password manager and Railway.

2. **[Andres] Import as a standby key** on the staging project: Dashboard →
   Project Settings → JWT Keys → create a standby key → import an existing
   private key → paste the JWK.

3. **Test the standby key before rotating** (open question from the addendum).
   Set the key locally (§3, `.env.staging` only), then run the §4 curl.
   - 200 means the standby key is already accepted. You can set the Railway
     variable before rotating.
   - 401 is what the Supabase docs predict: a standby key does not verify yet.
     Go on to step 4.

4. **[Andres] Rotate**: make the imported key current. The Supabase-managed ES256
   key becomes a previous key and keeps verifying until revoked. Do not revoke
   anything.

5. Run §4 again: expect 200. Then check that the frontend still works. Load the
   staging app signed in: realtime and the anon key use the legacy secret, which
   is unaffected.

6. **Prod**: the same 1–5 with a **new** key, after staging has completed the
   ladder in §5.

The realtime bridge (step 2e, `iss: sapling-realtime`) signs with this same key.
2d is a prerequisite for 2e too.

## 3. Secrets: what goes where

| Name | Value | Where | Where NOT |
|---|---|---|---|
| `SUPABASE_JWT_SIGNING_KEY` | The private JWK from §2 as **one line of JSON**, e.g. `{"kty":"EC","crv":"P-256","kid":"…","x":"…","y":"…","d":"…"}`. Extra members (`alg`, `use`, `key_ops`, `ext`) are ignored. `db/user_jwt.py` accepts exactly `kty: EC` + `crv: P-256` with `d`, `x`, `y` (ES256), or `kty: oct` with a base64url `k` of at least 32 bytes (HS256, local and CI only). A `kid` is optional for the parser but required in practice on hosted projects. | **[Andres]** Railway → backend (API) service → Variables, for that environment. Paste the JSON as-is, with no surrounding quotes. Your local `backend/.env.staging` / `.env.production` (used by §4 only), wrapped in single quotes. | The frontend, GitHub secrets, the repo, Trov, chat. The worker service does not need it: it runs outside a request and is always service role. |
| `SUPABASE_ANON_KEY` | The project's **anon** (legacy JWT) or **publishable** (`sb_publishable_…`) key, from Project Settings → API Keys. It is the same value as that environment's frontend `NEXT_PUBLIC_SUPABASE_ANON_KEY`. Supabase refuses a minted JWT in the `apikey` header, so this key goes there. Never the service key: `db/user_jwt.anon_key()` refuses to fall back to it. | **[Andres]** Railway backend service, same environment. Local env file for §4. | It is not secret, but it is per environment: staging's anon key on prod will 401. |
| `DB_USER_SCOPE_SHADOW_SAMPLE_RATE` (optional) | `0`–`1`. Fraction of reads the shadow re-runs. Default `0.1`. A **tuning knob, not a feature gate** (like `JOBS_LEASE_SECONDS`): whether shadow runs at all is the `db_user_scope` flag; this only sets how dense an already-on shadow is. It is an env var because flag variants are strings, not numbers. Clamped to `[0, 1]`; `nan`, `inf` or anything unparseable falls back to `0.1` with a WARNING. | Staging: `1` (traffic is small, so compare everything). Prod: leave unset, or `0.2`–`0.5` for a short, denser pass. Read at boot. | |

After setting them, the next boot no longer logs
`db_user_scope cannot leave 'off' on this deployment (...)` (`config.py`). That
line names exactly which key is missing or unparsable. Changing a Railway
variable redeploys the service.

## 4. Verify a minted token against PostgREST

`backend/scripts/mint_scope_token.py` mints exactly the token the backend sends
under enforce. It refuses `APP_ENV=production`, and also an unset `APP_ENV`
(which `config.py` reads as production), unless `--allow-production` is passed.
Use it with local and staging env files. On prod, pass `--allow-production`
only once, for the §2 step 6 check.

From `backend/`. Use your own `users.id` on that environment (Admin → Accounts,
or `SELECT id FROM users WHERE ...` in the SQL editor):

```bash
# Which key is configured: alg, kid, fingerprint, public half only.
# Its kid must match one in the project's JWKS:
python scripts/mint_scope_token.py --env-file .env.staging --show-key
curl -s https://<staging-ref>.supabase.co/auth/v1/.well-known/jwks.json

# Mint and call PostgREST as that student.
dotenv -f .env.staging run -- sh -c '
  TOKEN=$(python scripts/mint_scope_token.py --decode "$0") || exit 1
  curl -sS -w "\nHTTP %{http_code}\n" \
    "$SUPABASE_URL/rest/v1/notes?select=id,user_id&limit=5" \
    -H "apikey: $SUPABASE_ANON_KEY" \
    -H "Authorization: Bearer $TOKEN"
' user_XXXXXXXX
```

How to read the answer:

| Answer | Meaning |
|---|---|
| `HTTP 200` and every `user_id` equals the one you minted for (or `[]` if that user has no notes) | The key is trusted, the grants (2c) and policies (2b) apply. Step 2d is done. |
| `HTTP 401`, `PGRST301` / "JWSError" / "No suitable key" | The key is not trusted (standby, wrong project, or a kid mismatch). Check `--show-key` against the JWKS. |
| `HTTP 401` mentioning `apikey` | `SUPABASE_ANON_KEY` is wrong or from another project. |
| `HTTP 403`, `42501` "permission denied for table notes" | The token is accepted but 2c (grants) is not applied. |
| `HTTP 200` with rows of **another** user | Stop: policies are not anchored on `app_auth.uid()` for that table. Do not leave `off`. |

Two negative checks worth running once:

- Mint for user A and query `notes?user_id=eq.<user B>`: expect `[]`.
- Replace the token with the anon key alone (`-H "Authorization: Bearer $SUPABASE_ANON_KEY"`): expect `[]` or 401/403, never rows (#807 revoked `anon`).

The token is valid for 5 minutes and acts as that student. Don't paste it
anywhere.

---

## 5. The ladder on staging

Flag changes go through `/admin/flags` (or `PATCH /api/admin/flags/db_user_scope`,
`PUT /api/admin/flags/db_user_scope/targets`). Each worker picks up a change within
its 30 s flag snapshot.

**Precedence matters** (release doc §7): env override → user rule → role rule →
rollout → stored default. Requests **without** a session subject only ever see
the env override or the stored default, because rules and rollouts need a user
id. So:

1. **Shadow for everyone.** Set the stored **default** to `shadow`, not a
   rollout, so anonymous/public requests are covered too and `no_subject` can
   show up. Staging: `DB_USER_SCOPE_SHADOW_SAMPLE_RATE=1`.
   - Exercise the app: sign in as a student and an admin, walk every main-nav
     page, upload a document, run the tutor and a quiz, take notes, use
     flashcards and the calendar. Run the staging HTTP harness
     (`dotenv -f .env.staging run -- python -m db.e2e_staging_http`).
   - Read the report (§1) daily. **Stop at any `status=401`.** Fix every other
     kind (table in §1), redeploy, read again.
   - Exit criteria: the gate in §1 "What an empty report does not prove" (the
     cross-user matrix under enforce green in the integration lane, every
     `unverified_writes` route covered); `top` empty for 24 h of real traffic,
     apart from understood `more_rows` noise; `shadow_reads.compared` in the
     hundreds; p95 latency unchanged (the comparison runs off the request
     thread, at most 4 in flight per process). An empty `top` on its own is
     never the exit criterion.
2. **Enforce for admins and test accounts.** Add a **role** rule: `target_type:
   role`, `target_id` = the admin role's `roles.id` (`SELECT id FROM roles WHERE
   slug = 'admin'`), `variant: enforce`. Add user rules for test accounts. The
   default stays `shadow`, so everyone else keeps feeding the report.
   - Admin routers stay service role even under enforce (`admin_service_route`
     re-checks admin), so this exercises the admins' student-facing pages.
   - Watch `db.rls_denied`, 404s, 503s and 500s by route (`/api/admin/analytics/errors`
     and the report). Re-run the cross-user matrix against staging data under
     `SAPLING_FLAG_DB_USER_SCOPE=enforce`.
   - Walk every surface as an admin, including the writes in `unverified_writes`.
3. **Rollout.** `rollout_variant: enforce`, `rollout_percent` 10 → 50 → 100, with
   the default still `shadow`. Rollout buckets are stable per user, so the same
   10% stay enforced as the percentage grows. Hold each step at least a day of
   real-mode traffic. Watch `rag.index_failed` and tutor retrieval counts:
   indexing and embedding run only in real mode, and only here.
4. **100%.** Set the default to `enforce` and the rollout back to 0. Now `no_subject`
   is a 500, so step 1 must have cleared it.

## 6. Prod

Do the same ladder, only after staging has run enforce at 100% for at least a day:

1. §2 for prod with a new key, then §3, then §4 (`--allow-production` this once).
2. Default `shadow`, sample rate at its default. Read the report for at least a
   day of real traffic.
3. Role rule `enforce` for admins.
4. Rollout 10% → 50% → 100% enforce, a day each.
5. Default `enforce`.

Keep the kill switch (§7) ready at every step. A flag-store outage resolves to
`off` (ADR 0029). That is the less secure side for this flag, and it is accepted
until graduation (§9).

## 7. Kill switch and rollback

1. **Everyone off, guaranteed:** set `SAPLING_FLAG_DB_USER_SCOPE=off` on the Railway
   backend service. The env override beats every rule, the rollout and the
   default. A variable change redeploys, so allow a few minutes.
2. **Off without a deploy:** in `/admin/flags`, delete the flag's **user and role
   targets**, set the **rollout to 0**, **and** set the **default to `off`**.
   Setting only the default leaves every user a rule or the rollout covers still
   on the old variant. Each worker picks it up within 30 s.
3. **Key trouble** (401s under enforce = 503s for students): kill switch first,
   then fix the key. Never revoke our imported key while any user is on
   `enforce` or `shadow`: every scoped call would 401. Revoke it only after the
   flag is off everywhere.
4. **Code:** this report has no migration. Reverting it restores the previous
   shadow logging. Reverting #818 needs the flag off first.
5. **Policies/grants** (2a–2c) are inert while the flag is off, so leave them in
   place. Their reverse SQL is in the release doc §3.

## 8. Later: step 2e, Realtime (`realtime_rls`)

Live room chat moves off the anon key to a bridge token (`iss: sapling-realtime`,
`docs/security/realtime-jwt-bridge-design.md`), behind its own flag
`realtime_rls` (built separately). Until then `/api/social` is service-marked
and `room_messages` is exempt, so shadow never reports on social.

Once `realtime_rls` is fully on (default `on`, 100%) on an environment and live
chat is confirmed working through the bridge, there is one manual hardening
step for that environment:

- **[Andres]** `ALTER TABLE room_messages ENABLE ROW LEVEL SECURITY;` (prod
  already has it on with zero policies; check staging) and revoke `anon`'s
  `SELECT` on `room_messages` (and the stray TRUNCATE/REFERENCES/TRIGGER the
  June lockdown left, which step 2a revokes). Then confirm a student still gets
  live messages and an anon-key client gets none. Do this through a reviewed
  migration if the 2e workstream provides one. Never use the dashboard SQL
  editor for DDL.

Do this only after `realtime_rls` is fully on. Before that, it cuts live chat
for everyone still on the anon-key path.

## 9. Graduation

Once prod has run `enforce` at 100% for a full release with an empty report
(under enforce, `db.rls_denied` and `db.unscoped_query` are real refusals, not a
heuristic, so an empty report there IS meaningful):
delete the flag and make enforce unconditional, keeping only the env kill switch
(plan §4.4). Remove the shadow machinery with it (`db/scope_report.py`, the
shadow pool in `db/connection.py`).
