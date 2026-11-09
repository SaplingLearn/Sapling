# Release note: architecture hardening waves 3 and 4, and the combined prod promote (Nov 2026)

Trov handoffs #26 and #27, tickets #117 (phase 3) and #118 (phase 4). Written
2026-11-09, after both PRs merged to `main`. Every SHA, count and command below
was read from git, `gh` or the migration files on `main`. Nothing here has run
against production; on staging, only the migrations have run (by
`migrate-staging.yml`).

Naming: this doc calls **#850 (phase 3, async + stateless API) "wave 3"** and
**#851 (phase 4, domain modules) "wave 4"**. The Trov handoffs call both of them
"wave 3". It follows the wave-2 doc,
`docs/releases/2026-11-architecture-hardening-wave2.md`, which it extends
rather than replaces: that doc's §6 pre-checks, §7 verification, §8 rollback and
§9 human steps still apply, with the additions below.

**TL;DR**

- Production still runs `6ed0f13c` (#748, 2026-10-23). Waves 1 and 2 merged to
  `main` on 2026-11-08 and **were never promoted**, so **one promote now ships
  waves 1–4**: 242 non-merge commits, 799 files, +144k/−25k, and **19
  migrations** (§6).
- Wave 3 (#850) adds **five migrations**, all additive and inert until a flag
  or a person turns the consumer on (§2). Staging applied them when #850 merged
  (`migrate-staging.yml` run 42569303747, 2026-11-09 05:47Z, green).
- Two new global flags, `stateless_locks` and `stateless_tutor_sessions`, both
  default `off`. The replica track turns them on in this order:
  `stateless_rate_limit` → `stateless_locks` → `stateless_tutor_sessions` →
  (optional) `async_db_client`, then `API_REPLICAS = 2` (§3, §5). **Once
  `stateless_tutor_sessions` is on, do not turn it off.**
- One manual post-deploy step per environment:
  `SELECT public.ensure_study_guides_unique_key();` (§4).
- Wave 4 (#851) moves code only: no migrations, no flags, no data effect
  (§1b). The code-size baseline is now empty and import-linter runs in CI.
- `make promote` still needs `--allow-destructive` for #772 (wave 1). Waves
  2–4 add no destructive finding.

---

## 1. What shipped

Merged to `main` on 2026-11-09 (UTC), in this order:

| PR | Merge commit | What | Risk |
|---|---|---|---|
| #847 | 93e37256 | `concept_edges` agent slot + `scripts/backfill_concept_edges.py` (concept-to-concept edges so courses draw with real ring depth). Not on the request path. | low |
| #848 | 01e36a6f | Graph links drawn rim to rim | low (frontend) |
| #849 | 74c68f5a | Quiz answer screens per format, clickable question pager | low-med (frontend) |
| **#850** | ec51657c | **Wave 3 / phase 3: async + stateless API**, five migrations, the wave-2 §11 leftovers | low with flags off |
| **#851** | 826a6b1c | **Wave 4 / phase 4: domain modules**, complexity, import contracts | low (moves only) |
| #852 | 38db6a75 | Numbered local E2E slots, off the dev ports (tooling only; CI's browser lane stays main-only) | none (runtime) |
| #853 | 6dd92410 | `docs/frontend-testids.md` for the quiz home | none |

### 1a. Wave 3: #850, async + stateless API

Every new behaviour is behind a default-off flag. With all flags off the app
behaves as before, apart from the small unflagged fixes at the end of this
list.

- **The event loop no longer blocks on the tutor turn path.** The sync-DB
  allowlist in `tests/test_no_sync_db_in_async_handlers.py` went from 22
  entries to 0: the tutor turn helpers (now in `services/tutor/`),
  `services/chat_stream.py`, `services/tutor_sessions.py`'s async twins, notes
  `_course_meta` and documents `_validate_user`. Each turn loads its course and
  message history concurrently (the biggest time-to-first-token item). A
  coroutine `on_complete` in `chat_stream` runs under `asyncio.shield`, so a
  client disconnect still persists the turn.
- **Hot routers on the `a*` seam:** graph (`get_user_graph`,
  `get_user_recommendations`, `list_courses`), quiz (`get_attempt`,
  `answer_question`, `abandon_attempt`, `generate_quiz`'s reads), learn
  (`mode_switch`, `list_sessions`, `resume_session`), documents (list, delete,
  update). Write handlers that call `apply_graph_update` or `run_agent_sync`
  stay sync. With `async_db_client` off, the `a*` calls run the sync client on
  the same threadpool, so behaviour is identical.
- **Replica-safe state:** `services/pg_lease.py` + `app_leases` (flag
  `stateless_locks`) for the study-guide single-flight, admin account
  operations and consumed OAuth nonces; `tutor_pending_sessions` (flag
  `stateless_tutor_sessions`) for lazily started tutor sessions and their
  end/delete tombstones, materialised in one SQL transaction. The table is
  wiped with the account and never bundled.
- **`.railway/railway.ts`:** `replicas: API_REPLICAS` on the API service,
  committed as **1**. It takes effect only with `MANAGE_API` (§5).
- **Nightly load test:** `.github/workflows/loadtest-nightly.yml`, which runs
  only when the repo variable `LOADTEST_TARGET_URL` is set, and
  `loadtest/check_thresholds.py`, which fails the run on p95 ≥ 300 ms for any
  non-LLM route, chat TTFT p95 ≥ 3 s, or more than 1 % failures.
- **Wave-2 §11 leftovers:** one staged-job state machine
  (`services/staged_jobs.py`) behind `document_jobs` and `gradescope_jobs`; one
  upload pipeline (`agents/document.py::run_document_agents`, mapped to SSE
  events by `services/document_pipeline.py`); `jobs_overview()` behind
  `GET /api/admin/jobs` (new field `outstanding_oldest`) and
  `db_scope_divergences()` behind `GET /api/admin/analytics/db-scope`, both
  falling back to the old capped scan while the function is missing; the
  non-destructive `study_guides` key (§4).
- **Unflagged fixes:** concept describe, study guide and flashcards answer the
  friendly 429 on a budget refusal (`llm_budget.reraise_budget_refusal`); the
  room summary stays 200 with the budget message on purpose.
  `/api/admin/llm/budgets` shows the built-in 2M default (`builtin: true`) when
  the default row is missing. Room-message edit and delete check `room_id`
  (404 on a mismatch); room activity drops soft-deleted users.
  `GET /api/notes/user/{id}?course_id=` covers every offering of the course.
  The study-guide insert replaces a guide in place on a unique violation, so it
  works with or without the new index.

### 1b. Wave 4: #851, domain modules

No migrations and no flags. Route files over 600 lines were split into thin
routes over `services/<domain>/` packages, bodies moved verbatim under their
own names. `/openapi.json` is byte-identical for quiz and learn.

| Route | Lines before → after | Package |
|---|---|---|
| quiz | 3,148 → 182 | `services/quiz/` (absorbs the ten `services/quiz_*.py`) |
| learn | 2,010 → 166 | `services/tutor/` (`chat_stream.py`, `tutor_router.py`, `tutor_sessions.py` stay flat) |
| documents | 1,423 → 528 | `services/documents/` |
| auth | 1,173 → 539 | `services/auth/` |
| social | 1,131 → 272 | `services/social/` |
| admin | 1,005 → 419 | `services/admin/` |
| profile | 978 → 492 | `services/profile/` |
| gradescope | 868 → 538 | `services/gradescope/` (absorbs `gradescope_service.py`, `gradescope_jobs.py`) |
| flashcards | 700 → 501 | `services/flashcards/` (absorbs `flashcard_import_service.py`) |
| admin_analytics | 655 → 377 | `services/admin/analytics/` |
| gradebook | 649 → 466 | `services/gradebook/` (absorbs `gradebook_service.py`) |

- **Done-when met:** `backend/code_size_baseline.json` is empty (no route file
  over 600 lines, no function over McCabe 25) and `ruff.toml` has no `C901`
  per-file ignore outside `tests/**`.
- `apply_graph_update` validates a typed `GraphUpdate`
  (`services/graph_update_model.py`); plain dicts are accepted exactly as
  leniently as before (0 mismatches over 20,000 random inputs). Malformed input
  now raises before any write instead of after a partial batch, and a failed
  context refresh is logged instead of swallowed. `_get_user_stat` is a
  dispatch table (`_STAT_READERS`).
- **Import boundaries in CI:** `backend/.importlinter`, run by `lint-imports`
  in `ci.yml` after ruff, plus `tests/test_import_contracts.py`. Layering
  `routes | worker` → `services : agents : models` → `db`, and a domain reaches
  another only through its package `__init__`. 17 known exceptions are listed
  with reasons. New dev dependency: `import-linter==2.15` with `grimp==3.18`.
- **Shims, on purpose and temporary:** each route re-exports every moved name
  and each moved flat module is a `sys.modules` alias at its old path, so open
  teammate PRs keep working (§9).
- **Logger names:** moved auth code now logs as `services.auth.*`; update any
  log filter keyed on `routes.auth`. Quiz and learn code still logs as
  `routes.quiz` / `routes.learn`.

---

## 2. The five wave-3 migrations, in apply order

All in #850, each in its own commit. Append-only, idempotent, clean under
`promotion.preflight.scan_destructive`, and inert until a flag or a person
turns the consumer on. The reverse SQL below is copied from each file's
header (the #850 PR body's table predates two review fixes: `renew_lease`, and
`materialize_tutor_session`'s fifth argument).

| # | File | Adds | Inert until | Reverse (from the file header, as the migration role) |
|---|---|---|---|---|
| X1 | `20261109022852_app_leases.sql` | `app_leases` (RLS on, no policies), `claim_lease`, `renew_lease`, `release_lease` (service_role only) | `stateless_locks` | Turn `stateless_locks` off first (the app falls back to its in-process locks). `DROP FUNCTION IF EXISTS public.release_lease(text, text); DROP FUNCTION IF EXISTS public.renew_lease(text, text, integer); DROP FUNCTION IF EXISTS public.claim_lease(text, text, integer); DROP TABLE IF EXISTS public.app_leases;` |
| X2 | `20261109023347_jobs_overview.sql` | `jobs_overview()` (one GROUP BY type, status) | `GET /api/admin/jobs` calls it on the next request after the deploy; it falls back to the capped scan when missing | `DROP FUNCTION IF EXISTS public.jobs_overview();` |
| X3 | `20261109023455_db_scope_divergences.sql` | `db_scope_divergences(from, to, kinds)` | `GET /api/admin/analytics/db-scope` calls it; falls back to the capped scan when missing | `DROP FUNCTION IF EXISTS public.db_scope_divergences(timestamptz, timestamptz, text[]);` |
| X4 | `20261109023732_study_guides_unique_key.sql` | `ensure_study_guides_unique_key()` only; **not called** | a person runs it after the deploy (§4) | `DROP INDEX IF EXISTS public.study_guides_user_offering_exam_key;` (only if it was created) `DROP FUNCTION IF EXISTS public.ensure_study_guides_unique_key();` |
| X5 | `20261109024225_tutor_pending_sessions.sql` | `tutor_pending_sessions` (🔒 `assistant_reply`), `stash_` / `materialize_` / `discard_tutor_session` | `stateless_tutor_sessions` | Turn `stateless_tutor_sessions` off first (pending sessions are then never materialised; their first turn answers 404). `DROP FUNCTION IF EXISTS public.discard_tutor_session(text, text, text, boolean, integer); DROP FUNCTION IF EXISTS public.materialize_tutor_session(text, text, integer, integer, timestamptz); DROP FUNCTION IF EXISTS public.stash_tutor_session(text, text, text, text, text, text, boolean, text, jsonb, integer, integer, integer); DROP TABLE IF EXISTS public.tutor_pending_sessions;` |

**Reverse order for wave 3:** X5, X4, X3, X2, X1. Then wave 2's (wave-2 doc
§3) if you are taking that out too.

**Old prod code against the new schema.** Between the migrate step and the new
deploy going live, prod still runs `6ed0f13c`. Wave 3 adds only new tables and
functions that old code never reads. Wave 1's caveat still holds: after #772
drops `courses.deleted_at`, `services/topic_checklist_service.py` 500s until
the new code is live (wave-2 doc §3).

---

## 3. Flags and the order to turn them on

Both new flags are declared in `services/feature_flags.py::REGISTRY`, global
(`user_id=None`; per-user rules and rollouts do not apply), server-only, and
default `off`. Each has a kill switch, already listed in
`.railway/railway.ts`'s `FLAG_KILL_SWITCHES` so the worker shares it.

| Flag | From | Moves out of process memory | Kill switch |
|---|---|---|---|
| `stateless_locks` | #850 | study-guide single-flight, admin account-operation slot, consumed OAuth nonces → `app_leases` | `SAPLING_FLAG_STATELESS_LOCKS=off` |
| `stateless_tutor_sessions` | #850 | pending tutor sessions + end/delete tombstones → `tutor_pending_sessions` | `SAPLING_FLAG_STATELESS_TUTOR_SESSIONS=off` (see the warning below) |

**The replica track, in this order** (`docs/deploy/railway.md` "Two API
replicas" has the full audit, verification and rollback). Turn each on with
**one** replica running and watch it for a day before the next:

1. **`stateless_rate_limit`** (wave 2): the rate-limit windows into
   `rate_limit_hits`. Watch for "falling back to the per-process limiter" and
   `SELECT count(*) FROM rate_limit_hits;` staying bounded.
2. **`stateless_locks`**: watch `SELECT count(*) FROM app_leases;` stay small
   (one row per consumed OAuth nonce; claims prune rows that expired over an
   hour ago) and the `stateless_locks: <fn>() failed …; using the in-process
   locks` warning stay absent.
3. **`stateless_tutor_sessions`**: watch tutor start-session and first turns
   (404s on a first turn would be the symptom) and
   `SELECT state, count(*) FROM tutor_pending_sessions GROUP BY 1;`.
   **Do not turn it off again once it is on.** That strands the sessions still
   pending in the table: their first turn answers 404 (starting a new session
   fixes it for that student). It also has no memory fallback: a database
   error fails that session request.
4. **`async_db_client`** (optional; wave 2's flag, per user). **Its blast
   radius grew with #850**: it now covers the tutor turn path, graph, quiz,
   learn and documents reads, not only `GET /api/quiz/attempts` as the wave-2
   doc §4 step 4 says. Ladder: admins, then 10/50/100%. Turn it on when the
   load test says so; it is independent of the replica count.
5. **Then `API_REPLICAS = 2`** (§5).

`stateless_locks` and `stateless_rate_limit` fail open on a database error (to
the per-process behaviour, warned once per outage), so a Postgres blip
degrades to "as if one replica".

The other wave-2 flags (`realtime_rls`, `llm_budget`, `llm_outage_drill` /
`llm_fallback`, `jobs_queue`, `db_user_scope`) keep the order and
preconditions in the wave-2 doc §4. The two tracks are independent; do not
flip two flags on the same day.

---

## 4. Post-deploy manual step: the `study_guides` unique key

Once per environment, **after** the deploy that carries #850's
`routes/study_guide.py` is live (code from before it would 500 on regenerate
once the index exists), as the migration role:

```sql
SELECT public.ensure_study_guides_unique_key();
```

It answers one of:

- `created`: the unique index `study_guides_user_offering_exam_key` was built.
- `exists`: it was already there (the function is idempotent).
- `skipped: N duplicate keys`: N `(user_id, offering_id, exam_id)` keys have
  more than one row; no index was built and no row changed. **Which copy to
  keep is a human decision** (reads already show the newest `generated_at`);
  never delete a student's row automatically. Find them with
  `SELECT user_id, offering_id, exam_id, count(*) FROM public.study_guides GROUP BY 1, 2, 3 HAVING count(*) > 1;`,
  resolve them, then call the function again.

Staging: `main` deploys staging on every merge, so once `/api/health` there
reports a SHA at or after `ec51657c` the step can run. Whether it has run is
not recorded anywhere; check with
`SELECT to_regclass('public.study_guides_user_offering_exam_key');` (NULL =
not yet).

---

## 5. Two API replicas and the nightly load test

**Replicas.** `.railway/railway.ts` declares the API service with
`replicas: API_REPLICAS`, committed as 1, and it does nothing until
`MANAGE_API` is on. Per `docs/deploy/railway.md` "Two API replicas", staging
first:

1. All of §3's flags on and watched for a day each.
2. If `MANAGE_API` is still off, turn it on first with `API_REPLICAS` still 1:
   paste the API's pulled variables into its `env` block, `railway config plan`
   (must show `replicas: 1` on the API and **no variable deletes**), apply.
3. Change `API_REPLICAS` to 2, plan (the only API change it may show is
   `replicas: 1 -> 2`), apply.
4. Verify (railway.md "Verification"): the load test at two replicas against
   staging, with the owner's say-so; `GET /api/health` p95 near idle while
   chat streams are open (the loop-lag probe); zero `db.sync_on_loop` warnings;
   a tutor session served across both replicas; an ended session refused on
   the other replica; a 429 that holds across replicas.

**Rollback:** `API_REPLICAS` back to 1, plan, apply (or set the replica count
in the service settings). Leave the flags on; scale down **before** turning
any of them off. Known per-replica leftover, documented as acceptable: the
Resend spacing (two replicas sending at once can exceed 2 req/s; a 429 is
retried once).

**Load test.** Set the repository **variable** (not a secret)
`LOADTEST_TARGET_URL` (Settings → Secrets and variables → Actions → Variables)
to a function-mode target you own, and agreed to load nightly. Unset, the
nightly job is skipped and sends nothing. Optional: `LOADTEST_USERS`,
`LOADTEST_SPAWN_RATE`, `LOADTEST_DURATION`, `LOADTEST_CHAT`,
`LOADTEST_USER_IDS`, and the secret `LOADTEST_SESSION_TOKEN`
(`.github/workflows/loadtest-nightly.yml` header). Do not point it at prod. In
real model mode the chat task spends LLM budget.

Phase 3's done-when ("2 replicas serve prod; nightly load test meets targets")
is met only when both of these are live on prod.

---

## 6. The combined prod promote (waves 1–4)

Prod (`git ls-remote origin production`) is `6ed0f13c`. `make promote` migrates
the prod DB, then merges `main` into `production`, pinned to the SHA it
audited.

- `git log --oneline --no-merges 6ed0f13c..origin/main`: 242 commits.
- `git diff --shortstat 6ed0f13c origin/main`: 799 files, +143,929/−25,434.
- `git diff --name-status 6ed0f13c origin/main -- backend/db/migrations`: **19
  added files**, nothing modified or deleted:

```
20261016064813_analytics_opt_out.sql                      #677   wave-1 doc §3 #1
20261106055333_state_machines_audit.sql                   #772   wave-1 doc §3 #2  (destructive)
20261108063442_xp_events_per_user_idempotency.sql         #805   wave-1 doc §3 #3
20261108082151_rls_on_every_table.sql                     #807   wave-1 doc §3 #4
20261108092633_rls_app_auth_helpers.sql                   #821   wave-1 doc §3 #5
20261108094129_rls_policies.sql                           #821   wave-1 doc §3 #6
20261108094130_rls_authenticated_grants.sql               #821   wave-1 doc §3 #7
20261108095241_jobs_queue.sql                             #821   wave-1 doc §3 #8
20261108210944_rls_room_messages_realtime.sql             #826   wave-2 doc §3 W1
20261108212226_document_uploads.sql                       #826   wave-2 doc §3 W2
20261108213311_llm_budgets_and_cost_signal.sql            #826   wave-2 doc §3 W3
20261108213623_jobs_upkeep.sql                            #826   wave-2 doc §3 W4
20261108214227_gradescope_syncs.sql                       #826   wave-2 doc §3 W5
20261108220438_stateless_rate_limit_and_flag_version.sql  #826   wave-2 doc §3 W6
20261109022852_app_leases.sql                             #850   §2 X1
20261109023347_jobs_overview.sql                          #850   §2 X2
20261109023455_db_scope_divergences.sql                   #850   §2 X3
20261109023732_study_guides_unique_key.sql                #850   §2 X4
20261109024225_tutor_pending_sessions.sql                 #850   §2 X5
```

Staging has all 19 (the last five from run 42569303747), so preflight's
staging-ran-it-first check can pass.

### Step 1. The pre-checks (wave-2 doc §6)

Run the wave-2 doc §6 checklist as written (reviews, staging smoke, the
read-only prod SQL, backup, checkout hygiene, `STAGING_SUPABASE_DB_URL`,
Railway prod variables), with these changes:

- **Staging smoke**, flags off, adds: a tutor session (start, first turn, end,
  resume) and the session list; the graph page; a quiz (generate, answer,
  abandon, submit, history); a document list/rename/delete; a study-guide
  regenerate; `GET /api/admin/jobs` (has `outstanding_oldest`) and
  `GET /api/admin/analytics/db-scope` answer 200. Railway staging logs: **zero**
  `db.sync_on_loop` warnings now (the wave-2 doc expected some; the allowlist
  is empty).
- **Read-only prod SQL**: append these lines inside the same
  `BEGIN READ ONLY; … ROLLBACK;` block of the wave-2 doc §6 step 4:
  ```sql
  -- ── wave 3 ──
  -- none of wave 3's tables may exist yet (expect 0 rows)
  SELECT tablename FROM pg_tables WHERE schemaname = 'public'
    AND tablename IN ('app_leases','tutor_pending_sessions');
  -- what ensure_study_guides_unique_key() will meet after the deploy (expect 0;
  -- non-zero means it will answer 'skipped' and you need §4's decision)
  SELECT count(*) AS study_guide_dup_keys FROM (
    SELECT 1 FROM study_guides GROUP BY user_id, offering_id, exam_id HAVING count(*) > 1) d;
  ```
  The ledger count it prints is the baseline: **expect +19** after the
  promote, not +14.
- **Checkout hygiene**: the primary checkout still has the uncommitted
  `backend/promotion/runner.py` edit. Commit or stash it before `git pull`.

### Step 2. The promote

```bash
make promote ARGS="--allow-destructive"
```

`--allow-destructive` is still for #772's `DROP COLUMN users.current_room_id`
and `DROP COLUMN courses.deleted_at`; waves 2–4 add no finding. The migrate
stage runs **19 files**. The topic-checklist 500 window (§2) is the known
cost.

### Step 3. Verification (wave-2 doc §7)

Run the wave-2 doc §7 steps 1–5 (RLS and anon checks, Security Advisor,
canary, `/api/health` SHA, wave-2 objects, endpoints, smoke), with the ledger
at the pre-check count **+19**, plus:

```sql
-- wave 3's objects (expect 2 non-NULL, then 9 rows)
SELECT to_regclass('public.app_leases'), to_regclass('public.tutor_pending_sessions');
SELECT proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = 'public' AND proname IN (
   'claim_lease','renew_lease','release_lease','jobs_overview','db_scope_divergences',
   'ensure_study_guides_unique_key','stash_tutor_session','materialize_tutor_session',
   'discard_tutor_session');
```

And as an admin: `GET /api/admin/jobs` carries `outstanding_oldest`;
`GET /api/admin/analytics/db-scope` and `GET /api/admin/llm/budgets` (the 2M
default, `builtin` only if the row is missing) answer 200. Spot-check by hand:
Google sign-in, tutor chat, a quiz end to end, an upload, flashcards, a study
guide, the graph, a profile.

### Step 4. The study-guide key on prod

`SELECT public.ensure_study_guides_unique_key();` as in §4, once the new
deploy is live and smoke is green.

### Step 5. The post-promote data repairs (dry-run first)

From `backend/`, each one dry-run, read the output and the project host it
prints, then run for real. Staging first if it has not run there.

- `scripts/backfill_achievement_xp.py` (#805, wave 1).
- `scripts/cleanup_cross_user_note_concepts.py` (#830, wave 2):
  `dotenv -f .env.production run -- python scripts/cleanup_cross_user_note_concepts.py`,
  then add `--apply`.

### Then: the flag rollout, per environment, staging first

Leave every flag off for at least a day of prod traffic. Then, one flag at a
time, **staging before prod** each time:

- **The replica track** (§3): `stateless_rate_limit` → `stateless_locks` →
  `stateless_tutor_sessions` → (optional) `async_db_client`, then §5's
  `API_REPLICAS = 2`. Prod gets each step only after staging has run it for a
  day.
- **The wave-2 track** (wave-2 doc §4): `realtime_rls` (needs the step 2d key),
  `llm_budget`, the staging-only `llm_outage_drill` then `llm_fallback`,
  `jobs_queue` (needs the worker service), `db_user_scope` (its own runbook).

---

## 7. Rollback

The wave-2 doc §8 applies (flags first, then code, then migrations), with:

- **Flags.** `SAPLING_FLAG_STATELESS_LOCKS=off` is always safe (back to
  per-process locks; scale to one replica first). For
  `stateless_tutor_sessions`, prefer a code fix: turning it off strands pending
  sessions (first turn 404s). If you must, scale to one replica first and
  accept that students re-start those sessions.
- **Code.** Reverting #851 has no data or schema effect. Reverting #850 is
  safe with its flags off: the migrations stay and nothing reads them.
- **Migrations.** X5 → X1 (§2), each after its flag is off.

---

## 8. New env vars

None for the API at runtime beyond the two kill switches
`SAPLING_FLAG_STATELESS_LOCKS` and `SAPLING_FLAG_STATELESS_TUTOR_SESSIONS`
(already in `.railway/railway.ts`). #847's slot can be overridden with
`SAPLING_MODEL_CONCEPT_EDGES` like any slot; it runs only from the backfill
script. Repository variables for the load test: §5.

---

## 9. What's left

### Human steps (from the wave-2 doc §9, still open)

- [ ] **RLS step 2d: our ES256 signing key** (staging first, a separate key for
      prod), then `SUPABASE_JWT_SIGNING_KEY` and `SUPABASE_ANON_KEY` on the API
      **and** worker services. Required before `realtime_rls` or
      `db_user_scope` leaves `off`.
- [ ] **Railway worker service** (`docs/deploy/railway.md` steps 1–5). Required
      before `jobs_queue`.
- [ ] **API image cut-over**, later: OCR callers and Gradescope BU SSO off the
      request path first (wave-2 doc §9).
- [ ] **Supabase Auth:** "Allow new users to sign up" off on staging and prod;
      delete the stray prod Auth user.
- [ ] **Backups/PITR:** decide on a paid plan; until then the `make promote`
      dump is the only way back.
- [ ] **`school_match`:** confirm the same-school-only rule (#813).
- [ ] **Queued uploads over 20 MB / Supabase Storage:** decide before
      `jobs_queue` reaches 100%.
- [ ] **`cleanup_cross_user_note_concepts.py`** per environment (§6 step 5).
- [ ] **One manual Google sign-in** on staging and on prod after the promote.
- [ ] New in wave 3: **`ensure_study_guides_unique_key()`** per environment
      (§4); the **replica flags and `API_REPLICAS = 2`** (§3, §5); the
      **`LOADTEST_TARGET_URL`** variable (§5).
- [ ] Merge, approve and promote (blocked for the agent in auto mode).

### Teammate PRs whose code moved (#851)

Rebase onto `main` after #851, then re-apply each hunk to the same-named
function in its new module (move tables in §1b and
`docs/design/domain-modules.md` "As built (wave 3)"). For quiz, rebase onto
`dc85af01` first: it is a pure `git mv` of the flat `quiz_*` modules, so git
carries edits across the rename. The ratchet baseline is empty, so each PR
must keep every route file ≤ 600 lines and every function ≤ complexity 25.

| PR(s) | Moved |
|---|---|
| #750, #846 | quiz → `services/quiz/` |
| #751 | learn → `services/tutor/` |
| #752 | quiz, learn, documents, graph_service, auth, social, admin, profile, gradescope, flashcards |
| #717, #755 | documents → `services/documents/` |
| #673, #735, #801 | quiz, learn, documents, profile, flashcards, `achievement_service._get_user_stat` (now `_STAT_READERS`), `apply_graph_update` (now typed + phase helpers) |
| #799, #842 | admin_analytics → `services/admin/analytics/`; #842 also touches documents and graph_service |

### Code follow-ups (each a small PR; none blocks the promote)

- **Shims:** once the teammate PRs land, remove the route re-exports
  (`# noqa: F401  (re-export, #118)`) and the `sys.modules` aliases at the old
  flat paths (pinned in `tests/test_domain_shims.py`).
- **import-linter:** drop the `services.document_jobs -> routes.documents`
  exception; `document_jobs` still imports fastapi (`records_inline_outcome`
  catches `HTTPException`).
- **Complexity:** lower `[lint.mccabe] max-complexity` in steps (20, then 15),
  re-baselining each time.
- **Domain errors:** one `DomainError(status, detail)` with a single exception
  handler in `main.py`, replacing the per-route mapping
  (`routes/_errors.py::domain_status`, context managers, try/except). Decide
  whether an unmapped domain error re-raises to the generic 500 handler (which
  reaches PostHog `capture_exception`); today it answers
  `HTTPException(500, detail)` plus an ERROR log.
- **Silent excepts:** `graph_service.add_course`, `delete_node` and
  `delete_course` still `except: pass` around the context refresh; log them as
  `apply_graph_update` now does.
- **Agent read tools:** swap `asyncio.to_thread` for the `a*` twins in
  `agents/tools/*` (about 46 patch changes; those reads are already off the
  loop).
- **Async design doc §8, not built:** DB spans, saturation gauges (threadpool
  tokens, loop lag), a `PoolTimeout` → 503 handler, one shared request builder
  for the sync and async verbs.
- **Resend throttle** is per replica; revisit if email volume grows.

---

## 10. What ran

- **Hermetic suite:** 5,676 passed / 368 skipped on #850's top; 5,756 passed /
  370 skipped on #851's top; 5,823 passed, 0 failed after #851's merge of
  `main` (`d09af0d0`, which ported #847's `apply_graph_update(..., defer=)` into
  the split code). `ruff` and `lint-imports` clean (2 contracts kept, 0
  broken); code-size ratchet green with an empty baseline.
- **Migrations:** all five applied on a throwaway PG 15.8 container (93
  migrations then); lease semantics, grants and RLS, both aggregates, the
  pending-session TTL and cap, service_role-only execution checked there. CI's
  integration lane runs `test_app_leases_db`, `test_admin_aggregates_db`,
  `test_study_guides_unique_key_db` and `test_tutor_pending_sessions_db`.
- **Review:** `/code-review` (high) on each PR; 10 findings on #850 and 8 on
  #851, all fixed (handoff #26).
- **Local E2E** on `ddce3be6` (#851's top before the final merge of `main`):

  | Run | Integration | Playwright | Oracles |
  |---|---|---|---|
  | Flags off | 359 / 0 | 105 / 0 (14 skipped) | 0 findings |
  | `async_db_client` + `stateless_rate_limit` + `jobs_queue` on, with a worker | 359 / 0 | 105 / 0 | 0 findings |

  `stateless_locks` and `stateless_tutor_sessions` were not on in either run;
  they are covered by their unit and integration tests.
- **CI on `main` after the merges:** CI green on `38db6a75` (#852). The
  integration run on `38db6a75` failed at `supabase/setup-cli` with HTTP 504s
  before any test ran (infra; run 42569920775); the runs on `6dd92410` (#853)
  were still in progress when this was written.
