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

1. The CI **integration lane** green on the commit you deploy. It runs the
   cross-user matrix (`tests/integration/test_cross_user_matrix_db.py`,
   parametrized over `off` and `enforce`) and then the whole lane a second time
   with `SAPLING_FLAG_DB_USER_SCOPE=enforce` (step "Run integration tests under
   db_user_scope=enforce" in `.github/workflows/integration.yml`;
   `test_db_user_scope_lane_db.py` fails that step if the override stops
   reaching the app; that step runs on pushes to `main` and on a manual
   dispatch, not on every PR push, so for a PR touching routes, policies or
   grants dispatch the workflow on its branch). No new `KNOWN_LEAKS` entry, and every write route of
   `unverified_writes` covered by a matrix case or an integration test.
2. The Chapter 1 E2E lane green **under enforce** as well as by default (§10
   has the command and the last verified result).
3. Then the report clean as described in §6.

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
   ladder in §6 (through step 6).

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

## 5. How to change the flag (the three controls)

Every step below is one of these, in the admin portal at **`/admin/flags`**
(open the `db_user_scope` row; a change is applied when you confirm it) or the
equivalent admin API call. Each worker picks a change up within its 30 s flag
snapshot. Never change the registry default in code: `variants[0]` stays `off`
(ADR 0029).

| What | Admin UI (`/admin/flags` → `db_user_scope`) | API (admin session) |
|---|---|---|
| Stored default | **Everyone** → pick `shadow` / `enforce` / `off` → confirm | `PATCH /api/admin/flags/db_user_scope` `{"default_variant": "shadow"}` |
| Rollout | **Gradual rollout** → *Serve* `<variant>` *to* `N%` *of students* (presets or the slider) → confirm | `PATCH /api/admin/flags/db_user_scope` `{"rollout_variant": "enforce", "rollout_percent": 10}` |
| Role / user rule | **Overrides** → pick the role (or search the student) → *Set to* `enforce` → add | `PUT /api/admin/flags/db_user_scope/targets` `{"target_type": "role", "target_id": "<roles.id>", "variant": "enforce"}`; remove with `DELETE /api/admin/flags/db_user_scope/targets/role/<roles.id>` |
| Check one student | **Check a student** → search → shows variant and which step decided it | `GET /api/admin/flags/db_user_scope/explain?user_id=<users.id>` |

The API is easiest from the browser console of a tab signed in as an admin on
that environment (same origin, so the session cookie goes along):

```js
await fetch("/api/admin/flags/db_user_scope", {method: "PATCH",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({default_variant: "shadow"})}).then(r => r.json())
```

The admin role's id, for the role rule (SQL editor, read-only):

```sql
SELECT id FROM roles WHERE slug = 'admin';
```

**Precedence** (release doc §7): env override `SAPLING_FLAG_DB_USER_SCOPE` →
user rule → role rule → rollout → stored default. Requests **without** a
session subject only ever see the env override or the stored default, because
rules and rollouts need a user id. So `no_subject` (a public route not marked
service) only shows up once the stored **default** is `shadow`.

**A flag-store outage resolves to `off`** (ADR 0029: `variants[0]`) for every
request the env override does not cover. For this flag `off` is the LESS
secure side, so steps 1–6 of the ladder accept it, and step 7 removes it.

## 6. The ladder (staging first, then prod)

Run it on **staging** end to end, then repeat it on **prod** only after
staging has held step 6 for at least a day. Before step 1 on an environment,
§0 and §2–§4 are done there (its own key, `--show-key`/curl verified).

