# Release plan: architecture hardening to production (Nov 2026)

Trov sprint #28, tickets #114 to #119. Written 2026-11-08 at the end of the
overnight stacked-PR run. Every SHA, count and command below was read from git,
`gh` or the migration files on `harden/release-doc`. Nothing here has run against
staging or production.

**TL;DR**

- Production runs `6ed0f13c` (#748, 2026-10-23). This release ships 13 commits
  already on `main` (PostHog, the #772 state-machine audit, #807 deny-all RLS,
  #808 CVE upgrades, and others), plus #809 and the 9 stacked PRs below this one (#810, #821, #812–#815, #817–#819).
- All four of the stack's own migrations are in **one PR, #821**, so they merge
  and apply together (it replaced #811 and #816, now closed).
- There are 8 new migrations in total. One of them, #772's
  `20261106055333_state_machines_audit.sql`, changes data and drops two
  columns. `make promote` will block on it until you pass
  `--allow-destructive` (§6).
- The three new flags (`llm_fallback`, `jobs_queue`, `db_user_scope`) all
  default to `off`. #814 still changes LLM timeouts, retries and the circuit
  breaker with its flag off.
- Merge order is bottom to top, always with a merge commit, never a squash. See
  §2. #813, the cross-user security fix, can go out first by cherry-pick.

---

## 1. What prod gets

`git ls-remote origin production` returns `6ed0f13c` ("Merge pull request #748
from SaplingLearn/main", 2026-10-23 23:32 -0400). Prod deploys come from the
`production` branch. `make promote` (`backend/promotion/`) merges `main` into
`production`, pinned to the SHA it audited, after it has migrated the prod DB.
`main` deploys staging and migrates the staging DB on every merge
(`migrate-staging.yml`).

`git log --oneline --no-merges origin/production..HEAD` returns 36 commits. In
total that is 460 files and +85.6k/−5.3k lines; the stack alone is 82 files and
+12.4k/−0.3k.

### 1a. Already on `main`, not yet on prod (13 commits)

| PR | Commit | What | Risk | Why |
|---|---|---|---|---|
| #677 | c4c4d45e | PostHog backend: events, LLM analytics and exceptions through one consent queue | med | Adds a migration (`analytics_opt_out`). It stays inert until `POSTHOG_PROJECT_TOKEN` is set in prod. `error.*` route values change format once at deploy. |
| #675 | 7148b204 | PostHog frontend: pageviews, `/ingest` proxy, account opt-out | low | Only active with a token. Gated by the `product_analytics` flag, which defaults to `on`. |
| #754 | 2f685518 | E2E captures screens into Figma frames | low | Tooling only. |
| #772 | 02209c59 | Implicit state-machine audit (#756 to #771): one combined migration | **high** | Changes data and drops columns (§3). New CHECK constraints apply to old prod code during the migrate-to-deploy window. |
| #796 | 139188ab | Drops the 3D knowledge graph; adds a "Mastery colors" mode | low | Frontend only. |
| #798 | 9d3f3374 | Dashboard "Today's plan", Study/Tree/shell refinements, brand assets. Includes teammate PR #753 by lpcooper-arch. | med | Large frontend surface. |
| #802 | e47b9a33 | Onboarding token course search, latest-query-wins | low | Frontend plus search. |
| #805 | dce61cfd | `xp_events` idempotency per student | med | Changes a constraint. Run `scripts/backfill_achievement_xp.py` after it (dry-run by default). |
| #806 | d22b0aeb | Index sweeper defaults to on in production only | low | No change in prod: prod's `sweeper_enabled()` already defaults to on. |
| #807 | 9153482e | RLS on every public table; anon and authenticated revoked | **high** (needed) | Closes the 35-table anon-key exposure. The backend is unaffected because it runs as service_role with BYPASSRLS. |
| #803 | d1860dc9 | Course-centred radial graph layout | low | Frontend only. |
| #804 | 2be7b924 | Admin account tools: seed by major, wipe, copy between envs | med | Admin-only and destructive by design, with typed-email confirms. Copy is disabled until the `ACCOUNT_SYNC_*` env vars are set. |
| #808 | f2c77e05 | Phase 0 CVE upgrades: next 16.2→16.4, katex 0.16→0.18, mermaid, cryptography, pillow, pypdf | med | Framework and renderer bumps. Check KaTeX and mermaid rendering in the smoke. |

Every one of these was merged by Andres. The only teammate code in the range is
#753 (lpcooper-arch), which landed inside #798. Since `stack/base` was cut,
nothing new has landed on `main`: `origin/main` is still `f2c77e05`. Before you
start, re-check with `git fetch && git log --oneline f2c77e05..origin/main`.

### 1b. The docs PR and the stack (none merged yet)

| # | PR | Branch | Commits | What | Risk | Why |
|---|---|---|---|---|---|---|
| 0 | #809 | `docs/architecture-hardening-plan` | 5e75d6ab | Hardening plan and RLS step-2 plan (draft SQL, not migrations) | none | Docs only. |
| 1 | #810 | `harden/w1c-backup` | f99aba5f, fec08225 | `pg_dump` backup module, `make backup-db`; `make promote` backs up before migrating and refuses to continue if the backup fails | low | Operator tooling. `make promote` now needs host `pg_dump` 15+ or podman/docker. |
| 2 | #821 | `harden/db-migrations` | 93998307, dad53800 | **All four stack migrations**: RLS 2a (`app_auth` helpers, function EXECUTE hygiene, `room_messages` privileges), 2b (137 policies), 2c (grants to `authenticated`), and the `jobs` queue table and functions, plus their DB-level integration tests | low | Privileges, policies and one new table. Inert for the service_role backend: nothing mints a `sapling-api` token until `db_user_scope` is on, and nothing writes `jobs` until `jobs_queue` is on. Replaces #811 and #816 (closed). |
| 3 | #812 | `harden/w1b-cross-user-matrix` | be082ccb | Cross-user test matrix, about 285 requests, flag off | none | Tests only. |
| 4 | #813 | `harden/fix-social-cross-user-leaks` | 74d43bdd | **Security fix**: 4 cross-user leaks in `routes/social.py` | low | Members see no change. `school_match` is now same-school only. |
| 5 | #814 | `harden/w1d-llm-resilience` | 30e22d0f, 21e2f7f7 | LLM retries, timeouts, circuit breaker; cross-provider fallback behind `llm_fallback` | **med** | **Active with the flag off.** Per-slot timeouts drop from 600 s to 30–240 s, Gemini now gets 3 attempts, and the breaker fails fast for 30 s after 8 failures. |
| 6 | #815 | `harden/w2c-relock` | 57dbd62a | Re-locks 12 flagged transitive dependencies | med | Includes oauthlib 3→4 (Google sign-in) and logfire 4→5 / otel 0.66. |
| 7 | #817 | `harden/w2b-jobs-foundation` | 66f965a1, 1484dd1c, 174adec1 | `services/jobs.py`, `python -m worker`, course-context refresh behind `jobs_queue` (its migration is in #821) | low | With the flag off it adds one cached flag read. |
| 8 | #818 | `harden/w3a-user-scoped-client` | 8d59ddbf, ed882824, e9cd875b, 6c936d1d, 0b57f73e, bfb407cd, b9b3a1bc | User-scoped PostgREST client behind `db_user_scope` (off/shadow/enforce) | low (off) / high (enforce) | With the flag off, requests are byte-identical (pinned by a test). Every `table()` call now goes through `_scope_headers`. |
| 9 | #819 | `harden/w3b-async-db-design` | 3314e062 | Async DB client design doc | none | Docs only. |
| 10 | this (#820) | `harden/release-doc` | — | This file | none | Docs only. |

`stack/base` is **not a PR**. It is `f2c77e05` plus a merge commit `8c7d72fc`
of #809's head. Once #809 is on `main`, that merge commit adds nothing.

---

## 2. Merge order and how to merge a stack here

According to `gh repo view`, all three merge methods are allowed
(`mergeCommitAllowed`, `squashMergeAllowed` and `rebaseMergeAllowed` are all
`true`). Head branches are not deleted on merge (`deleteBranchOnMerge: false`).
The active "Branch Protection" ruleset requires 1 approval and dismisses stale
approvals on push, so every push to a PR branch needs a fresh approval.

**Use a merge commit every time. Never squash or rebase a stacked PR.** Squash
writes a new commit that is not an ancestor of the next PR's branch. The next
PR's diff, taken from the merge base, would then show all of its parent's
changes again, and its reviewed commits could no longer be merged cleanly. A
merge commit keeps each PR's head in `main`'s history, so after a retarget the
next PR's diff is exactly its own commits. A repo note says the same: an
ancestry merge must be a merge commit.

### Procedure

I checked each step with `git commit-tree` simulations on the real SHAs, without
pushing anything.

```bash
# 0. #809 (docs, already targets main)
gh pr merge 809 --merge

# 1. #810: retarget, then merge main INTO its branch once, so the PR has a
#    single merge base. Without this step, git sees two merge bases (f2c77e05 and
#    5e75d6ab) and the diff shows 18 files (it re-shows #809's docs) instead of
#    #810's own 10.
gh pr edit 810 --base main
git fetch origin && git switch harden/w1c-backup && git pull --ff-only
git merge --no-edit origin/main && git push          # a plain push, no force
#    wait for CI and a re-approval, then:
gh pr merge 810 --merge

# 2..9. For each N in 821 812 813 814 815 817 818 819, in order, once the
#       PR below it has merged. #821 is every migration in the stack: merging it
#       runs migrate-staging.yml for all four at once.
gh pr edit N --base main          # its diff is now exactly its own commits
#        wait for CI (the retarget re-runs it), then:
gh pr merge N --merge

# 10. This PR (#820) the same way.
```

- Delete a PR's head branch only **after** you have retargeted the PR above it.
  Deleting a base branch while a PR still targets it can close that PR.
- **If a teammate merges to `main` partway through:** the next PR's diff stays
  clean, because its merge base is still its parent's head. To test against the
  new `main`, merge `main` into the PR branch (`git merge origin/main && git
  push`). Do not rebase and force-push reviewed commits: that rewrites what was
  reviewed and breaks the diff of every PR above it. Resolve any conflict in that
  merge commit.
- **Shipping #813 first, ahead of the stack.** Checked: `social.py` and
  `test_social_state_machines.py` apply cleanly on `main`. The two matrix files
  conflict as modify/delete because #812 has not merged, so drop them:
  ```bash
  git switch -c hotfix/social-leaks origin/main
  git cherry-pick 74d43bdd        # stops on 2 modify/delete conflicts
  git rm backend/tests/cross_user_matrix.py backend/tests/integration/test_cross_user_matrix_db.py
  git cherry-pick --continue
  ```
  On that tree the social suites pass: 82 passed. Open it as its own PR and
  merge it. When #813 later merges in the stack, the social changes are already
  on `main` and only the matrix edits remain. Expect a conflict-free merge.
- **No stacked PR was seen by CodeRabbit.** It skips PRs whose base is not
  `production`/`staging`, and every PR here, #810 and #821 included, targets
  another stack branch. One `/code-review` pass (high effort) over the whole
  stack ran on 2026-11-08 and reported 10 findings, all in this release doc. They
  are fixed here. Each PR still needs its own approval.

---

## 3. New migrations, in apply order

This is `git diff --name-only origin/production..HEAD -- backend/db/migrations/`:
8 files. `db/migrate.py` applies **each file in its own transaction** and
commits it. A failure stops the chain at that file: the earlier files stay
applied and the failing one rolls back.

Staging already has #1 to #4 (`migrate-staging.yml` succeeded on 11-04, 11-06
and twice on 11-08). #5 to #8 reach staging together when #821 merges.

| # | File | PR | What | Touches data? | Reverse |
|---|---|---|---|---|---|
| 1 | `20261016064813_analytics_opt_out.sql` | #677 | `user_settings.analytics_opt_out BOOLEAN NOT NULL DEFAULT false` | No. A constant default is metadata only. | `ALTER TABLE user_settings DROP COLUMN IF EXISTS analytics_opt_out;` (only after reverting #677's code) |
| 2 | `20261106055333_state_machines_audit.sql` | #772 | `email_sends.claimed_at` / `idempotency_gen`, `email_broadcasts.heartbeat_at` and a status CHECK, a `room_bans` table, room FKs → ON DELETE CASCADE, `gradescope_credentials` sync outcome, a `course_chunk_sources` ledger, a quiz completed-XOR-abandoned CHECK, `canopy_metrics` changes, the `apply_mastery_delta` function, `documents.index_status` gaining `exhausted`, a claim/reaper rewrite, **DROP `users.current_room_id` and `courses.deleted_at`** | **Yes.** It backfills `claimed_at` / `heartbeat_at`, **deletes rooms with no members**, gives rooms whose owner left to their earliest member, resolves quiz rows that are both completed and abandoned, and rewrites `mastery_tier 'subject_root'` to `'unexplored'`. | **No reverse header, and it is partly irreversible.** The dropped columns, deleted rooms and rewritten rows come back only from the pre-promote dump (§7.3). Re-adding the columns empty: `ALTER TABLE users ADD COLUMN current_room_id TEXT REFERENCES rooms(id) ON DELETE SET NULL; ALTER TABLE courses ADD COLUMN deleted_at TIMESTAMPTZ;` |
| 3 | `20261108063442_xp_events_per_user_idempotency.sql` | #805 | UNIQUE `(user_id, idempotency_key)` replaces UNIQUE `(idempotency_key)`. It raises if duplicate pairs exist. | No rows change; it moves a constraint. | `ALTER TABLE xp_events DROP CONSTRAINT IF EXISTS xp_events_user_id_idempotency_key_key; ALTER TABLE xp_events ADD CONSTRAINT xp_events_idempotency_key_key UNIQUE (idempotency_key);` This fails once two students hold the same key, which is the bug the migration fixes. Don't reverse it. |
| 4 | `20261108082151_rls_on_every_table.sql` | #807 | ENABLE RLS on every `public` table except `room_messages`; REVOKE ALL from anon/authenticated; GRANT ALL to service_role; default privileges stop granting anon/authenticated | No (privileges) | **Reversing it reopens the anon-key hole.** If you must: `DO $$ DECLARE t text; BEGIN FOR t IN SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename<>'room_messages' LOOP EXECUTE format('ALTER TABLE public.%I DISABLE ROW LEVEL SECURITY', t); END LOOP; END $$;` Re-granting anon is never needed: the backend uses service_role. |
| 5 | `20261108092633_rls_app_auth_helpers.sql` | #821 | Schema `app_auth` with `uid()` and 4 SECURITY DEFINER membership helpers; EXECUTE on public functions revoked from PUBLIC/anon/authenticated and granted to service_role; default privileges; `room_messages` write privileges revoked (anon SELECT kept) | No | Header block, verified in a container: `ALTER DEFAULT PRIVILEGES IN SCHEMA app_auth REVOKE EXECUTE ON FUNCTIONS FROM authenticated, service_role; DROP SCHEMA IF EXISTS app_auth CASCADE; GRANT EXECUTE ON FUNCTION public.set_updated_at() TO PUBLIC, anon, authenticated; GRANT EXECUTE ON FUNCTION public.match_course_chunks(vector, integer, text, text) TO PUBLIC, anon, authenticated; ALTER DEFAULT PRIVILEGES GRANT EXECUTE ON FUNCTIONS TO PUBLIC; ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO anon, authenticated;` Then `room_messages`, which depends on the environment. **Local/CI/staging:** `GRANT INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.room_messages TO anon, authenticated;` **Prod:** `GRANT INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.room_messages TO authenticated; GRANT TRUNCATE, REFERENCES, TRIGGER ON public.room_messages TO anon;` (prod's anon had only those three). Reverse 2b first. |
| 6 | `20261108094129_rls_policies.sql` | #821 | 137 policies on 55 tables, all `TO authenticated`, all keyed on `(SELECT app_auth.uid())` | No (policies) | 137 `DROP POLICY IF EXISTS ...` lines in the header. Reverse 2c first. |
| 7 | `20261108094130_rls_authenticated_grants.sql` | #821 | Table, column and function grants to `authenticated` exactly matching the 2b policies; EXECUTE on `match_course_chunks` and `apply_mastery_delta` | No (grants) | 59 `REVOKE ...` lines in the header. Run this one **first** when reversing. |
| 8 | `20261108095241_jobs_queue.sql` | #821 | `public.jobs` (service-only, RLS on) plus `enqueue_job` / `claim_jobs` / `complete_job` / `fail_job` | No. New table, written only when `jobs_queue` is on. | Turn `jobs_queue` off, then check `SELECT status, count(*) FROM public.jobs GROUP BY 1;`, then `DROP FUNCTION IF EXISTS public.fail_job(uuid, text, integer, text, integer, boolean); DROP FUNCTION IF EXISTS public.complete_job(uuid, text, integer); DROP FUNCTION IF EXISTS public.claim_jobs(text, text[], integer, integer); DROP FUNCTION IF EXISTS public.enqueue_job(text, jsonb, text, timestamptz, integer); DROP TABLE IF EXISTS public.jobs;` |

To reverse the RLS stack, go in the opposite order: 2c (7), then 2b (6), then 2a
(5). Leave #807 in place.

**Old prod code against the new schema.** Between the migrate step and the new
deploy going live (minutes), prod still runs `6ed0f13c`:

- `services/topic_checklist_service.py:51` on `production` filters
  `courses.deleted_at=is.null`. After #2 drops that column, **topic-checklist
  requests 500 until the new code is live.** I found no other prod reader of
  either dropped column (`git grep` on `origin/production`).
- The new CHECK constraints (email broadcast status, quiz completed-XOR-abandoned,
  `mastery_tier`) reject only values the old code does not write, as far as I
  could tell. The old `subject_root` tier is a response-only dict, never written
  to the database.

---

## 4. New flags and env vars

### Flags

The table includes the one flag new since the last promote that is not part of
this stack. All are declared in `backend/services/feature_flags.py::REGISTRY`.

| Flag | Variants | Default | Scope | Kill switch |
|---|---|---|---|---|
| `llm_fallback` (#814) | off / on | off | Global (`user_id=None`); per-user rules are ignored. Server-only. | `SAPLING_FLAG_LLM_FALLBACK=off` |
| `jobs_queue` (#817) | off / on | off | Per student who triggered the work. Server-only. | `SAPLING_FLAG_JOBS_QUEUE=off` |
| `db_user_scope` (#818) | off / shadow / enforce | off | Per user, resolved once per request. Server-only. | `SAPLING_FLAG_DB_USER_SCOPE=off` |
| `product_analytics` (#677, already on main) | off / on | **on** | Per student, client-visible | `SAPLING_FLAG_PRODUCT_ANALYTICS=off`. It does nothing without `POSTHOG_PROJECT_TOKEN`. |

**Recommended order after the promote:** leave all three new flags off for at
least a day of prod traffic first.

1. **`llm_fallback`.** Preconditions: prod's Railway `GEMINI_API_KEY` is real.
   Embeddings already need it, but the local `backend/.env.production` copy is a
   placeholder, so check Railway, not the file. The #814 acceptance test passes
   on staging first: force an Anthropic outage at the connection level (a
   blackholed host, or 5xx/529), turn the flag on, and expect no user errors and
   `llm_usage` rows on `gemini-*`. A bad API key gives a 401, which never falls
   back. Turn it on with the stored default in `/admin/flags`.
2. **`jobs_queue`.** Precondition: a Railway **worker service** is running
   `cd /app && python -m worker`. It uses the same image and the same variables
   as the API (`SUPABASE_*`, `ENCRYPTION_KEY`, model keys, `APP_ENV`), with no
   PORT and no healthcheck. If the flag is on with no worker running, jobs pile
   up and class aggregates stop refreshing. Ladder: staging on, then a few prod
   users, then 100%. Watch `SELECT status, count(*) FROM jobs GROUP BY 1` and
   the `job.dead` logs.
3. **`db_user_scope`** (#818's ladder). Preconditions: step 2d is done, meaning
   our ES256 key is generated with `supabase gen signing-key --algorithm ES256`,
   imported and rotated in (test on staging whether a standby key is accepted
   before rotating). Then set `SUPABASE_JWT_SIGNING_KEY` and `SUPABASE_ANON_KEY`
   and confirm the boot WARNING about missing keys is gone. Then, on staging
   first:
   1. **off.** Deploy.
   2. **shadow for everyone.** Watch `db.unscoped_query`, which must reach zero
      or be marked, and `db.rls_shadow_divergence` by table and route.
      `error=401` means a kid/JWKS mismatch: stop. `error=403` means a missing
      grant. Also watch p95 latency.
   3. **enforce for admins and test accounts** with a role rule. Watch
      `db.rls_denied`, 404s, 503s and 500s by route, and re-run the cross-user
      matrix under enforce.
   4. **enforce at 100% on staging** for a day of real-mode traffic. Watch
      `rag.index_failed` and tutor retrieval counts.
   5. **prod:** shadow, then admins, then 10%, 50% and 100%, keeping the env kill
      switch to hand. Note that a flag-store outage resolves to `off`, which is
      the *less* secure side for this flag. Graduate the flag once prod has run
      enforce at 100%.

### Env vars

| Var | From | Needed when |
|---|---|---|
| `SUPABASE_JWT_SIGNING_KEY` | #818 | `db_user_scope` leaves `off`. One JWK: `EC` P-256 with `kid` on staging and prod. It is a secret. |
| `SUPABASE_ANON_KEY` | #818 | Same as above. The `apikey` header of a user-scoped request. |
| `SAPLING_MODEL_FALLBACK_<TASK>` | #814 | Optional. Overrides the fallback model name for a slot. |
| `JOBS_POLL_INTERVAL_SECONDS`, `JOBS_BATCH`, `JOBS_LEASE_SECONDS`, `JOBS_LOG_FORMAT` | #817 | Optional worker defaults. The CLI flags `--poll-interval` and the rest override them. |
| `POSTHOG_PROJECT_TOKEN`, `POSTHOG_HOST`, `POSTHOG_QUEUE_MAX`, `POSTHOG_PERSONAL_API_KEY`, `POSTHOG_PROJECT_ID`, `POSTHOG_API_HOST` | #677 (main) | Optional. With the token unset, PostHog is fully off. `POSTHOG_DISABLED` is deprecated. |
| `ACCOUNT_SYNC_PEER_URL`, `ACCOUNT_SYNC_PEER_TOKEN` (prod), `ACCOUNT_SYNC_INBOUND_TOKEN` (staging) | #804 (main) | Optional. When unset, the copy buttons are hidden. Recommended setup: one-way, driven from prod. |
| `INDEX_SWEEPER_ENABLED` | #806 (main) | Optional. Unset means on in production. |

---

## 5. Pre-promote

1. **Reviews.** Every stacked PR needs its own approval before merge. #808 is
   already merged. Run `/code-review` on each PR before it merges, not after.
2. **Merge the stack** as described in §2. Each merge to `main` auto-migrates
   staging.
3. **Check staging after the merges:**
   - Ledger: `SELECT filename, applied_at FROM schema_migrations ORDER BY filename DESC LIMIT 10;`
     should list all 8 files from §3.
   - The `migrate-staging.yml` runs are green:
     `gh run list --workflow migrate-staging.yml --limit 5`.
   - Supabase **Security Advisor** (staging): expect **exactly one** "RLS
     Disabled in Public" finding, on `room_messages`, which stays exempt until
     step 2e. A finding on any other table means stop.
   - Smoke: sign in with **real Google** once. oauthlib 4 (#815) is only covered
     by an offline test. Then open the tutor, run a quiz, upload a document,
     check that KaTeX and mermaid render (#808), load the graph, and open a
     study room.
   - The Railway staging logs show no `EncryptionKeyMismatch` and no
     `encryption key check skipped`.
4. **Read-only prod pre-checks.** Each of these, if non-zero, makes a
   migration raise or delete rows:
   ```bash
   # bash. Split the password out of the URI so it never sits on any argv
   # (the same rule as promotion/backup.py): PGPASSWORD goes by name into the
   # container's env, and DBURL carries no password.
   cd backend
   eval "$(venv/bin/dotenv -f .env.production run -- venv/bin/python -c '
   import os, shlex, urllib.parse as u
   p = u.urlsplit(os.environ["SUPABASE_DB_URL"])
   host = p.netloc.rsplit("@", 1)[1]
   print("export PGPASSWORD=" + shlex.quote(u.unquote(p.password or "")))
   print("export DBURL=" + shlex.quote(p._replace(netloc=(p.username or "") + "@" + host).geturl()))
   ')"
   podman run --rm -i --network host -e PGPASSWORD -e DBURL --entrypoint sh \
     public.ecr.aws/supabase/postgres:15.8.1.085 -c 'psql "$DBURL" -X -v ON_ERROR_STOP=1' <<'SQL'
   BEGIN READ ONLY;
   -- #772 raises if > 0 (decide those courses first)
   SELECT count(*) AS courses_deleted_at_set FROM courses WHERE deleted_at IS NOT NULL;
   -- #772 DELETES these rooms (and, via the new cascades, their messages)
   SELECT count(*) AS memberless_rooms FROM rooms r WHERE NOT EXISTS (SELECT 1 FROM room_members m WHERE m.room_id = r.id);
   -- #772 drops and re-adds these FKs, which validates every existing row.
   -- Each must be 0, or migration #2 raises after #1 has committed. (Drop a
   -- line if that table does not exist on prod; the migration skips it too.)
   SELECT count(*) AS orphan_room_members   FROM room_members   x WHERE NOT EXISTS (SELECT 1 FROM rooms r WHERE r.id = x.room_id);
   SELECT count(*) AS orphan_room_activity  FROM room_activity  x WHERE NOT EXISTS (SELECT 1 FROM rooms r WHERE r.id = x.room_id);
   SELECT count(*) AS orphan_room_messages  FROM room_messages  x WHERE NOT EXISTS (SELECT 1 FROM rooms r WHERE r.id = x.room_id);
   SELECT count(*) AS orphan_room_summaries FROM room_summaries x WHERE NOT EXISTS (SELECT 1 FROM rooms r WHERE r.id = x.room_id);
   SELECT count(*) AS orphan_reply_to       FROM room_messages  x WHERE x.reply_to_id IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM room_messages p WHERE p.id = x.reply_to_id);
   -- #805 raises if > 0
   SELECT count(*) AS xp_dupes FROM (SELECT 1 FROM xp_events GROUP BY user_id, idempotency_key HAVING count(*) > 1) d;
   -- #807 ENABLE fails on any table the migration role does not own
   SELECT tablename, tableowner FROM pg_tables WHERE schemaname = 'public' AND tableowner <> current_user;
   -- what is pending (expect the 8 files of section 3 to be absent)
   SELECT count(*) AS applied FROM schema_migrations;
   ROLLBACK;
   SQL
   unset PGPASSWORD DBURL
   ```
5. **Backup.** With #810 merged, `make promote` takes the backup itself
   (stage 2) and stops if the backup fails. You can also take one by hand
   beforehand:
   ```bash
   make backup-db ENV=prod      # -> backups/prod-<UTC>.dump, 0600, validated with pg_restore --list
   ```
   If #810 is not merged, take the dump manually. `SUPABASE_DB_URL` must be
   the session-mode pooler URI (port 5432, user `postgres.<ref>`), and `pg_dump`
   must be at least version 15. `postgres:17` also works, but then you must
   restore with 17 or newer.
   ```bash
   mkdir -p backups && chmod 700 backups
   # PGPASSWORD and DBURL exported as in step 4 (password kept off argv)
   podman run --rm -i --network host -e PGPASSWORD -e DBURL --entrypoint sh \
     public.ecr.aws/supabase/postgres:15.8.1.085 -c 'pg_dump -Fc --dbname "$DBURL"' \
     > backups/prod-manual-$(date -u +%Y%m%dT%H%M%SZ).dump
   unset PGPASSWORD DBURL
   chmod 600 backups/prod-manual-*.dump
   podman run --rm -i --entrypoint pg_restore public.ecr.aws/supabase/postgres:15.8.1.085 --list \
     < backups/prod-manual-<ts>.dump | grep -c 'TABLE DATA'     # must be > 0
   ```
   The dump holds production data: plaintext columns plus ciphertext. Never
   commit it or copy it off the machine unencrypted.
6. **Checkout hygiene.** Run `make promote` from an up-to-date, clean `main`.
   Preflight blocks if the local `db/migrations/` differs from `origin/main`.
   The primary checkout currently has an **uncommitted edit to
   `backend/promotion/runner.py`** (deploy-wait progress lines), and #810 edits
   the same file. Commit or stash it before `git pull`.
7. Set `STAGING_SUPABASE_DB_URL` (the aws-1 pooler) so the
   staging-ran-it-first check can pass. `gh` must be authenticated, and podman
   must be available for the backup.

---

## 6. The promote and verification

```bash
make promote ARGS="--allow-destructive"
```

`--allow-destructive` is required. Preflight's `scan_destructive` flags #772's
`DROP COLUMN users.current_room_id` (line 857) and
`DROP COLUMN courses.deleted_at` (line 875); I re-ran the scan and it flags
exactly those two. Read them when the runner prints them. The topic-checklist
500 window from §3 is the known cost.

The stages are: preflight, then **backup** (#810), snapshot, migrate (the
irreversible step), snapshot and diff, a pause where you answer `y`, the merge
`main → production` pinned to the audited SHA, the deploy wait on `/api/health`,
and finally the smoke tests (`backend/promotion/smoke.py` against
`api.saplinglearn.com` and `saplinglearn.com`).

**Verify after it finishes:**

1. **The anon key reaches nothing.** This is #807's canonical count-only check.
   It returns no rows. Take `$ANON` from the frontend's
   `NEXT_PUBLIC_SUPABASE_ANON_KEY` or the dashboard.
   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' \
     "https://jxqcmjqtjlpuxfrxmrdv.supabase.co/rest/v1/graph_nodes?select=id&limit=0" \
     -H "apikey: $ANON" -H "Authorization: Bearer $ANON" -H "Prefer: count=exact"
   # expect 401 (before #807 this was 200/206 with a Content-Range count)
   # 2a revoked anon EXECUTE. The body must name the real parameter, or
   # PostgREST answers 404 "function not found" whatever the privileges are:
   curl -s -o /dev/null -w '%{http_code}\n' -X POST \
     "https://jxqcmjqtjlpuxfrxmrdv.supabase.co/rest/v1/rpc/match_course_chunks" \
     -H "apikey: $ANON" -H "Authorization: Bearer $ANON" -H "Content-Type: application/json" \
     -d "{\"query_embedding\":\"[$(python3 -c 'print(",".join(["0"]*768))')]\"}"
   # expect 401 (permission denied); 200 means anon can still execute it
   ```
2. **Security Advisor (prod):** the 35 "RLS Disabled in Public" errors drop to
   **0 errors**. What remains is informational ("RLS enabled, no policy" on the
   bucket-E tables, and on `room_messages`).
3. **Smoke:** `make promote` runs it. To re-check later without touching the DB:
   `make promote ARGS="--verify-only"`.
4. **Boot:** the Railway prod logs show the lifespan passing the encryption
   canary, with no `EncryptionKeyMismatch` and no `encryption key check skipped`.
   `/api/health` reports the new `production` SHA.
5. **Ledger:** `SELECT count(*) FROM schema_migrations` should equal the
   pre-check count plus 8.
6. **Post-promote data repair (#805):** run
   `scripts/backfill_achievement_xp.py`. It defaults to a dry run. Read the
   output, then run it for real.
7. Spot-check by hand in prod: Google sign-in, tutor chat, quiz, an upload, and
   the graph. Then a day later, start on the flags in §4.

---

## 7. Rollback plan

1. **Flags first.** A flag resolves in this order: env override, fail-closed,
   user rule, role rule, rollout, then default. **Setting only the stored default
   to `off` does not turn the flag off** for anyone a user rule, a role rule or
   the rollout already covers.
   - **Everyone, guaranteed:** `SAPLING_FLAG_LLM_FALLBACK=off`,
     `SAPLING_FLAG_JOBS_QUEUE=off`, `SAPLING_FLAG_DB_USER_SCOPE=off` on Railway.
     The env override wins over every rule. Changing a Railway variable
     redeploys the service, so allow for one deploy (minutes).
   - **No deploy:** in `/admin/flags`, delete the flag's user and role targets,
     set the rollout to 0, **and** set the default to `off`. Each process picks
     it up within its 30 s flag snapshot.
   - #814's timeouts, retries and breaker are not behind a flag. Undoing them
     takes a code revert.
2. **Code.** Revert the promotion's merge commit on `production` (the runner
   prints the revert command when smoke fails), or revert individual stack
   merge commits on `main` and re-promote. Any `production` hotfix must be
   back-merged into `main`, or the next promote's preflight blocks
   (`production-diverged`). Caveat from the runbook: reverting code leaves the
   new schema in place. That is safe for the RLS, policy, grant and jobs
   migrations, because they are additive or privilege-only. It is **not**
   strictly safe for #772: old code reads `courses.deleted_at` in the topic
   checklist.
   **A reverted merge stays reverted.** After `git revert -m 1` of the promotion
   merge, the next promote of `main` does **not** bring those commits back: git
   treats them as already merged. If that revert is back-merged into `main`,
   it removes the stack from `main` too. To re-ship after the fix, first revert
   the revert (`git revert <revert-sha>`) on `main`, then promote. Prefer
   reverting individual stack merge commits on `main` when only one PR is at
   fault.
3. **Migrations.** Apply the reverse SQL from §3 by hand as the migration role,
   in reverse order: jobs, then 2c, then 2b, then 2a. Leave #807, #805 and #677
   in place. #772 has no reverse.
4. **Data.** Restore from the pre-promote dump (`backups/prod-<UTC>.dump`)
   using the recipes in `backend/promotion/README.md` → "Backups". Rehearse on
   the local stack first. Restore only the tables you need
   (`--data-only --table=<t>`), never the whole archive over the live project.
   Take a fresh dump before any restore over prod.
   **Never `--data-only` into a live table that already has rows.** The COPY
   aborts on the first duplicate primary key and restores nothing. `-L` selects
   whole archive entries, not rows. For #772's dropped columns and deleted rooms:
   1. Restore the needed tables from the dump into a **scratch** database (the
      local stack or a throwaway container):
      `pg_restore --no-owner --no-acl -d "$SCRATCH" --table=users --table=courses --table=rooms --table=room_members --table=room_messages <dump>`.
   2. Re-add the columns on prod (§3 #2).
   3. Export only what you need from the scratch DB, for example
      `\copy (SELECT id, current_room_id FROM users WHERE current_room_id IS NOT NULL) TO 'users_room.csv' CSV`.
   4. On prod, `\copy` that into a temp table, then `UPDATE users u SET
      current_room_id = t.current_room_id FROM tmp t WHERE t.id = u.id;`.
      Restore deleted rooms with `INSERT ... ON CONFLICT (id) DO NOTHING`, then
      their members and messages in the same way.
   5. Rehearse the whole sequence on the local stack first.

---

## 8. Human-only steps (Andres)

- [ ] **Supabase Auth:** turn "Allow new users to sign up" **off** on staging and
      prod, and delete the stray prod Auth user (an Email signup from early
      setup). `app_auth.uid()` already ignores those tokens. This removes the
      token class entirely.
- [ ] **Backups/PITR:** both projects are on the Free plan, with no platform
      backups and no PITR. Decide on a paid plan. Until then, the #810 dump is the
      only way back.
- [ ] **RLS step 2d:** generate and import our ES256 key, rotate it in on
      staging first, then set `SUPABASE_JWT_SIGNING_KEY` and `SUPABASE_ANON_KEY`
      on Railway. Required before `db_user_scope` leaves `off`.
- [ ] **Railway config in the repo:** commit a `railway.toml`. None exists today,
      so service settings live only in the UI (plan item #114).
- [ ] **Railway worker service:** run `cd /app && python -m worker` on the same
      image and variables, before turning on `jobs_queue`.
- [ ] **One manual Google sign-in on staging** after #815 merges (oauthlib 3→4),
      and once on prod after the promote.
- [ ] Confirm the **`school_match` same-school-only** decision in #813.
- [ ] Merge, approve and promote. These are blocked for the agent in auto mode.

---

## 9. What ran

**Restack after the final pass (2026-11-08).** All four migrations, with their DB
tests and the policy generator, moved into one PR, #821. #811 and #816 were
closed, and the stack above was rebased with their commits dropped. The new top
commit has a tree **byte-identical** to the tree the final pass below ran on, so
those results hold for the new top. #812–#815 differ from their old trees only by
the files that now sit below them in #821, and CI re-ran on every restacked PR.
The SHAs in the CI table are the pre-restack ones.

Hermetic (backend, CI env and ignore list, primary venv):

| Point in the stack | Result |
|---|---|
| W1c + W1a + W1d + W2c + W2a combined | 4676 passed, 0 failed |
| Through W2b (#817) | 4748 passed, ruff clean |
| **Top (#818 W3a, final)** | **4793 passed, 0 failed**, ruff clean |

CI per PR (`gh pr checks`, 2026-11-08 ~11:00Z). "integration" is the
real-Supabase lane. CodeRabbit is "skipping" on every stacked PR because their
bases are not whitelisted.

| PR | Backend (pytest) | Frontend | integration | evals | Workers build |
|---|---|---|---|---|---|
| #809 | pass | pass | pass | — | pass |
| #810 | pass | pass | pass | — | pass |
| #811 (closed, now in #821) | pass | pass | pass | — | pass |
| #821 | pass | pass | pass | — | pass |
| #812 | pass | pass | pass | — | pass |
| #813 | pass | pass | pass | — | pass |
| #814 | pass | pass | pass | pass | pass |
| #815 | pass | pass | pass | — | pass |
| #816 (closed, now in #821) | pass | pass | pass | — | pass |
| #817 | pass | pass | pass | pass | pass |
| #818 | pass | flake, rerun requested* | pass | pass | pass |
| #819 | pass | pass | pass | — | pass |

After the #821 restack (2026-11-08 ~19:30Z), every PR, #810, #821, #812–#815 and #817–#820, re-ran and is green. #821's first integration run failed: one test imported `services/jobs.py`, so it was moved back to #817.

Earlier CI reds on #813 to #816 were GitHub infra failures (the `supabase`
setup-cli download returned 504) and a vitest flake in `EmailBroadcasts`. All of
them are green on rerun.

\* #818 changes no frontend file. Its one Frontend failure was the same
`EmailBroadcasts.test.tsx` "polls history every 5s" timing flake; the failed
job was rerun (run 42472506629).

Final local E2E pass: one flock'd `make e2e-up` cycle on the stack top, with a
Python 3.13 venv installed from `requirements.lock` and function mode:

<!-- FINAL-PASS-RESULTS -->
- **run 2** (`3c9632ef`): integration **234 passed / 2 failed**, Playwright
  **105 passed / 14 skipped**, oracles **0 findings**.
  - The `syllabus/apply` enforce-matrix case expected 404 and got 403. That was
    a wrong expectation in the #818 test: the handler answers 403 for both a
    missing and a foreign document. Fixed in `f93398ae`.
  - The bucket-completeness check found 11 stray tables (`learner_state`,
    `check_items`, `misconceptions`, and others) left in the persistent local DB
    by the unmerged learning-loop branch. None of them come from this stack, and
    CI's fresh database passed the same check on #817.
- **run 3** (stack top `c9c0c007`, everything except this docs PR): **all green.**
  `make e2e-up` ok. Integration lane **235 passed / 0 failed**: the cross-user
  matrix in `off` and in `enforce`, the RLS lockdown and policy tests, and the jobs
  queue. The bucket-completeness check was deselected locally only, because of the
  stray learning-loop tables described above; CI's fresh database still runs it.
  Playwright **105 passed / 14 skipped / 0 failed**. Oracles **0 findings**.
  `make e2e-down` clean. The backend venv was built from `requirements.lock` on
  Python 3.13, as in CI, so the run exercised #815's re-lock.
- Run 1 never booted. The encryption canary refused the worktree's
  `.env.local.example` key against the persistent local DB, which was written under
  the primary checkout's key. That is the canary working as designed; the worktree
  then used the primary's local `ENCRYPTION_KEY`. Note: these runs applied this
  stack's migrations (RLS 2a/2b/2c and jobs) to your **local** Supabase DB. They are
  additive, so switching back to `main` locally is fine.
<!-- /FINAL-PASS-RESULTS -->

---

## 10. Open findings not fixed tonight

These come from #812's static review and #819's measurement. None of them is
fixed in this release. The confidence column says how sure the review was.

| Finding | Where | Severity | Confidence |
|---|---|---|---|
| **SSRF.** The Quizlet import fetches any user-supplied URL, follows redirects and does no host check. | `services/flashcard_import_service.py::scrape_quizlet_url` (`:183`, `follow_redirects=True` at `:191`) | high | high |
| `link_concept` accepts a foreign concept node id. That creates a cross-user `note_concepts` row and lets a caller test whether a node exists. | `services/notes_service.py::link_concept` | med | high |
| `course_id` writes (upload, scan-concepts, notes create) have no enrollment check. Student B may be able to push into another class's shared chunk pool. | `routes/documents.py`, the concepts scan, `routes/notes.py` | med | medium |
| The public profile GET does not filter soft-deleted users. `/api/profile/{id}/roles` is unauthenticated and reveals who is an admin. | `routes/profile.py` (`:837` roles) | low/med | high |
| `study-guide/regenerate` deletes the caller's cached guide before it validates the exam. | `routes/study_guide.py::regenerate_guide` (`:429`) | low | high |
| The flashcards course lookup filters a `courses.user_id` column that does not exist, so a PostgREST 400 is swallowed and the code falls back. | `routes/flashcards.py:135` | low | high |
| 5 `async def` handlers call sync `table()` and block the event loop: `quiz.generate_quiz` (`quiz.py:1986`), `admin_documents.reindex`, `careers.apply`, `gradescope.save_credentials_via_bu_sso`, `profile.upload_user_avatar`. | `docs/design/async-db-client.md` §1 | perf | high |
| `school_match` is now same-school only (#813). Andres to confirm that this is the intended product behaviour. | `routes/social.py` | decision | — |
| Stored cross-room `reply_to_id` rows are hidden on read but stay in the table. `edit_room_message` and `delete_room_message` do not check `room_id`; both are author-gated, so this is not a leak. | `routes/social.py` | low | high |
| `room_messages` remains outside RLS policies until step 2e (the realtime JWT bridge). On staging, which has RLS off, anon can read room messages. | `docs/security/realtime-jwt-bridge-design.md` | med (staging) | high |
