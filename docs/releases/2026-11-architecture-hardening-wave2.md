# Release plan: architecture hardening wave 2 to production (Nov 2026)

Trov handoff #24, sprint #28, tickets #114 to #119. Written 2026-11-08/09 at the
end of the wave-2 stacked-PR run. Every SHA, count and command below was read
from git, `gh` or the migration files on the wave-2 branches. Nothing here has
run against staging or production. It is the companion of the wave-1 doc,
`docs/releases/2026-11-architecture-hardening.md` (on `main`), and it replaces
that doc's promote plan: wave 1 never reached prod, so one promote now ships
both waves.

**TL;DR**

- Production still runs `6ed0f13c` (#748, 2026-10-23). Wave 1 (#809 to #821)
  merged to `main` on 2026-11-08 between 20:27Z and 20:54Z and **was not
  promoted**. The next promote ships everything on `main` (40 non-merge commits
  since prod) plus the 16 wave-2 PRs (#826 to #840 and this doc) once they
  merge.
- All six wave-2 migrations are in **one PR, #826**, at the bottom of the stack.
  Merging it migrates staging with all six at once. Every one is additive and
  inert until a flag (or a worker) turns its consumer on.
- Prod runs **14 new migrations** in total: wave 1's 8 and wave 2's 6. #772's
  `20261106055333_state_machines_audit.sql` still changes data and drops two
  columns, so `make promote` still needs `--allow-destructive` (§7).
- Five new flags (`realtime_rls`, `llm_budget`, `llm_outage_drill`,
  `async_db_client`, `stateless_rate_limit`) join wave 1's three. All default
  `off`. Unflagged changes are the six security fixes (#827 to #832), the
  off-loop hops and the flag version check in #839, and the LLM-usage
  attribution in #838 (§1b).
- Merge bottom to top through GitHub's stack, the way wave 1 went in (§2).
- Nothing changes on Railway until someone sets `SAPLING_IMAGE_TARGET` or
  applies `.railway/railway.ts`. The worker service, the signing key, and the
  API image cut-over are human steps (§9).

---

## 1. What prod gets

`git ls-remote origin production` returns `6ed0f13c` ("Merge pull request #748
from SaplingLearn/main", 2026-10-23 23:32 -0400). `origin/main` is `a4af5e26`
(#825). Prod deploys from the `production` branch; `make promote`
(`backend/promotion/`) migrates the prod DB, then merges `main` into
`production`, pinned to the SHA it audited. `main` deploys staging and
migrates the staging DB on every merge (`migrate-staging.yml`).

- `git log --oneline --no-merges origin/production..origin/main`: 40 commits.
- The wave-2 stack adds 80 non-merge commits: `origin/main...harden2/w9-complexity-ratchet`
  is 150 files, +23.6k/−0.5k.
- Prod to the stack top: 115 non-merge commits, 564 files, +113k/−11k.

### 1a. Already on `main`, not yet on prod

**Before wave 1 (13 PRs).** Detail and risk notes are in the wave-1 doc §1a.

| PR | Commit | What | Risk |
|---|---|---|---|
| #677 | c4c4d45e | PostHog backend (one consent queue); migration `analytics_opt_out` | med |
| #675 | 7148b204 | PostHog frontend | low |
| #754 | 2f685518 | E2E screens into Figma frames | low (tooling) |
| #772 | 02209c59 | State-machine audit, one combined migration that **changes data and drops columns** | **high** |
| #796 | 139188ab | Drops the 3D graph; "Mastery colors" mode | low |
| #798 | 9d3f3374 | Dashboard "Today's plan", Study/Tree/shell, brand assets (includes teammate #753) | med |
| #802 | e47b9a33 | Onboarding token course search | low |
| #805 | dce61cfd | `xp_events` idempotency per student (constraint change; backfill script after) | med |
| #806 | d22b0aeb | Index sweeper defaults to on in production only | low |
| #807 | 9153482e | RLS on every public table; anon/authenticated revoked | **high** (needed) |
| #803 | d1860dc9 | Course-centred radial graph layout | low |
| #804 | 2be7b924 | Admin account tools (seed/wipe/copy) | med |
| #808 | f2c77e05 | Phase 0 CVE upgrades (next, katex, mermaid, cryptography, pillow, pypdf) | med |

**Wave 1 (11 PRs, merged 2026-11-08 20:27Z to 20:54Z).** Detail in the wave-1
doc §1b.

| PR | Commit on main | What | Risk |
|---|---|---|---|
| #809 | 83d303f0 | Hardening plan + RLS step-2 plan (docs) | none |
| #810 | a19737b9 | `pg_dump` before `make promote` migrates; `make backup-db` | low |
| #821 | 2f006d4c | All four wave-1 migrations: RLS 2a/2b/2c and the `jobs` queue | low (inert) |
| #812 | 971b675a | Cross-user test matrix | none |
| #813 | 34b81fbe | **Security fix:** 4 cross-user leaks in `routes/social.py`; `school_match` same-school only | low |
| #814 | 6c550ce5 | LLM retries, timeouts, breaker; fallback behind `llm_fallback` | **med** (active with the flag off) |
| #815 | 066ac3e6 | Re-lock of 12 transitive dependencies (oauthlib 3→4, logfire 4→5) | med |
| #817 | f66edc83 | `services/jobs.py`, `python -m worker`, course context behind `jobs_queue` | low |
| #818 | 9b939510 | User-scoped PostgREST client behind `db_user_scope` | low (off) / high (enforce) |
| #819 | 4fd5dca3 | Async DB client design doc | none |
| #820 | 9ed39835 | The wave-1 release doc | none |

**After wave 1 (3 PRs, all frontend, all by Andres).**

| PR | Commit on main | What | Risk |
|---|---|---|---|
| #822 | ef3a3f5d | `@opennextjs/cloudflare` 1.20.16 for Next 16.4 | low |
| #824 | a85ba0ae | Gummi heading font | low |
| #825 | a4af5e26 | Streak flame spacing; graph physics after a drag | low |

The only teammate code in the whole range is #753 (lpcooper-arch), inside
#798. Re-check before you start: `git fetch && git log --oneline a4af5e26..origin/main`.

### 1b. The wave-2 stack (none merged yet)

The stack was cut from `a85ba0ae` (#824). #825 landed on `main` afterwards; it
touches only `TodayColumn.tsx` and `KnowledgeGraph2D*`, which no wave-2 PR
touches, so expect a clean restack. Every PR is still a **draft**.

| # | PR | Branch | What | Risk | Why |
|---|---|---|---|---|---|
| 1 | #826 | `harden2/db-migrations` | **All six wave-2 migrations** (§3) and their SQL-only tests | low | Additive tables, functions, indexes, one policy, one `canopy_metrics()` redefinition. Nothing changes existing rows. |
| 2 | #827 | `harden2/w4-quizlet-ssrf` | **Security fix (SSRF, high):** Quizlet import allowlists `quizlet.com`/`www.quizlet.com`, validates every redirect hop, refuses non-public IPs, pins the connection to the checked IP, ignores proxy env | low | A submitted non-Quizlet URL is a 400; a redirect away is a 422 (Paste fallback); `http://` links are upgraded. Prod at `6ed0f13c` still fetches any URL with `follow_redirects=True`. |
| 3 | #828 | `harden2/w4-study-guide-regenerate` | Regenerate validates and generates **before** deleting the cached guide; deletes only older rows | low | A failed regenerate no longer wipes the student's guide. |
| 4 | #829 | `harden2/w4-flashcards-course-filter` | Flashcard generation finds the course's documents (it ran with **zero** documents before: a 400 on a nonexistent `courses.user_id` was swallowed); Study sends `course_id` | low-med | Outputs and token use change for students with documents. A free-text topic with no enrolled match now gets no documents, never the whole library. |
| 5 | #830 | `harden2/w4-link-concept-owner` | `link_concept` refuses a node the caller does not own (404); idempotent re-link; cleanup script for old cross-user rows | low | Re-link 500 → 200; unlinking a missing link 200 → 404. |
| 6 | #831 | `harden2/w4-course-enrollment-checks` | Course-keyed writes (upload, upload/sync, scan-concepts, notes create/move, start-session) need an enrollment in the course | **med-low** | A student enrolled only in a past term now writes to that term's offering instead of minting a current-term one. |
| 7 | #832 | `harden2/w4-profile-roles-deleted` | `/roles` needs a session; soft-deleted profiles 404; anonymous viewers lose roles and role cosmetics; deleted accounts leave leaderboard/friends/room lists | low-med | Visible: deleted accounts disappear from lists. |
| 8 | #833 | `harden2/w5a-realtime-rls-2e` | RLS step 2e: `GET /api/auth/realtime-token` and the study-room client behind `realtime_rls` | low (off) | Flag off: the anon subscription now waits for flags to load (a few hundred ms). Its migration is in #826. |
| 9 | #834 | `harden2/w5b-shadow-runbook` | Actionable `db_user_scope` shadow report (`GET /api/admin/analytics/db-scope`), `scripts/mint_scope_token.py`, runbook `docs/security/db-user-scope-rollout.md` | none (off) | Nothing runs with the flag off (pinned by a test). |
| 10 | #835 | `harden2/w6a-upload-index-jobs` | Upload pipeline and first index attempt on the job queue behind `jobs_queue` (`document.process`, `document.index`) | low (off) / med (on) | Flag off: one cached flag read per upload; `/upload/sync` adopts a duplicate's saved row instead of a 500. On: bytes travel through Postgres (20 MB cap). |
| 11 | #836 | `harden2/w6b-images-railway-upkeep` | Dockerfile `api`/`worker`/`full` targets via `SAPLING_IMAGE_TARGET`; `.railway/railway.ts` (worker service, unapplied); heartbeat, prune, `GET /api/admin/jobs`; `scripts/latency_check.py` | low | Default build is still `full`. **The `api` image is not safe to serve yet** (§9). |
| 12 | #837 | `harden2/w6c-gradescope-job` | Gradescope sync on the job queue behind `jobs_queue`; `GET /api/gradescope/sync/{course}/status`; the modal polls on 202/504 | low (off) / med (on) | Flag off: answers pinned byte for byte against the old route. BU SSO (Chromium) stays in the request. |
| 13 | #838 | `harden2/w7-llm-budget-cost-drill` | Per-user daily token budget (`llm_budget`), weekly LLM cost per active user + 2x-jump signal, `llm_outage_drill` flag, `/api/admin/llm`, runbook `docs/ops/llm-outage-drill.md` | low (off) / med (on) | **Unflagged:** LLM-usage rows with no user are now attributed to the acting user, so per-user numbers rise (totals unchanged); a vision-OCR page whose rescue raised is no longer cached. |
| 14 | #839 | `harden2/w8-async-stateless` | Async DB seam behind `table()` (`async_db_client`), the 5 blocking handlers off the loop, `GET /api/quiz/attempts` async end to end, Postgres rate limiter (`stateless_rate_limit`), cross-replica flag version check, locust + `loadtest.yml` | low-med | **Unflagged:** the off-loop hops, a version read every 5 s while requests flow (`FEATURE_FLAGS_VERSION_CHECK_S`), and `db.sync_on_loop` WARNs from the 22 allowlisted paths (expected). |
| 15 | #840 | `harden2/w9-complexity-ratchet` | ruff C901 (max 25) + route-file length ratchet over `backend/code_size_baseline.json`; `docs/design/domain-modules.md` | none (runtime) | Process cost: teammate PRs that grow a baselined file fail CI (§11). |
| 16 | this PR | `harden2/release-doc` | This file | none | Docs only. |

---

## 2. Merge order and how to merge the stack

Bottom to top: #826, #827, …, #840, then this PR. Every PR depends on the one
below it.

### What actually worked in wave 1

Read from the PR timelines (`gh api .../issues/<n>/timeline`):

- At 20:27:48Z every wave-1 PR was added to **one GitHub stack**
  (`added_to_stack`).
- #810 targeted the non-PR branch `stack/base`. Deleting that branch
  (20:31:35Z) made GitHub move #810 onto `main` by itself
  (`automatic_base_change_succeeded`, 20:31:36Z).
- From then on each merge did the rest: when #810 merged (20:34:12Z), GitHub
  changed #821's base to `main` (20:34:14Z) and **force-pushed #821 rebased
  onto the new `main`** (20:34:20Z), and the PRs above it too. Andres merged the
  next PR 20 to 40 seconds later, and so on up the stack. The last one (#820)
  merged at 20:54:48Z.
- **Squash worked.** 7 of the 11 were squash-merged (#809, #810, #821, #812,
  #813, #814, #820); #815, #817, #818 and #819 went in as merge commits. Both
  restacked cleanly, because GitHub rebases the PRs above onto the squashed
  commit. The wave-1 doc's "never squash" warning only applies to a stack that
  you retarget by hand without GitHub's stack support.
- `deleteBranchOnMerge` is `false`, so the `harden/*` heads still exist. Delete
  them whenever you like; nothing targets them any more.
- `migrate-staging.yml` ran once, when #821 merged (run 42520853126, 20:34:53Z,
  2m43s, green), and applied all four wave-1 migrations.

### Wave 2

All 15 wave-2 PRs are in one GitHub stack (#826 added 22:38:53Z, #840
23:13:52Z). #826 already targets `main`, so there is no base branch to delete.

```bash
# 0. Before the first merge
gh pr ready 826 827 828 829 830 831 832 833 834 835 836 837 838 839 840   # all are drafts
for n in $(seq 826 840); do gh pr checks $n; done                       # every head green

# 1. #826 is every wave-2 migration. Merging it runs migrate-staging.yml for all six.
gh pr merge 826 --squash
gh run list --workflow migrate-staging.yml --limit 1        # wait for success (wave 1's took ~3 min)
#    then check the staging ledger (§6 step 3) before going on.

# 2..15. For each N in 827 … 840, in order: wait for GitHub to move N onto main
#        and force-push it rebased ("automatic base change" + "force-pushed" in
#        the PR timeline), then
gh pr merge N --squash          # or --merge; both restacked cleanly in wave 1

# 16. This PR the same way.
```

- **CI on the restacked heads.** In wave 1 each PR was merged before CI re-ran
  on its rebased head. That was fine because every head had passed CI first.
  The careful version is `gh pr checks N --watch` after each restack. Do at
  least that for #831 (the enrollment gate) and #839 (the async seam), which
  have the widest unflagged surface.
- **If a teammate merges to `main` mid-stack**, the next restack rebases onto
  it. If GitHub reports a conflict, resolve it on that PR's branch and push;
  do not rebase reviewed commits of PRs further up by hand.
- **CodeRabbit** is "skipping" on all 15 (drafts and non-whitelisted bases).
  The reviews that gated these PRs are the per-PR `/code-review` passes in §10.
- Each PR still needs whatever approval the repo requires. The agent cannot
  merge or approve in auto mode.

---

## 3. New migrations, in apply order

`git diff --name-status origin/production harden2/w9-complexity-ratchet -- backend/db/migrations/`
lists 14 added files. The first 8 are wave 1's; the wave-1 doc §3 has their
detail and reverse SQL, unchanged. The last 6 are wave 2's, all in #826:

```
20261016064813_analytics_opt_out.sql                 #677   (wave-1 doc §3 #1)
20261106055333_state_machines_audit.sql              #772   (wave-1 doc §3 #2, destructive)
20261108063442_xp_events_per_user_idempotency.sql    #805   (wave-1 doc §3 #3)
20261108082151_rls_on_every_table.sql                #807   (wave-1 doc §3 #4)
20261108092633_rls_app_auth_helpers.sql              #821   (wave-1 doc §3 #5)
20261108094129_rls_policies.sql                      #821   (wave-1 doc §3 #6)
20261108094130_rls_authenticated_grants.sql          #821   (wave-1 doc §3 #7)
20261108095241_jobs_queue.sql                        #821   (wave-1 doc §3 #8)
20261108210944_rls_room_messages_realtime.sql        #826   (W1 below)
20261108212226_document_uploads.sql                  #826   (W2)
20261108213311_llm_budgets_and_cost_signal.sql       #826   (W3)
20261108213623_jobs_upkeep.sql                       #826   (W4)
20261108214227_gradescope_syncs.sql                  #826   (W5)
20261108220438_stateless_rate_limit_and_flag_version.sql  #826   (W6)
```

`db/migrate.py` applies each file in its own transaction and commits it; a
failure stops the chain at that file. Staging already has the first 8
(`migrate-staging.yml`, last run 2026-11-08 20:34:53Z). W1 to W6 reach staging
together when #826 merges. `promotion.preflight.scan_destructive` finds
nothing in W1 to W6; it flags only #772's two `DROP COLUMN`s.

An earlier draft of #826 had a seventh file, `20261108215504_canopy_llm_cost_keys.sql`.
The review folded its Canopy keys into W4 and deleted it, so W4 is wave 2's
only `canopy_metrics()` redefinition. The PR body's table still lists it; the
branch does not have it.

| # | File | From | What | Inert until | Reverse (from the file header) |
|---|---|---|---|---|---|
| W1 | `20261108210944_rls_room_messages_realtime.sql` | #833 | `app_auth.realtime_uid()` (only `iss=sapling-realtime`), SECURITY DEFINER `app_auth.is_room_member_realtime(room_id)`, policy `room_messages_select_member` (SELECT, TO authenticated). `GRANT SELECT ON room_messages TO authenticated` **only where RLS is already on** (prod). Does **not** enable RLS on `room_messages` or revoke anon SELECT: that is a manual step (§4, `realtime_rls`). | `realtime_rls` (or `db_user_scope`) mints a token; the manual enable step | `DROP POLICY IF EXISTS room_messages_select_member ON public.room_messages; DROP FUNCTION IF EXISTS app_auth.is_room_member_realtime(text); DROP FUNCTION IF EXISTS app_auth.realtime_uid();` The grant is harmless to leave. To restore prod's exact prior ACL: `REVOKE SELECT ON public.room_messages FROM authenticated;`, but check `\dp room_messages` first and skip it if the grant predates W1. |
| W2 | `20261108212226_document_uploads.sql` | #835 | `document_uploads` staging table (encrypted `file_data`/`result`), `prune_document_uploads(days, limit)`. Service-only (RLS on, no policies). | `jobs_queue` | Turn `jobs_queue` off, let in-flight uploads finish, check `SELECT stage, count(*) FROM public.document_uploads GROUP BY 1;`, then `DROP FUNCTION IF EXISTS public.prune_document_uploads(integer, integer); DROP TABLE IF EXISTS public.document_uploads;` |
| W3 | `20261108213311_llm_budgets_and_cost_signal.sql` | #838 | `llm_budgets` (seeded default 2,000,000 tokens/UTC day), `llm_budget_status(user)`, `llm_cost_per_active_user_weekly()`; restates `idx_llm_usage_user_created` (0035, a no-op where it exists). Service-only. | `llm_budget` (the cost function is read by an admin route and by W4's `canopy_metrics()`) | **Reverse W4 first** (its `canopy_metrics()` calls the cost function, and a `LANGUAGE sql` body records no dependency). Turn `llm_budget` off. Then `DROP FUNCTION IF EXISTS public.llm_cost_per_active_user_weekly(); DROP FUNCTION IF EXISTS public.llm_budget_status(text); DROP TABLE IF EXISTS public.llm_budgets;` Leave `idx_llm_usage_user_created` (0035 owns it). |
| W4 | `20261108213623_jobs_upkeep.sql` | #836 (+#838 keys) | `heartbeat_job()`, `prune_jobs()`, two partial indexes on `jobs`; `canopy_metrics()` re-created from #772's #760 block plus `counts.jobs_dead_lettered`, `totals.jobs_queue_depth` and four `totals.llm_*` keys (integers, omitted when there is no honest answer). | a worker built from #836; the Canopy keys appear on the next hourly poll | `DROP FUNCTION IF EXISTS public.prune_jobs(integer, integer); DROP FUNCTION IF EXISTS public.heartbeat_job(uuid, text, integer); DROP INDEX IF EXISTS public.jobs_succeeded_updated_idx; DROP INDEX IF EXISTS public.jobs_dead_updated_idx;` then re-run the "#760 canopy_metrics" block of `20261106055333_state_machines_audit.sql` (from its `CREATE OR REPLACE FUNCTION canopy_metrics()` through its `NOTIFY`). Stop the worker first, or every heartbeat logs a warning. |
| W5 | `20261108214227_gradescope_syncs.sql` | #837 | `gradescope_syncs` staging table (one active sync per enrollment, partial unique index), `prune_gradescope_syncs(days, limit)`. No password, cookie or Gradescope text. Service-only. | `jobs_queue` | Turn `jobs_queue` off, let in-flight syncs finish, check `SELECT stage, count(*) FROM public.gradescope_syncs GROUP BY 1;`, then `DROP FUNCTION IF EXISTS public.prune_gradescope_syncs(integer, integer); DROP TABLE IF EXISTS public.gradescope_syncs;` |
| W6 | `20261108220438_stateless_rate_limit_and_flag_version.sql` | #839 | `rate_limit_hits` + `claim_rate_limit(key, limit, window)`; `feature_flags_version` + statement triggers on `feature_flags` and `feature_flag_targets` (not on TRUNCATE). | `stateless_rate_limit` for the limiter. **The version triggers are live at once**: every flag write bumps the one-row table. #839's code reads it every 5 s; older code never does. | Turn `stateless_rate_limit` off. `DROP TRIGGER IF EXISTS trg_feature_flags_bump_version ON public.feature_flags; DROP TRIGGER IF EXISTS trg_feature_flag_targets_bump_version ON public.feature_flag_targets; DROP FUNCTION IF EXISTS public.bump_feature_flags_version(); DROP TABLE IF EXISTS public.feature_flags_version; DROP FUNCTION IF EXISTS public.claim_rate_limit(text, integer, integer); DROP TABLE IF EXISTS public.rate_limit_hits;` The app falls back to the per-process limiter and the 30 s TTL on its own. |

**Reverse order for wave 2:** W6, W5, W4 (restoring `canopy_metrics()`), W3,
W2, W1. Then, only if you are also taking wave 1 out, the wave-1 doc's order:
jobs, 2c, 2b, 2a; leave #807, #805 and #677 in place; #772 has no reverse.

**Old prod code against the new schema.** Between the migrate step and the new
deploy going live, prod still runs `6ed0f13c`. Wave 1's caveat holds: after
#772 drops `courses.deleted_at`, `services/topic_checklist_service.py:51`
500s until the new code is live (wave-1 doc §3). Wave 2 adds nothing old code
reads or writes: new tables, new functions, a policy on a table prod already
denies, and extra `canopy_metrics()` keys that an older image forwards
unchanged.

---

## 4. Flags

All declared in `backend/services/feature_flags.py::REGISTRY`, all default
`off`. A flag resolves in this order: env override, fail-closed, user rule,
role rule, rollout, default (§8.1 for what that means for turning one off).

| Flag | From | Variants | Scope | Client-visible | Kill switch |
|---|---|---|---|---|---|
| `realtime_rls` | #833 | off / on | Per user | **yes** (`Social.tsx` reads it) | `SAPLING_FLAG_REALTIME_RLS=off` |
| `llm_budget` | #838 | off / on | Per user (role rules and rollouts apply) | no | `SAPLING_FLAG_LLM_BUDGET=off` |
| `llm_outage_drill` | #838 | off / anthropic / google / both | **Global** (`user_id=None`) | no | Unset `SAPLING_FLAG_LLM_OUTAGE_DRILL`, default `off`. Refused in `APP_ENV=production` (also what an unset `APP_ENV` means) unless `SAPLING_LLM_FORCE_OUTAGE_ALLOW_PRODUCTION=yes`. A flag-store outage resolves to `off`, so the store can never arm it. |
| `async_db_client` | #839 | off / on | Per user, resolved once per request | no | `SAPLING_FLAG_ASYNC_DB_CLIENT=off` |
| `stateless_rate_limit` | #839 | off / on | **Global** | no | `SAPLING_FLAG_STATELESS_RATE_LIMIT=off` |
| `llm_fallback` | #814 (wave 1) | off / on | **Global** | no | `SAPLING_FLAG_LLM_FALLBACK=off` |
| `jobs_queue` | #817 (wave 1); #835 and #837 add uploads, indexing and Gradescope | off / on | Per student who triggered the work | no | `SAPLING_FLAG_JOBS_QUEUE=off` |
| `db_user_scope` | #818 (wave 1) | off / shadow / enforce | Per user, once per request | no | `SAPLING_FLAG_DB_USER_SCOPE=off`. A flag-store outage resolves to `off`, the **less** secure side for this flag. |

### Order after the promote

Leave every flag off for at least a day of prod traffic first. Then, each one
on staging before prod:

1. **`realtime_rls`.** Precondition: step 2d is done (§9) and
   `SUPABASE_JWT_SIGNING_KEY` is set and trusted by that project's Realtime;
   without it the token endpoint answers 503 and the room falls back to
   REST-only. **This one fixes something on prod:** prod has had RLS on for
   `room_messages` with zero policies since June, so live study-room chat
   delivers nothing there today (W1's header). Ladder: admins (role rule),
   then a rollout, then default `on` with no `off` rules. Watch 503s on
   `/api/auth/realtime-token` and Realtime `CHANNEL_ERROR`s. Then, **staging
   only**, the manual close-the-anon-path step, as the migration role:
   ```sql
   BEGIN;
   GRANT SELECT ON public.room_messages TO authenticated;
   ALTER TABLE public.room_messages ENABLE ROW LEVEL SECURITY;
   REVOKE SELECT ON public.room_messages FROM anon;
   COMMIT;
   ```
   Prod already has RLS on and no anon SELECT, and W1 already made the
   grant. Pin the end state in a new migration afterwards
   (`docs/security/realtime-jwt-bridge-design.md` "Enable sequence", steps
   4–5). Before this step, staging's anon key still reads room messages.
2. **`llm_budget`.** Check the seeded default first:
   `GET /api/admin/llm/budgets` (2,000,000 tokens per UTC day, a runaway guard,
   not a study limit). Ladder: admins, then 10/50/100%. Watch 429s with
   `code=LLM_BUDGET_EXCEEDED` and `GET /api/admin/llm/budgets/status/{user_id}`.
   Raise a limit with `PUT /api/admin/llm/budgets`.
3. **`llm_outage_drill`, staging only**, then **`llm_fallback`** on prod.
   This is #814's acceptance test. Follow `docs/ops/llm-outage-drill.md`:
   staging's Railway `GEMINI_API_KEY` must be real; set
   `SAPLING_FLAG_LLM_OUTAGE_DRILL=anthropic` with `llm_fallback` on, run
   `backend/scripts/llm_outage_drill.py`, expect no user-facing errors and
   `llm_usage` rows on `gemini-*`. Remove the variable straight after. Then
   turn `llm_fallback` on in prod with the stored default. Do not drill prod.
4. **`async_db_client`.** Today only `GET /api/quiz/attempts` uses the `a*`
   twins end to end, so the blast radius is small. Ladder: admins, then
   10/50/100%. Watch 5xx on that route and p95. Graduate after one release
   at 100% (the registry comment).
5. **`stateless_rate_limit`.** Global, so it is one switch. Required before
   any second API replica (until then each replica keeps its own limiter).
   Watch for the "falling back to the per-process limiter" warning and
   `SELECT count(*) FROM rate_limit_hits;` staying bounded.
6. **`jobs_queue`.** Precondition: the Railway worker service (§9) is running
   on that environment. With the flag on and no worker, aggregation and
   indexing only queue, and uploads and Gradescope syncs wait 30 s and then run
   inline. Ladder: staging 10% then 100%, then prod 10/50/100%. Measure chat
   time to first token under an upload locally first
   (`python backend/scripts/latency_check.py --pdf <50-page.pdf> --flag both`).
   Watch `GET /api/admin/jobs`, `SELECT status, count(*) FROM jobs GROUP BY 1`,
   Canopy's `totals.jobs_queue_depth` and `counts.jobs_dead_lettered`.
7. **`db_user_scope`.** The longest ladder; its shadow phase can start any time
   after step 2d. Follow `docs/security/db-user-scope-rollout.md` exactly:
   staging default `shadow` with `DB_USER_SCOPE_SHADOW_SAMPLE_RATE=1`, read
   `GET /api/admin/analytics/db-scope` daily, stop at any `status=401`; then
   admins on `enforce`, rollout 10/50/100, default `enforce`; then the same on
   prod with a separate key. An empty shadow report is not proof by itself:
   the cross-user matrix under enforce and the integration lane are the gate.

Runbooks: `docs/security/db-user-scope-rollout.md`,
`docs/security/realtime-jwt-bridge-design.md` ("Step 2e (shipped)"),
`docs/ops/llm-outage-drill.md`, `docs/deploy/railway.md`.

---

## 5. New env vars and Railway services

From `git diff origin/main harden2/w9-complexity-ratchet -- backend | grep -E 'getenv|environ'`
plus the worker's CLI defaults. Wave 1's (`SUPABASE_JWT_SIGNING_KEY`,
`SUPABASE_ANON_KEY`, `SAPLING_MODEL_FALLBACK_<TASK>`, the PostHog and
`ACCOUNT_SYNC_*` sets, `INDEX_SWEEPER_ENABLED`) are in the wave-1 doc §4.

| Var | From | Where | Default | Needed when |
|---|---|---|---|---|
| `SAPLING_IMAGE_TARGET` | #836 | Railway service variable, read as a Docker build arg | unset or empty = `full` (today's image) | `worker` on the new worker service. `api` on the API service only after the cut-over conditions in §9. Anything else fails the build. A change needs a redeploy (it is a build input). |
| `JOBS_POLL_INTERVAL_SECONDS`, `JOBS_BATCH`, `JOBS_LEASE_SECONDS`, `JOBS_MAX_HEARTBEAT_SECONDS`, `JOBS_PRUNE_AFTER_DAYS`, `JOBS_LOG_FORMAT` | #817, #836 | worker | 5 / 10 / 300 / 3600 / 14 / `text` | Optional. `JOBS_LEASE_SECONDS` below 300 (`MIN_LEASE_SECONDS`) makes the worker exit 2 at boot. `JOBS_PRUNE_AFTER_DAYS=0` turns pruning off. CLI flags override all of them. |
| `UPLOAD_JOB_PICKUP_GRACE_SECONDS` | #835 | API | 30 | Optional. How long an upload waits for a worker before running inline. |
| `GRADESCOPE_JOB_PICKUP_GRACE_SECONDS` | #837 | API | 30 | Optional. The same for a Gradescope sync. |
| `DB_USER_SCOPE_SHADOW_SAMPLE_RATE` | #834 | API, read at boot | 0.1 | Optional. Staging sets `1` during the shadow phase. A tuning knob, not a gate. |
| `SAPLING_LLM_FORCE_OUTAGE_ALLOW_PRODUCTION` | #838 | API (+ worker) | unset | **Never set in prod** except for a deliberate prod drill, and remove it straight after. A safety interlock, not a feature gate. |
| `SAPLING_LLM_FORCE_OUTAGE` | removed by #838 | — | — | Replaced by the `llm_outage_drill` flag. If it is still set anywhere, the backend logs a boot WARNING and ignores it. |
| `FEATURE_FLAGS_VERSION_CHECK_S` | #839 | API (+ worker) | 5 | Optional. `0` turns the cross-replica version check off; the 30 s snapshot TTL still applies. |
| `SAPLING_FLAG_REALTIME_RLS`, `SAPLING_FLAG_LLM_BUDGET`, `SAPLING_FLAG_LLM_OUTAGE_DRILL`, `SAPLING_FLAG_ASYNC_DB_CLIENT`, `SAPLING_FLAG_STATELESS_RATE_LIMIT` | #833–#839 | API + worker | unset | Kill switches (§4, §8). `SAPLING_FLAG_LLM_OUTAGE_DRILL` is also how a staging drill is armed. |
| `SUPABASE_JWT_SIGNING_KEY` | #818 (wave 1) | API + worker | unset | Now also needed by `realtime_rls` (503 without it), not only `db_user_scope`. A secret. |
| `SAPLING_DRILL_SESSION` | #838 | the operator's shell | — | `scripts/llm_outage_drill.py` against a remote; never a Railway variable. |
| `target_url` (workflow input) | #839 | `.github/workflows/loadtest.yml` | **none, required** | `workflow_dispatch` only; an empty target fails before anything is sent. Never point it at prod without a reason. |

**Railway services.**

- **New: `worker`** (#836, `.railway/railway.ts`, runbook `docs/deploy/railway.md`).
  Same repo and Dockerfile, `SAPLING_IMAGE_TARGET=worker`, start command
  `python -m worker`, 1 replica, no domain, no healthcheck. Its variables are
  Railway references to the API service: 54 names (`BOOT_VARIABLES`,
  `HANDLER_VARIABLES`, `FLAG_KILL_SWITCHES`, `MODEL_SLOT_VARIABLES`), minus the
  ones the API does not set, which go in `NOT_ON_API` per environment. The
  file is a **partial** that owns only the worker; the API service is behind
  `MANAGE_API = false`. It is **unapplied and unverified against the live
  project**: whether a raw `${{svc.VAR}}` string is accepted as a reference is
  still an open item in the runbook. `railway.toml` was not used because
  Railway stops reading config-as-code files on 2026-12-01 (docs.railway.com,
  read 2026-11-08).
- **API service:** unchanged by this release. Leave `SAPLING_IMAGE_TARGET`
  unset (`full`) until §9's cut-over.
- `scripts/e2e-up.sh` gains `E2E_WORKER=1` (local only) to start a worker
  beside the local backend.

---

## 6. Pre-promote

1. **Reviews and approvals.** Every PR got a `/code-review` at high effort and
   its findings were fixed in that PR (§10). Each still needs its own approval
   and must leave draft.
2. **Merge the stack** as in §2. Merging #826 migrates staging; every merge to
   `main` redeploys staging.
3. **Check staging after the merges:**
   - Ledger: `SELECT filename FROM schema_migrations ORDER BY filename DESC LIMIT 15;`
     lists all 14 files of §3.
   - `gh run list --workflow migrate-staging.yml --limit 3` is green for #826.
   - Supabase **Security Advisor** (staging): still **exactly one** "RLS
     Disabled in Public" finding, on `room_messages` (W1 does not enable it).
     The five new tables have RLS on with no policies.
   - Smoke, flags off. Sign in with real Google once (oauthlib 4, #815). Then:
     tutor chat; a quiz and the quiz history list (#839's async route); upload
     a document to a course you are enrolled in (#831); generate flashcards
     from a course in Study and check they cite your documents (#829); import a
     Quizlet set by URL (#827); regenerate a study guide (#828); link and
     unlink a concept on a note (#830); open your own and someone else's
     profile, and the leaderboard (#832); a study room's live chat (#833's
     flag-off path); a Gradescope sync if you have a linked course (#837);
     KaTeX and mermaid rendering (#808).
   - `GET /api/internal/metrics` with the Canopy token: `totals.jobs_queue_depth`
     and `counts.jobs_dead_lettered` are present (an idle queue is a measured
     0).
   - Admin endpoints answer 200: `GET /api/admin/jobs`,
     `GET /api/admin/llm/drill` (`forced_outage.variant` is `off`),
     `GET /api/admin/llm/budgets`, `GET /api/admin/analytics/db-scope`,
     `GET /api/admin/analytics/llm/cost-per-active-user`.
   - Railway staging logs: no `EncryptionKeyMismatch`, no
     `encryption key check skipped`. `db.sync_on_loop` WARNs from the
     allowlisted learn/notes/documents paths are expected (§11).
4. **Read-only prod pre-checks.** Wave 1's checks still apply (prod has run
   none of the 14 migrations); wave 2 adds three. Each of the wave-1 counts, if
   non-zero, makes a migration raise or delete rows.
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
   -- ── wave 1 (see the wave-1 doc §5 step 4 for what each one means) ──
   SELECT count(*) AS courses_deleted_at_set FROM courses WHERE deleted_at IS NOT NULL;
   SELECT count(*) AS memberless_rooms FROM rooms r WHERE NOT EXISTS (SELECT 1 FROM room_members m WHERE m.room_id = r.id);
   SELECT count(*) AS orphan_room_members   FROM room_members   x WHERE NOT EXISTS (SELECT 1 FROM rooms r WHERE r.id = x.room_id);
   SELECT count(*) AS orphan_room_activity  FROM room_activity  x WHERE NOT EXISTS (SELECT 1 FROM rooms r WHERE r.id = x.room_id);
   SELECT count(*) AS orphan_room_messages  FROM room_messages  x WHERE NOT EXISTS (SELECT 1 FROM rooms r WHERE r.id = x.room_id);
   SELECT count(*) AS orphan_room_summaries FROM room_summaries x WHERE NOT EXISTS (SELECT 1 FROM rooms r WHERE r.id = x.room_id);
   SELECT count(*) AS orphan_reply_to       FROM room_messages  x WHERE x.reply_to_id IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM room_messages p WHERE p.id = x.reply_to_id);
   SELECT count(*) AS xp_dupes FROM (SELECT 1 FROM xp_events GROUP BY user_id, idempotency_key HAVING count(*) > 1) d;
   SELECT tablename, tableowner FROM pg_tables WHERE schemaname = 'public' AND tableowner <> current_user;
   -- ── wave 2 ──
   -- none of wave 2's tables may exist yet (expect 0 rows)
   SELECT tablename FROM pg_tables WHERE schemaname = 'public'
     AND tablename IN ('jobs','document_uploads','llm_budgets','gradescope_syncs','rate_limit_hits','feature_flags_version');
   -- W3 restates this index; if it is missing (expect true) W3 builds it under a lock on llm_usage
   SELECT to_regclass('public.idx_llm_usage_user_created') IS NOT NULL AS llm_usage_index_present;
   -- W6 puts triggers on these; both must exist (expect 2)
   SELECT count(*) AS flag_tables FROM pg_tables WHERE schemaname = 'public'
     AND tablename IN ('feature_flags','feature_flag_targets');
   -- what is pending: the ledger count now; expect +14 after the promote
   SELECT count(*) AS applied FROM schema_migrations;
   ROLLBACK;
   SQL
   unset PGPASSWORD DBURL
   ```
5. **Backup.** `make promote` takes a `pg_dump` itself (stage 2, #810) and
   stops if it fails. You can also take one beforehand with
   `make backup-db ENV=prod` (→ `backups/prod-<UTC>.dump`, mode 0600, checked
   with `pg_restore --list`). The manual recipe, with the password kept off
   argv, is in the wave-1 doc §5 step 5. The dump holds production data:
   never commit it or copy it off the machine unencrypted.
6. **Checkout hygiene.** Run `make promote` from an up-to-date, clean `main`;
   preflight blocks if the local `db/migrations/` differs from `origin/main`.
   The primary checkout **still** has an uncommitted edit to
   `backend/promotion/runner.py` (deploy-wait progress lines, noted in the
   wave-1 doc). Commit or stash it before `git pull`.
7. `STAGING_SUPABASE_DB_URL` set (the aws-1 session pooler) so the
   staging-ran-it-first check passes; `gh` authenticated; podman available.
8. **Railway prod variables** before the deploy: none are required. Check that
   `SAPLING_LLM_FORCE_OUTAGE` and `SAPLING_LLM_FORCE_OUTAGE_ALLOW_PRODUCTION`
   are **not** set on prod, and that `SAPLING_IMAGE_TARGET` is unset on the API.

---

## 7. The promote and verification

```bash
make promote ARGS="--allow-destructive"
```

`--allow-destructive` is required for #772's `DROP COLUMN users.current_room_id`
and `DROP COLUMN courses.deleted_at`; wave 2 adds no finding. Read them when
the runner prints them. The topic-checklist 500 window (§3) is the known cost.

The stages: preflight, **backup**, snapshot, migrate (the irreversible step:
14 files), snapshot and diff, a pause where you answer `y`, the merge
`main → production` pinned to the audited SHA, the deploy wait on
`/api/health`, and the smoke tests (`backend/promotion/smoke.py` against
`api.saplinglearn.com` and `saplinglearn.com`).

**Verify after it finishes:**

1. **Wave 1's checks** (wave-1 doc §6, steps 1–4): the anon key reaches no
   table (`graph_nodes?select=id&limit=0` with `$ANON` → 401) and cannot
   execute `match_course_chunks` (→ 401); Security Advisor shows **0** "RLS
   Disabled in Public" errors on prod; the boot passes the encryption canary;
   `/api/health` reports the new `production` SHA.
2. **Ledger:** `SELECT count(*) FROM schema_migrations` equals the pre-check
   count plus **14**.
3. **Wave 2's objects:** `SELECT version FROM feature_flags_version;` returns one
   row; `SELECT scope, subject, daily_token_limit FROM llm_budgets;` returns the
   seeded default (`'default'`, `''`, 2000000).
4. **Endpoints** (as an admin): the five admin endpoints of §6 step 3 answer
   200; `GET /api/auth/realtime-token` answers **404** (flag off);
   `GET /api/internal/metrics` (Canopy token) carries the two `jobs_*` keys.
5. **Smoke:** `make promote` runs it. Later, without touching the DB:
   `make promote ARGS="--verify-only"`.
6. **Post-promote data repairs** (each dry-run by default; read the output,
   then run for real):
   - `scripts/backfill_achievement_xp.py` (#805, wave 1).
   - `scripts/cleanup_cross_user_note_concepts.py` (#830), from `backend/`:
     `dotenv -f .env.production run -- python scripts/cleanup_cross_user_note_concepts.py`,
     check the project host it prints, then add `--apply`. Do staging first.
     It deletes `note_concepts` rows linking a note to another student's
     node, written before #830; it has not run anywhere yet.
7. Spot-check by hand in prod: Google sign-in, tutor chat, quiz, an upload, a
   flashcard generation, the graph, a profile. Then, a day later, start on the
   flags in §4.

---

## 8. Rollback plan

1. **Flags first.** A flag resolves: env override, fail-closed, user rule,
   role rule, rollout, default. **Setting only the stored default to `off`
   does not turn the flag off** for anyone a user rule, a role rule or the
   rollout already covers.
   - **Everyone, guaranteed:** set the env override on Railway, on the API
     **and** the worker service: `SAPLING_FLAG_REALTIME_RLS=off`,
     `SAPLING_FLAG_LLM_BUDGET=off`, `SAPLING_FLAG_ASYNC_DB_CLIENT=off`,
     `SAPLING_FLAG_STATELESS_RATE_LIMIT=off`, `SAPLING_FLAG_JOBS_QUEUE=off`,
     `SAPLING_FLAG_DB_USER_SCOPE=off`, `SAPLING_FLAG_LLM_FALLBACK=off`; for the
     drill, **remove** `SAPLING_FLAG_LLM_OUTAGE_DRILL`. The env override wins
     over every rule. A Railway variable change redeploys the service, so
     allow for one deploy (minutes).
   - **No deploy:** in `/admin/flags`, delete the flag's user and role
     targets, set the rollout to 0, **and** set the default to `off`. With
     #839 each process notices within about 5 s under traffic (the version
     check), never later than its 30 s snapshot.
   - `realtime_rls` off sends clients back to the anon subscription on their
     next flags refresh. On staging after the manual close-the-anon-path step,
     that path delivers nothing until you roll that step back too
     (`GRANT SELECT ... TO anon; ALTER TABLE ... DISABLE ROW LEVEL SECURITY;`,
     never on prod).
   - `jobs_queue` off: in-flight queued uploads and syncs still finish on the
     worker if it is running; new ones run inline. Keep the worker running
     until `document_uploads` and `gradescope_syncs` have no `queued`/`running`
     rows.
   - Not behind a flag: wave 1's #814 timeouts/retries/breaker, and wave 2's
     unflagged changes in §1b. Undoing those takes a code revert.
2. **Code.** Revert the promotion's merge commit on `production` (the runner
   prints the revert command when smoke fails), or revert individual stack
   commits on `main` and re-promote. A `production` hotfix must be
   back-merged into `main`, or the next preflight blocks
   (`production-diverged`). Reverting code leaves the schema in place. That is
   safe for every wave-2 migration (additive, and the code that uses them is
   flag-gated); it is not strictly safe for #772 (old code reads
   `courses.deleted_at`).
   **A reverted merge stays reverted.** After `git revert -m 1` of the
   promotion merge, the next promote of `main` does **not** bring those
   commits back: git treats them as already merged. If that revert is
   back-merged into `main`, it removes the work from `main` too. To re-ship
   after the fix, first revert the revert (`git revert <revert-sha>`) on
   `main`, then promote. When only one PR is at fault, prefer reverting that
   PR's squash commit on `main` and re-promoting.
3. **Migrations.** Apply the reverse SQL from §3 by hand as the migration
   role, newest first: W6, W5, W4 (restore `canopy_metrics()` from #772's
   block), W3, W2, W1. Turn the matching flag off and check the staging
   tables are empty first. Wave 1's reverse is in the wave-1 doc §3/§7.
4. **Data.** Wave 2's tables hold only staging rows, counters and admin
   config; nothing in them needs restoring except a hand-tuned `llm_budgets`
   (note your overrides before dropping it). For wave 1's #772 data (dropped
   columns, deleted rooms), restore from the pre-promote dump
   (`backups/prod-<UTC>.dump`) following `backend/promotion/README.md` →
   "Backups", rehearsed on the local stack first:
   - **Never `--data-only` into a live table that already has rows.** The COPY
     aborts on the first duplicate key and restores nothing; `-L` picks whole
     archive entries, not rows.
   - Restore the needed tables into a **scratch** database (the local stack or
     a throwaway container):
     `pg_restore --no-owner --no-acl -d "$SCRATCH" --table=users --table=courses --table=rooms --table=room_members --table=room_messages <dump>`.
   - Re-add the dropped columns on prod (wave-1 doc §3 #2), export only what
     you need from the scratch DB with `\copy (SELECT ...) TO '...csv' CSV`,
     `\copy` it into a temp table on prod, then `UPDATE ... FROM tmp` /
     `INSERT ... ON CONFLICT (id) DO NOTHING`.
   - Take a fresh dump of prod before any restore over it. Connect with the
     password in `PGPASSWORD` by name, never in a URI on argv (§6 step 4).

---

## 9. Human-only steps (Andres)

- [ ] **RLS step 2d: our ES256 signing key**, staging first, a separate key for
      prod. `docs/security/db-user-scope-rollout.md` §2: generate it, import
      it as a **standby** key, test the standby, rotate it in. Then set
      `SUPABASE_JWT_SIGNING_KEY` (one JWK, a secret) and `SUPABASE_ANON_KEY` on
      the Railway API **and** worker services, and confirm the boot WARNING
      about missing keys is gone. `scripts/mint_scope_token.py --show-key`
      prints only alg, kid, fingerprint and the public JWK. Required before
      `realtime_rls` or `db_user_scope` leaves `off`. Never revoke the key
      while any user is past `off`.
- [ ] **Railway worker service** (`docs/deploy/railway.md` steps 1–5):
      `railway config pull`, fix the constants at the top of
      `.railway/railway.ts`, fill `NOT_ON_API` from
      `railway variables --service backend --kv`, `railway config plan` (it
      must only **create** `worker`; any delete means stop), `railway config
      apply`, never `--confirm-destructive`. Healthy when the log shows
      `worker.boot` then `worker.started`. Staging first. Required before
      `jobs_queue`.
- [ ] **API image cut-over, in this order, later.** The `api` image has no OCR
      stack and no Chromium, so it is safe only when nothing on the request
      path needs them:
      1. the worker service runs on that environment and `jobs_queue` is on
         for 100% of students (uploads extract on the worker);
      2. the other inline OCR callers (`routes/extract.py`, flashcard import,
         syllabus import in `services/calendar_service.py`) move to jobs or
         you accept text-layer-only extraction there;
      3. Gradescope BU SSO (`login_via_bu_sso`, Chromium, needs the student's
         password and a live Duo tap) becomes a worker job with a poll
         endpoint (not built);
      4. then set `SAPLING_IMAGE_TARGET=api` on the API service, redeploy,
         check `/api/health` and `make promote ARGS="--verify-only"`.
      Rollback at any point: unset the variable (or set `full`) and redeploy.
- [ ] **Supabase Auth:** turn "Allow new users to sign up" **off** on staging
      and prod, and delete the stray prod Auth user (wave-1 doc §8). Both
      `app_auth.uid()` and `app_auth.realtime_uid()` already ignore GoTrue
      tokens.
- [ ] **Backups/PITR:** both projects are on the Free plan, with no platform
      backups and no PITR. Decide on a paid plan. Until then the #810 dump is
      the only way back. (The Free plan's 500 MB DB limit also matters for
      queued uploads, below.)
- [ ] **`school_match`:** confirm the same-school-only rule from #813. Wave 2
      deliberately did not touch it.
- [ ] **Queued uploads over 20 MB / Supabase Storage.** With `jobs_queue` on,
      files up to 20 MB travel through Postgres (`document_uploads.file_data`,
      cleared at a terminal stage; disk returns only after vacuum); bigger ones
      run inline. A Storage bucket is the better transport but is a new bucket
      plus policies. Decide whether to build it before `jobs_queue` reaches
      100%.
- [ ] **Run `scripts/cleanup_cross_user_note_concepts.py`** on staging, then
      prod (§7 step 6). Dry-run first.
- [ ] **One manual Google sign-in** on staging after the merges and on prod
      after the promote (#815's oauthlib 4 is only covered offline).
- [ ] **Teammate PRs and the ratchet** (§11): tell the authors of #750, #751,
      #752, #801, #673, #735 and #717 before #840 merges, or merge theirs
      first.
- [ ] Merge, approve and promote. These are blocked for the agent in auto mode.

---

## 10. What ran

### Review

Every wave-2 PR got its own `/code-review` at high effort, and its findings
were fixed **in that PR** before the restack (the PR bodies carry an
addendum per fix round). What the reviews found and what changed:

| PR | Main findings → fix |
|---|---|
| #826 | Seven files with two `canopy_metrics()` redefinitions → canopy LLM keys folded into W4 and `20261108215504` deleted. LLM cost reported $0 for an unpriced week → NULL / key omitted. Jump computed from the unrounded ratio → from the published 4-dp ratio, `ratio_pct` clamped. Missing default budget row meant unlimited → built-in 2M fallback. Version upsert at epoch ms (self-healing row); TRUNCATE dropped from the triggers. Bounded rate-limit prune outside the key lock. `document_uploads.document_id` index; retention prunes for both staging tables; `BACKEND_RPCS` pins. |
| #827 | Redirect failures were 400 (no Paste fallback) → 422. `http://` links rejected → upgraded. NAT64/6to4 judged by the wrapper → by the embedded IPv4. DNS rebinding window → connection pinned to the checked IP, `trust_env=False`. Unbounded DNS → 5 s limit, one resolve per host, one client across hops. UrlTab branches on the status. |
| #828 | Two workers regenerating at once could each delete the other's new row (`id=neq`) → delete only `generated_at < new`. Cleanup failure 500'd a paid generation → best-effort. Stale-material drop also deleted older guides → skipped. |
| #829 | Unbounded all-documents fallback, current-term-only reads, arbitrary pick among same-named courses, N+1, silent `except` → root fix: Study sends `course_id`; reads by course across terms (50 newest); bounded deterministic name match; no whole-library fallback; failures logged. |
| #830 | Re-link 500 → idempotent upsert. FK race 500 → 404. extract-concepts did per-node probes → one bulk write. Unlink did not check the node → checked. Old cross-user rows → cleanup script. |
| #831 | CI's `POST /api/notes` 404→200 was the matrix's case order, not the gate → `SELF_ENROLLING` ordering. Gate and write could pick different terms → one read returns the enrolled offering the write uses. Gaps → note move (PATCH) and start-session gated; scan-concepts gated on the document's course; replay lookup before the gate. |
| #832 | Roles leaked to anonymous viewers via `featured_role`/role cosmetics → stripped. Integration probe tested a user without roles → seeded admin, all matrix modes. A 503 served the anonymous view → propagates. Deleted users still on leaderboard/friends/rooms → filtered (no rank gap). Shared `_live_user_or_404`. |
| #833 | Channels never recovered after token expiry; refresh failures could leave channels on a rejected token; a flagged student could join with the anon key before flags loaded; per-room lifecycle reverted and re-minted on every room switch; an old revert could land after a new token → supervised channels, expiry timer, wait-for-flags, permanent-error latch, one ref-counted screen-level lifecycle with a serialized `setAuth` chain, signed `exp` returned. |
| #834 | `write_other_user` missed `in.`/`neq.`/`not.` filters, owner columns other than `user_id` and write-rpc user params → covered, and documented as a one-sided heuristic. `report_denied` derived the op from the HTTP verb → takes the call site's op (upsert is not insert). NaN/inf sample rate → rejected (falls back to 0.1). Unscoped-WARN flood → once per (route, table) per process, every occurrence still counted. Tally and report keys disagreed → one `scope_report.key_of()`. Unbounded report scan → 20k events, ≤ 168 h, `truncated` flag. Runbook: an empty report is not proof; the matrix under enforce is the gate. |
| #835 | Stale attempts could move an upload's stage backwards → owner-fenced CAS writes, takeover after a quiet lease. One DB blip 500'd the stream → retried, 10 in a row ends it. Two requests could both run one upload inline → token-owned take-back, outcome recorded. `result` kept after delivery → cleared. Abandoned and soft-deleted rows → re-staged. Shared `documents_read` decrypt. |
| #836 | Heartbeat paced by the running worker's lease left jobs exposed to shorter-lease claimers → fleet-wide `MIN_LEASE_SECONDS = 300`. N replicas pruned N times → one per hour. Worker env incomplete → 54 references + a test that re-derives them. Empty `SAPLING_IMAGE_TARGET` broke the build → defaults to `full`, `target-check` stage. Admin paging, latency script cache and TTL fixes. Staging-table prunes wired into `jobs.prune`. |
| #837 | Joined requests could run one sync twice → token-owned take-back + recorded outcome. Unguarded poll loop → DB-error budget. Error-code mapping split → one `response_for_outcome`. Abandonment by age → by job liveness. No link re-check in the worker → re-checked twice. 180 s held thread and a 504 → 60 s, then 202 + a status route the modal polls. |
| #838 | Unattributed LLM usage escaped the budget → attributed to the acting user; worker jobs run as their user. Budget refusals in OCR were swallowed and cached → propagate, not cached. Budget read per model request → once per request/job, foreground only. `read_status` leaked threads → per-call rpc timeout. Drill as an env var → `llm_outage_drill` flag + the prod interlock. One shared off-loop flag read. |
| #839 | Limiter rpc unbounded and retried while the DB was down → bounded, marks the store down. A failed version read → marks the flag store down; no read on cold reloads. Blocking avatar/careers handlers → plain `def`. Ratchet missed aliases and attribute forms → fixed. One threadpool for the hops. Locust from a hash-pinned lock. `arpc` mirrors `rpc`'s shadow handling. |
| #840 | ruff config could exclude a function from C901 → `--isolated` with explicit settings + a bypass test. Offenders keyed by score → by qualname. Slack failed CI → warns. `--shrink` re-checks. Baseline re-recorded at the stack top after all fixes. |

### CI

- **Hermetic** (backend, CI env and ignore list): full suite at the final stack
  top `9ba0af26` = **5510 passed / 345 skipped / 0 failed**, ruff clean, code-size
  ratchet clean.
- **CI:** every PR was green on every check (Backend, Frontend, integration with
  the cross-user matrix in `off` and `enforce`, Workers build, evals where present)
  after the last review-fix restack. Two frontend timing flakes needed a rerun
  earlier (`Study.races.test.tsx`, `EmailBroadcasts.test.tsx`; neither is touched by
  wave 2). The only real CI failure was a test bug in #832's new probe (a UUID
  passed to JSON), fixed there. The stack was then rebased onto main `a4af5e26`
  (which includes #825) as GitHub stack #841. Re-check before merging with
  `for n in $(seq 826 840) 845; do gh pr checks $n; done`.

### Final local E2E pass

One flock'd `make e2e-up` cycle on the stack top (integration lane, Playwright,
oracles, `make e2e-down`):

<!-- FINAL-PASS-RESULTS -->
Run on 2026-11-09 against the stack top `e15ce587` (main `a4af5e26` plus all 16
PRs), function-mode LLM seam, in two flock'd cycles. Each cycle tore down cleanly.

| | Run 1: flags off | Run 2: `jobs_queue` + `realtime_rls` on, `E2E_WORKER=1` |
|---|---|---|
| Integration lane | 333 passed, 1 failed | 330 passed, 1 failed, 3 errors |
| Playwright | 104 passed, 1 failed, 14 skipped | 104 passed, 1 failed, 14 skipped |
| Oracles | 0 findings | 0 findings |

The cross-user matrix passed in both `off` and `enforce`, and so did the new
#830, #831 and #832 probes. No leak was found. With the flags on, the queued
upload journey (`upload.spec.ts`, through the worker) and the study-room live
chat (`study-room.spec.ts`, using the minted Realtime token) both passed.

What failed, and what was done:
- **Integration, `test_quiz_subcutaneous_db.py::test_generate_persists_exam_days_away_when_an_exam_is_upcoming`
  (both runs):** a timezone artifact, not fixed here. The test computes "today
  + 5" in the machine's local time (EST, still 2026-11-08), but the server counts
  days from UTC (already 2026-11-09 at 01:00Z), so it got 4. CI runs in UTC and
  passes it. Follow-up: make the test use the same UTC date as
  `services/exam_proximity`.
- **Integration, 3 setup errors (run 2 only):** the integration reseed raced
  the live worker's `course_context.refresh` upserts on `offering_concept_stats`
  and got a 409. This is a test-harness race only. Fixed in #835 (commit
  5a3d8580): the seed helpers treat a unique violation (23505) as "row present".
- **Playwright `quiz-written.spec.ts` (both runs):** an existing caret race on
  **main** (main failed 6/6 when run in isolation), not a wave-2 regression. The
  brackets key moved the caret in a `requestAnimationFrame`, so fast keystrokes
  could land first. Fixed in #833 (commit 74e96b5a: the caret is applied in a
  `useLayoutEffect`, with vitest coverage). After the fix the spec passed 10/10
  on the new top `9ba0af26`, run on its own.

Not re-run after those two fixes: the full Playwright suite, the integration
lane and the oracles. Each fix touched only its own file (the seed helper, and
`WrittenAnswer.tsx`).

These runs applied wave 2's migrations to the local Supabase DB. They are
additive.
<!-- /FINAL-PASS-RESULTS -->

---

## 11. Open findings and follow-ups (not fixed in this release)

*Updated 2026-11-09 after #850 and #851 merged: the last column says which PR closed each item. The wave-3 release note, `docs/releases/2026-11-architecture-hardening-wave3.md`, carries what is still open.*

| Finding | Where | Severity | Note | Closed by |
|---|---|---|---|---|
| **22 sync-DB-on-loop call sites remain** on async handlers: 17 in `routes/learn.py` (the tutor turn path, including `chat_stream`'s pre-stream reads), 3 in `routes/notes.py`, 2 in `routes/documents.py`. They are allowlisted in `tests/test_no_sync_db_in_async_handlers.py` (the list may only shrink) and log `db.sync_on_loop`. | #839 | **perf, the biggest TTFT issue** | Next phase-3 step: move the tutor path onto the `a*` twins. | **#850** (allowlist 22 → 0) |
| `document_jobs.py` and `gradescope_jobs.py` implement the same staged-job state machine twice (stage/attach/re-stage, token take-back, owner-fenced claim, liveness, watch loop). | #835, #837 | maintainability | Proposal in #837's addendum: one `services/staged_jobs.py`, after both land, with the two test files as the net. | **#850** (`services/staged_jobs.py`) |
| The upload pipeline exists twice (the SSE route and the worker's `_run_agents`). | #835 | maintainability | Phase 4 (#118): one `run_document_agents(text, deps, on_stage)` yielding stages. | **#850** (`agents/document.py::run_document_agents` + `services/document_pipeline.py`) |
| `GET /api/admin/jobs` counts unfinished rows by scanning (capped at 10,000, with a truncated flag). | #836 | low | A `jobs_overview()` SQL aggregate (GROUP BY type, status) needs a migration. | **#850** (`jobs_overview()`; falls back to the scan until it exists) |
| `GET /api/admin/analytics/db-scope` aggregates `events` in Python over a capped scan (20k events, ≤ 168 h). | #834 | low | A SQL GROUP BY function needs a migration. | **#850** (`db_scope_divergences()`; falls back to the scan until it exists) |
| Duplicate study-guide rows are prevented in code only. | #828 | low | `UNIQUE(user_id, offering_id, exam_id)` after deduping existing rows, in its own migration PR. | **#850**, once `ensure_study_guides_unique_key()` is run by hand (wave-3 doc §4) |
| **The code-size ratchet will fail teammate PRs** that grow a baselined route file or push a function over 25: #750, #751, #752, #801, #673, #735, #717 touch baselined files. | #840 | process | Merge theirs first, or have them split / hand-raise the ceiling in `code_size_baseline.json` (a reviewed edit). | Superseded by **#851**: the baseline is empty, so every PR now meets ≤ 600 / ≤ 25; open teammate PRs must also rebase onto the split modules (wave-3 doc §9) |
| **The API image still needs Chromium** for Gradescope BU SSO, and OCR for `extract`, flashcard import and syllabus import. | #836, #837 | blocks the cut-over | §9. | open |
| A 20 MB queued upload is a ~27 MB JSON body to PostgREST over the 30 s sync client. **Untested on hosted Supabase.** | #835 | med (flag on) | Test on staging before `jobs_queue` goes wide, or lower `QUEUED_UPLOAD_MAX_BYTES`, or move to Storage (§9). | open |
| Budget refusals on study guide, flashcards, social summary, concept describe and course summary map to those routes' existing generic error (e.g. 502), not a 429. | #838 | low (flag on) | Only the tutor, quiz and uploads have the friendly 429. | **#850** for concept describe, study guide and flashcards; the room summary stays 200 on purpose; course summary unchanged |
| `/api/admin/llm/budgets` does not show the built-in 2M default when the default row is missing. | #826, #838 | low | | **#850** (`builtin: true`) |
| A tab loaded before the deploy reads a Gradescope 202 body as counts (only for syncs over 60 s with `jobs_queue` on). | #837 | low | | open |
| `GET /api/notes/user/{id}?course_id=` still filters on the current-term offering. | #831 | low | The frontend never sends it. | **#850** |
| Room activity history still names soft-deleted users. | #832 | low | | **#850** |
| `.railway/railway.ts` is unverified against the live project (reference syntax). | #836 | — | Runbook step 3's plan is the check. | open |
| **Wave-1 §10 items still open:** the `school_match` same-school decision (#813); stored cross-room `reply_to_id` rows stay in the table (hidden on read), and `edit_room_message`/`delete_room_message` do not check `room_id` (author-gated, not a leak); `room_messages` stays outside RLS on staging until the manual step after `realtime_rls` is at 100% (§4). | wave 1 | low/decision | The other wave-1 §10 findings (Quizlet SSRF, `link_concept`, course-write enrollment, profile roles/deleted, study-guide regenerate, flashcards `courses.user_id`, the 5 blocking async handlers) are fixed by #827–#832 and #839. | Partly **#850** (`edit_room_message`/`delete_room_message` check `room_id`); the rest open |