| # | Set | Hold | Go on when | If it goes wrong |
|---|---|---|---|---|
| 1 | Rollout: *Serve* `shadow` to **N%** (staging 100%, prod 25%). `DB_USER_SCOPE_SHADOW_SAMPLE_RATE`: staging `1`, prod unset (0.1). | 1 day of real traffic | §1 report: no `status=401` ever; `shadow_reads.compared` in the hundreds; every `fewer_rows` / `different_ids` / `error` / `write_other_user` group understood and fixed (§1 table); p95 latency unchanged | Rollout to 0 (§7.2). A `status=401` means the key is not trusted: back to §2–§4. |
| 2 | Default: **Everyone** = `shadow`; rollout back to 0. | 1 day (prod: 2) | As step 1, plus no `db.unscoped_query` (`no_subject`) group left: each one is a public route that needs `Depends(service_route)` + an allowlist entry, and would be a 500 under enforce. | Default back to `off`. |
| 3 | **Overrides** → role `admin` (and test accounts by user) = `enforce`. Default stays `shadow`. | 1 day | Admins walk every main-nav page and the writes in `unverified_writes` (upload, tutor, quiz, notes, flashcards, study guide, calendar, gradebook, rooms/friends, profile/settings). `db.rls_denied` empty; no new 404/503/500 by route (`/api/admin/analytics/errors`). | Delete the role rule. |
| 4 | Rollout: *Serve* `enforce` to **10%** → **50%** → **100%** (default still `shadow`, so the 100% step leaves only anonymous requests on shadow). | ≥1 day each | `db.rls_denied`, `db.unscoped_query` and 503s flat; `rag.index_failed` and tutor retrieval counts unchanged (indexing and embeddings run only in real mode, so only here). Buckets are stable per user, so the same students stay enforced as the percentage grows. | Rollout to 0 (§7.2). |
| 5 | Default: **Everyone** = `enforce`; rollout back to 0; delete the step-3 overrides. | 1 day | Under enforce `db.rls_denied` / `db.unscoped_query` are real refusals, not a heuristic: the §1 SQL over 24 h must return no rows for them. | Default back to `shadow` (§7.2). |
| 6 | Hold step 5. | prod: one full release | Report still empty. | §7. |
| 7 | **Pin it** (removes the outage → `off` fallback): **[Andres]** Railway → backend (API) service → Variables → `SAPLING_FLAG_DB_USER_SCOPE` = `enforce` → deploy. The worker reads the same variable through its `${{backend.…}}` reference (`.railway/railway.ts`), and runs as service anyway. | – | `GET /api/admin/flags/db_user_scope/explain?user_id=<any>` answers `{"variant": "enforce", "step": "env_override"}`. From now a flag-store outage, a deleted `feature_flags` row or a bad stored value cannot drop anyone to the service role. | Set the variable to `off` (that is now the kill switch, §7.1). Never just delete it while the stored default is not `enforce`. |
| 8 | Graduation (§9): the code PR that makes enforce unconditional. | – | – | Revert the PR; the step-7 pin keeps enforce meanwhile. |

Re-run the cross-user matrix against the environment's own data whenever you
like (`dotenv -f .env.staging run -- python -m db.e2e_staging_http` exercises
the HTTP surface; the matrix itself runs in CI on every PR that touches `backend/`, `supabase/` or `scripts/` and on every push to `main`, §1).

## 7. Kill switch and rollback

1. **Everyone off, guaranteed:** set `SAPLING_FLAG_DB_USER_SCOPE=off` on the Railway
   backend service. The env override beats every rule, the rollout and the
   default. A variable change redeploys, so allow a few minutes. After step 7
   of the ladder this is the same variable, changed from `enforce` to `off`.
2. **Off without a deploy** (steps 1–6 only; after step 7 the env pin wins):
   in `/admin/flags`, delete the flag's **user and role overrides**, set the
   **rollout to 0**, **and** set **Everyone** to `off`. Setting only the
   default leaves every user a rule or the rollout covers still on the old
   variant. Each worker picks it up within 30 s.
3. **Key trouble** (401s under enforce = 503s for students): kill switch first,
   then fix the key. Never revoke our imported key while any user is on
   `enforce` or `shadow`: every scoped call would 401. Revoke it only after the
   flag is off everywhere.
4. **Clock skew:** a minted token's `iat` is the API host's clock and PostgREST
   rejects one issued too far in its future, so an API host whose clock runs
   ahead of the database's by more than PostgREST's leeway gets 401s, i.e.
   503s for students, until the clocks agree (seen once locally, §10). On
   Railway and Supabase both clocks are NTP-synced; if a 401 burst appears
   with a correct key, compare the two clocks before anything else.
5. **Code:** reverting a release that only changed policies or code paths is
   safe at any step; reverting the flag code itself (#818) needs the flag off
   first.
6. **Policies/grants** (2a–2c) are inert while the flag is off, so leave them in
   place. Their reverse SQL is in the release doc §3.

## 8. Step 2e, Realtime: done

Live room chat runs on a bridge token (`iss: sapling-realtime`,
`docs/security/realtime-jwt-bridge-design.md`), not the anon key. It shipped
behind its own flag, `realtime_rls`, which went to default `on` on staging
and prod with live chat confirmed working through the bridge. `/api/social`
stays service-marked, so shadow still never reports on social.

The hardening step this section used to leave to Andres is now a reviewed
migration, `20261109073255_room_messages_rls_enable.sql`: RLS on for
`room_messages`, anon's privileges revoked (`REVOKE ALL`, so the
TRUNCATE/REFERENCES/TRIGGER the June lockdown left go too; step 2a had
already taken them), authenticated exactly SELECT, gated by the member
policy. It is a no-op on prod (RLS on since June, anon already revoked) and
changes staging when it migrates. The same change removed the client's anon
subscription path and stopped reading the `realtime_rls` flag; the flag
stays registered (stored default `on`) for one release so frontend bundles
older than the change keep live chat, and a follow-up deletes it with its
stored rows. Nothing is left to do by hand. Rollback: revert that change, then (staging only, never prod) `GRANT
SELECT ON public.room_messages TO anon; ALTER TABLE public.room_messages
DISABLE ROW LEVEL SECURITY;`.

To check an environment after it migrates: a student in a room still gets
live messages, and an anon-key client gets none (PostgREST
`/rest/v1/room_messages` with the anon key answers 401).

## 9. Graduation

Step 7 of the ladder already makes enforce outage-proof without a code change.
Graduation removes the flag itself, once prod has run step 5 for a full
release with an empty report. It is one reviewed PR:

1. `db/scope.py::_resolve_mode`: answer `enforce` unconditionally, except an
   explicit `SAPLING_FLAG_DB_USER_SCOPE=off` (the kill switch, read straight
   from the environment). No flag-store read, so no outage path to `off`.
2. Delete the `db_user_scope` `FlagDef` from `services/feature_flags.py`, its
   stored rows (`DELETE FROM feature_flag_targets WHERE flag_key =
   'db_user_scope'; DELETE FROM feature_flags WHERE key = 'db_user_scope';` in a
   timestamped migration), and the shadow machinery: `db/scope_report.py`, the
   shadow pool and `shadow_headers` / `note_shadow_write` hooks in
   `db/connection.py` + `db/scope.py`, `DB_USER_SCOPE_SHADOW_SAMPLE_RATE`, and the
   `/api/admin/analytics/db-scope` report (keep `db.rls_denied` /
   `db.unscoped_query`: under enforce they are the real refusals).
3. The cross-user matrix keeps `MODES = ["off", "enforce"]` while the kill
   switch exists. With enforce the default, integration.yml's two runs are
   the same run: drop its enforce step.
4. Keep the Railway variable from step 7 until the PR is deployed, then leave
   it (it is now simply the kill switch's `enforce` side) or delete it.

## 10. Verified locally (what the gate above was last run against)

Run 2026-11-16 on branch `sec2/rls-enforce`, local slot stack (Supabase CLI
2.116.0, PG15, migrations replayed from empty, function-mode agents), the HS256
local key from `backend/.env.local.example`:

| Lane | default (`off`) | `SAPLING_FLAG_DB_USER_SCOPE=enforce` |
|---|---|---|
| Playwright Chapter 1 (`frontend/e2e`) | 112 passed, 1 failed, 14 skipped | 112 passed, 1 failed, 14 skipped |
| `python -m e2e_oracles` | 0 findings | 0 findings |
| Integration lane (`-m integration`, whole lane) | not rerun here (CI step 1; the matrix inside it covers both modes) | 385 passed |
| PostgREST 401/403/42501, `db.rls_denied`, `db.unscoped_query` in the backend log | – | none |

The one failure is the same test in both modes and on `main` without this
branch (`study-guide.spec.ts:337`, the second check answer keeps the first
answer's text): not a scope problem. Under enforce every request in the lane
ran as the student: no policy, grant or unmarked service path was missing.

To repeat it (one flock'd cycle; `--slot` as free; see `scripts/e2e-cycle.sh`):

```bash
export SAPLING_FLAG_DB_USER_SCOPE=enforce   # e2e-up passes the shell env to uvicorn
E2E_FRESH_DB=1 flock -w 14400 "$STACK_LOCK" scripts/e2e-cycle.sh --slot 2
grep -cE 'rls_denied|unscoped_query|42501|ScopeUnavailable' .e2e/backend.log   # expect 0
```

An earlier run on a heavily loaded machine showed one burst of 401s ("PostgREST
rejected the user-scoped token") inside five seconds, then none: the host had
stalled for about a minute and the Supabase VM's clock came back 54 s behind
it, so tokens minted on the host were "issued in the future" for PostgREST
(Kong's access log and the backend log disagree by exactly that). That is §7.4,
not a key or policy problem. It did surface one real bug, fixed on this
branch: `GET /api/flashcards/user/{id}` answered a refusal as a 500 carrying
the refusal's text, because the service wraps every failure in
`StorageError`; `routes/_errors.py::domain_status` now re-raises a wrapped
`db.scope` refusal so main.py answers 503/404/500 as everywhere else.

### What stays service role under enforce, and why

Each opt-out is listed with its reason in `tests/test_service_scope_allowlist.py`.
The router-level ones, reviewed for this rollout:

| Router / endpoint | Could it be user-scoped now? |
|---|---|
| `/api/auth` | **Moved** (this branch): `GET /me`, `/local-seed` and `/realtime-token` now run as the student (own rows + catalog only); the OAuth redirect/callback, `/pending/*` and `/test-login` run before a session exists and `/logout` writes `users.sessions_valid_after` (users is SELECT-only for students), so those five keep an endpoint-level service mark. |
| `/api/social` | No, not as a mount. Invite-code join reads and joins a PRIVATE room the student is not in (`rooms_select_visible` hides it, `room_members_insert_self` refuses it); leaving hands ownership to another member and the last leave deletes the room (no student UPDATE of another's `owner_id`, no `rooms` DELETE policy); `_touch_room` updates a room the caller does not own; matching, room overview and activity read other members' mastery. Moving it means service-scoping most of `services/social/` piece by piece, which buys RLS on little more than the message and friend-request reads. Do it as its own change, with the social E2E specs and the matrix's social cases under enforce as the gate. |
| `GET /api/profile/{user_id}` | No. It serves anonymous viewers (no subject: a 500 under enforce), reads another user's rows and creates their missing settings/profile rows; visibility is applied in code. `/{user_id}/roles` (another user's `user_roles`) and `/username/check` (other users' usernames) likewise. |
| `/api/careers`, `/api/newsletter`, `/api/email` | No: public, no session, and their tables (`job_applications`, `newsletter_emails`, `email_*`) are service-only. |
| `/api/internal/*` | No: server-to-server bearer tokens, no session; `canopy_metrics()` and the account copy are service-role only. |
| `/api/admin/*` | No: cross-user by design. `admin_service_route` re-checks admin before marking, so a handler that forgot `require_admin` never runs service-scoped for a student. |
