# Railway: images, services and the worker

As of 2026-11-08 (Trov #114 phase 0 "Railway config in repo", #116 phase 2
"API image has no torch/Chromium"). Nothing here has been applied to Railway.
Every step below is for Andres to run, staging first.

## What is in the repo

| File | What it is |
| --- | --- |
| `backend/Dockerfile` | One file, five stages: `target-check`, `api`, `heavy`, `worker`, `full`. The last stage picks one from the `SAPLING_IMAGE_TARGET` build argument (unset or empty = `full`; anything but `api`/`worker`/`full` fails the build in `target-check`). |
| `backend/requirements.txt` | The API's dependencies. `requirements.lock` is exactly this file compiled (the lock did not change in the split). |
| `backend/requirements-worker.txt` | The worker-only extras: Docling, transformers, torch. Never in the lock (CPU torch index, see the Dockerfile). |
| `.railway/railway.ts` | Railway Infrastructure as Code: the `worker` service, and the API service behind `MANAGE_API`. Unverified against the live project. |

### The images

| Target | Contents | Command | Size driver |
| --- | --- | --- | --- |
| `api` | `requirements.txt` under the lock. No tesseract, no torch, no Docling, no Chromium. | `uvicorn main:app --port 5000` | small |
| `worker` | `api`'s packages + `requirements-worker.txt` (CPU torch) + tesseract + Chromium | `python -m worker` | torch, Chromium |
| `full` | the same as `worker` | `uvicorn main:app --port 5000` | torch, Chromium |

`full` is the image Railway builds today (same apt packages, same torch step,
same lock constraints, same Chromium) plus one line, `/etc/sapling-image-target`,
naming the target it was built as; it is still what a plain
`docker build backend` produces. Nothing changes on Railway until a service
sets `SAPLING_IMAGE_TARGET`.

Choosing one:

- Railway: set the service variable `SAPLING_IMAGE_TARGET` to `api`, `worker`
  or `full`. Railway hands a service variable to the Docker build when the
  Dockerfile declares an `ARG` of that name, and the Dockerfile's last stage is
  `FROM ${SAPLING_IMAGE_TARGET:-full}`. Unset OR EMPTY means `full` (a plain
  `${SAPLING_IMAGE_TARGET}` with an empty value left the build with no `FROM`
  at all). Any other value fails the build: the first stage, `target-check`,
  exits 1 with "SAPLING_IMAGE_TARGET='<value>' is not a backend image target:
  use api, worker or full". (Under BuildKit, which resolves stages in parallel,
  the failure may instead surface as a pull error for the unknown `FROM` name;
  either way nothing is built.) Railway has no build-target setting; this is
  how the target gets chosen. Changing it needs a redeploy, not just a
  restart: it is a build input.
- Locally / CI: `docker build --target api backend` (or
  `--build-arg SAPLING_IMAGE_TARGET=api`). Podman/buildah accepts the same.

`tests/test_docker_lock_install.py` pins the stage layout (default `full`, the
`api` stage installs nothing outside the lock and no torch, Chromium or
tesseract). `tests/test_api_image_imports.py` imports `main` and runs the
FastAPI startup in a fresh interpreter with every package outside the lock
(plus `playwright`) blocked, and checks `/api/health` answers: the API image's
dependency set, proven in the hermetic suite on every PR.

## Why `.railway/railway.ts` and not `railway.toml`

Railway's config-as-code files (`railway.toml` / `railway.json`) are
deprecated: per docs.railway.com/reference/config-as-code (read 2026-11-08)
they stop being read on **2026-12-01**, and a service cannot be managed by both
systems. The replacement is Infrastructure as Code: one TypeScript program in
`.railway/` (`railway.ts`, generally available; Python and Go are beta), run
by the Railway CLI with `railway config plan` / `railway config apply`.

It is a **partial** (`export const partial = "sapling-backend"`). An apply
from a partial only creates, changes or deletes resources that the partial owns,
and the first apply claims every resource the file declares. As committed the
file declares only the new `worker` service, so the first apply can create the
worker and nothing else. The API service is described under `MANAGE_API`
(off), because the moment this partial owns it, any of its variables missing
from the file would be deleted on apply.

What I could not verify offline (check in the plan output):

- the exact project, service and environment names (constants at the top of
  the file: `PROJECT`, `API_SERVICE`, `BRANCH_FOR`);
- that `github(..., { rootDirectory: "backend" })` matches the API service's
  current root directory;
- that `domains: []` leaves the worker with no public networking;
- that a reference value such as `${{backend.SUPABASE_URL}}` is accepted as a
  literal `env` value (it is Railway's reference-variable syntax in the UI). The
  IaC reference (docs.railway.com/infrastructure-as-code/reference, read
  2026-11-08) documents literal strings and the object form
  `<service>.env.<VAR>` for references, and does not mention a raw `${{...}}`
  string either way; if the plan shows the literal text instead of a
  reference, switch `ref()` to the object form;
- what a reference to a variable the API service does not set resolves to: the
  variables docs do not say (empty string, literal text or a failed deploy).
  Hence `NOT_ON_API` (step 3): never leave a reference dangling.

## Runbook

### 1. Prerequisites

- The jobs migrations are applied in the target environment:
  `20261108095241_jobs_queue.sql` and `20261108213623_jobs_upkeep.sql`
  (the upkeep one adds `heartbeat_job`, `prune_jobs` and the two Canopy keys).
  A worker built from this branch calls `heartbeat_job`; against a database
  without it every heartbeat logs a warning and the job is unaffected.
- A recent Railway CLI with the `railway config` commands, logged in, and the
  repo linked to the project (`railway link`), staging environment selected.

### 2. Read what Railway has now

```sh
railway config pull          # imports the live config; does not change Railway
```

Compare the pulled API service with `.railway/railway.ts`: its name, root
directory, branch per environment, start command, healthcheck. Fix the
constants at the top of `.railway/railway.ts` where they differ. Do NOT commit
the pulled file's variable values (it writes them as `preserve()`, which is
safe, but keep the diff reviewable).

Check the API service's **start command** in the Railway UI. If it is set, it
overrides the Dockerfile `CMD`; keep it as it is (the image's CMD is
`uvicorn main:app --host 0.0.0.0 --port 5000`).

### 3. Plan, staging

First list what the API service actually sets, and put every name from the
worker's lists (`BOOT_VARIABLES`, `HANDLER_VARIABLES`, `FLAG_KILL_SWITCHES`,
`MODEL_SLOT_VARIABLES`) that is NOT in it into `NOT_ON_API` in
`.railway/railway.ts`, so the worker never holds a reference to a variable that
does not exist:

```sh
railway variables --service backend --kv | cut -d= -f1 | sort   # the API's names
```

Most of the optional names (model-slot overrides, kill switches, OCR tuning)
will be unset; that is normal and they then take their code defaults, in the
worker as in the API. `NOT_ON_API` may differ per environment: plan and apply
staging and production separately, each with its own list.

```sh
railway config plan
```

The plan must show exactly: create service `worker` with its source, start
command and replicas, `SAPLING_IMAGE_TARGET=worker`, and one reference per
name in `SHARED_VARIABLES` (the four lists above minus `NOT_ON_API`; 54 names
before that filter, `backend/tests/test_railway_worker_env.py` pins what they
must cover). Anything else, and above all any **delete**, means a constant is
wrong: stop and fix the file. Never pass `--confirm-destructive`.

### 4. Apply, staging

```sh
railway config apply
```

Then in the worker's Variables tab confirm the references resolved (no empty
values for the boot-required block). The first deploy builds
`SAPLING_IMAGE_TARGET=worker`. It is healthy when its log shows
`worker.boot model_mode=...` then `worker.started id=... types=...`. A
`worker.boot_failed` exit 2 names the missing variable.

### 5. Turn the queue on, staging

Follow `docs/releases/2026-11-architecture-hardening.md` (the `jobs_queue`
rollout: 10% of students, then 100%). Watch it with the admin endpoint
`GET /api/admin/jobs` (queue depth by type and status, newest dead letters),
or in SQL `SELECT status, count(*) FROM jobs GROUP BY 1`. Canopy gets
`totals.jobs_queue_depth` and `counts.jobs_dead_lettered` on its next poll.
Measure chat latency under an upload locally first:
`python backend/scripts/latency_check.py --pdf <50-page.pdf> --flag both`
(local stack only; it refuses any other host).

Then repeat steps 2 to 5 in production.

### 6. Cut-over: the API onto the `api` image (later)

The `api` image has no OCR stack and no Chromium. Moving the API service onto
it is safe only when NOTHING on the API's request path needs either, which
today is not the case:

1. **OCR.** With `jobs_queue` off, the upload pipeline extracts text inline
   (`routes/documents.py`), and so do `routes/extract.py`,
   `services/flashcards/importing.py` and `services/calendar_service.py`
   (syllabus import). Without Docling those fall back to pypdf text (fine for
   born-digital PDFs) and then to tesseract, which the `api` image does not
   have either: a scanned PDF or an image would extract nothing. So: the
   upload pipeline must run in the worker (the `document.process` /
   `document.index` job types, W6a) with `jobs_queue` ON for 100% of students,
   and the other three callers must either move to jobs too or accept
   text-layer-only extraction.
2. **Chromium.** Gradescope's BU SSO (`POST /api/gradescope/...` →
   `gradescope_service.login_via_bu_sso`) launches Chromium on the request
   path. On the `api` image the launch fails and the route answers 500 "BU
   sign-in is unavailable. Please retry or connect using session cookies."
   (the other Gradescope sign-in modes keep working). It has to become a
   worker job first (follow-up; the Duo push makes it interactive, so it needs
   a poll endpoint).

When both are done:

- set `MANAGE_API = true` after pasting the API's pulled variables into its
  `env` block, plan (must show no variable deletes), apply; or simply set the
  variable in the UI;
- set `SAPLING_IMAGE_TARGET=api` on the API service and redeploy;
- verify `GET /api/health` and `make promote ARGS="--verify-only"`.

Rollback at any point: delete the API service's `SAPLING_IMAGE_TARGET` (or
set it to `full`) and redeploy. That rebuilds today's image.

## Two API replicas

`.railway/railway.ts` declares the API service with `replicas: API_REPLICAS`
(2). That line does nothing until `MANAGE_API` is on (runbook step 6), and it
must not take effect before the flags below are on: until then several guards
live in process memory, and a second replica would see only its own half.
Nothing in this section has been applied; it is the order to do it in,
staging first.

### Prerequisites: the flags, in this order

All four are global flags (`services/feature_flags.py` REGISTRY; per-user
rules and rollouts do not apply), edited in `/api/admin/flags`; each has a
`SAPLING_FLAG_<KEY>` kill switch the worker shares. Turn each on with ONE
replica running, watch it for a day, then the next.

| # | Flag | Migration it needs | What it moves out of process memory |
| --- | --- | --- | --- |
| 1 | `stateless_rate_limit` | `20261108220438_stateless_rate_limit_and_flag_version.sql` | the per-key rate-limit windows (`services/request_limits.py`) into `rate_limit_hits` + `claim_rate_limit()`, so two replicas share one budget instead of each granting the full one |
| 2 | `stateless_locks` | `20261109022852_app_leases.sql` | the study-guide single-flight, the admin account-operation slot and the consumed OAuth nonces become `app_leases` rows (`services/pg_lease.py`), so they exclude across replicas |
| 3 | `stateless_tutor_sessions` | `20261109024225_tutor_pending_sessions.sql` | pending tutor sessions (between start-session and the first turn) and their end/delete tombstones into `tutor_pending_sessions`, so a session started on one replica can be continued, ended or deleted on the other |
| 4 | `async_db_client` (optional) | none | not replica state: the async handlers' PostgREST calls on a native async client instead of a threadpool hop. Independent of the replica count; turn it on when the load test says so |

The first two fail open on a database error (to the old per-process
behaviour, with one warning per outage), so a Postgres blip degrades to "as
if one replica", never to an outage. `stateless_tutor_sessions` has no memory
fallback once on: a database error fails that session request, as any other
tutor-session write already does. The flag store itself is
already replica-safe: every process re-checks `feature_flags_version`
(`FEATURE_FLAGS_VERSION_CHECK_S`) and drops its snapshot when another process
changed a flag.

Then set `MANAGE_API = true` (step 6's variable paste first), plan (it must
show `replicas: 2` on the API and no variable deletes) and apply.

### The audit: per-process state on the API

Every module-level dict/set/lock/cache under `backend/` that outlives a
request (swept 2026-11-09):

| State | Where | On two replicas |
| --- | --- | --- |
| rate-limit windows | `services/request_limits.py` `_rate_state` | **made safe**: `stateless_rate_limit` (flag 1) |
| study-guide single-flight | `routes/study_guide.py` key locks | **made safe**: `stateless_locks` (flag 2), a lease per guide key |
| admin account-operation slot | `services/account_ops_lock.py` `_running` | **made safe**: `stateless_locks` (flag 2) |
| consumed OAuth nonces | `routes/auth.py` `_CONSUMED_OAUTH_NONCES` | **made safe**: `stateless_locks` (flag 2), a never-released lease on the nonce's hash |
| pending tutor sessions + tombstones | `services/tutor_sessions.py` `PENDING_SESSIONS`, `_DISCARDED`, `_MATERIALIZATION_LOCKS` | **made safe**: `stateless_tutor_sessions` (flag 3); first-turn materialisation is one SQL transaction |
| flag snapshot | `services/feature_flags.py` | **safe**: version check (`feature_flags_version`) |
| encryption key canary first seed | `services/encryption_canary.py` | **safe**: two boots at once both insert with DO NOTHING, both re-read the one stored canary; same key passes, a different key refuses to boot (`tests/test_encryption_canary.py` runs the race) |
| queued uploads / Gradescope syncs | `services/document_jobs.py`, `services/gradescope_jobs.py` (`services/staged_jobs.py`) | **safe**: rows in Postgres, every write a CAS on stage + owner token; a watcher on either replica sees the same row |
| index sweeper | `services/index_sweeper.py` (one per replica) | **safe**: rows are claimed by `claim_documents_for_indexing` with a per-row lease, so two sweepers split the work |
| account-state cache | `services/auth_guard.py` (30 s TTL) | acceptable: a removed/deleted account is refused on the other replica within 30 s |
| roles cache | `services/feature_flags.py` `_roles` (60 s TTL) | acceptable: a role change reaches both within 60 s |
| course context | `services/course_context_service.py` (60 s TTL) | acceptable: cleared locally by the mutator, converges elsewhere within the TTL |
| analytics consent | `services/analytics_consent.py` (TTL) | acceptable: an opt-out reaches the other replica within the TTL |
| LLM budget status | `services/llm_budget.py` `_cache` (30 s TTL) | acceptable: the spend itself is in `llm_usage`; each replica may let a little past the line inside the TTL |
| email notification opt-outs | `services/email_service.py` `_opt_out_cache` (60 s) | acceptable: the send dedupe (`email_sends`) and suppressions are in Postgres |
| Resend request spacing | `services/email_service.py` `_next_slot` | per replica: two replicas sending at once can exceed Resend's 2 req/s; a 429 is retried once after its Retry-After. Broadcasts are admin-initiated and run on one replica |
| immutable lookups | `services/academics.py` (`offering_course_id`, `term_for_offering`), `services/growth.py` (`growth_stages`) | harmless: reference data that does not change at runtime |
| in-flight background tasks | `routes/documents.py` `_POST_ROLL_TASKS`, `services/tutor_router.py` `_inflight` | harmless: per-process work, drained at shutdown; a lost post-roll index is re-driven by the sweeper |
| event / PostHog queues | `services/events_service.py`, `services/posthog_client.py` | harmless: per-process buffers drained by their worker thread and at shutdown |
| circuit breakers, outage drill log | `agents/_resilience.py` | harmless: each replica learns a provider outage on its own |
| HTTP clients, minted user JWTs, Redis client, OCR models | `db/async_connection.py`, `services/typesafe_client.py`, `db/user_jwt.py`, `services/cache.py`, extraction backends | harmless: connection/compute caches, no shared truth |
| db_user_scope tally | `db/scope_report.py` | harmless: the admin report reads the `events` table (`db_scope_divergences()`); the in-memory tally is this process's view only |
| log-dedupe sets | `services/decisions.py`, `services/llm_pricing.py`, `db/scope.py`, `agents/_providers.py` | harmless |
| OAuth fallback state store | `routes/auth.py` `_OAUTH_FALLBACK_STORE` | unused when `SESSION_SECRET` is set (the state is a signed cookie, valid on any replica with the same secret); outside local dev `validate_config` refuses to boot without one |

### Verification (staging, after the flags and before production)

1. **Load test** at two replicas against staging with the owner's say-so
   (`loadtest/README.md`; `.github/workflows/loadtest.yml` or the nightly
   job): p95 of the non-LLM routes under 300 ms and chat TTFT p95 under 3 s,
   the thresholds `loadtest/check_thresholds.py` enforces. Compare with the
   one-replica baseline at the same concurrency and flag values.
2. **Event-loop lag**: during that run, `GET /api/health` (no DB, no auth)
   is the loop-lag probe: its p95 should stay near its idle value while chat
   streams are open. A climbing health p95 means something blocks the loop.
   Also expect zero `db.sync_on_loop` warnings in the API logs (a sync
   PostgREST call on the event loop; the static ratchet's allowlist is empty).
3. **Cross-replica behaviour**: start a tutor session and send the first turn
   until both replicas have served one (Railway logs name the replica); end a
   session on one and confirm a turn on the other is refused (409/404) rather
   than carried on; hit a rate limit and confirm the 429 holds across
   replicas.

### Rollback

Set `API_REPLICAS` back to 1 in `.railway/railway.ts`, plan, apply (or set
the replica count in the service's settings). Leave the flags on: they are
correct on one replica too. Turning a flag off while two replicas run brings
back the split state it was guarding, so scale down first.

## Worker variables

The worker runs the same code as the API (its boot checks, the job handlers
`document.process`, `document.index`, `course_context.refresh`, `jobs.prune`,
`gradescope.sync` once it lands, and the agents they call), so a variable set
only on the API is silently missing in the worker. `.railway/railway.ts`
therefore references, from the API service, every variable those code paths
read. The list was derived by grepping `os.getenv` / `os.environ` reads in
those modules, and `backend/tests/test_railway_worker_env.py` re-derives it on
every PR: a new env read on a worker path fails CI until it is shared or
excluded with a reason.

| List | What | Why the worker needs it |
| --- | --- | --- |
| `BOOT_VARIABLES` | `APP_ENV`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ENCRYPTION_KEY`, `SESSION_SECRET`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `SAPLING_MODEL_MODE`, `SUPABASE_JWT_SIGNING_KEY`, `SUPABASE_ANON_KEY` | `worker/__main__.py::boot`: `validate_config()` and the key canary (a missing one exits 2), the model-mode freeze, the boot-time `db_user_scope` key warning |
| `HANDLER_VARIABLES` | `OCR_ENGINE`, `GEMINI_VISION_OCR_*`, `GOT_OCR_*`, `REDIS_URL`, `INDEX_MAX_ATTEMPTS`, `INDEX_LEASE_SECONDS`, `DBOS_*`, `EVENTS_LOGGING_ENABLED`, `EVENTS_QUEUE_MAX`, the `POSTHOG_*` set, the `FEATURE_FLAGS_*_S` TTLs, `LOGFIRE_TOKEN` | extraction/OCR, the shared OCR cache, indexing, events + LLM usage, PostHog mirror and erasure, flag caching |
| `FLAG_KILL_SWITCHES` | `SAPLING_FLAG_<KEY>` for every non-nav flag | a switch thrown on the API must hold in the worker too |
| `MODEL_SLOT_VARIABLES` | `SAPLING_MODEL_<TASK>` + `SAPLING_MODEL_FALLBACK_<TASK>` for classifier, summary, concepts, syllabus, ocr_vision, course_summary | a slot rolled back on the API must not keep running the default in the worker |

Not shared, on purpose: HTTP-only settings (`PORT`, `FRONTEND_URL`,
`SECURE_COOKIES`, Google OAuth, `ALLOWED_EMAIL_DOMAINS`), email (`RESEND_API_KEY`,
`EMAIL_*`: no job sends mail), `CANOPY_METRICS_TOKEN`, `ACCOUNT_SYNC_*`,
`OCR_ASYNC_ENABLED` and `UPLOAD_JOB_PICKUP_GRACE_SECONDS` (the API's side of an
upload), `DB_USER_SCOPE_SHADOW_SAMPLE_RATE` (per request; the worker runs as
service role), `SAPLING_FUNCTION_HANDLERS` (E2E only) and the commit SHA
(Railway sets `RAILWAY_GIT_COMMIT_SHA` on every service). The reasons are in
the test's `EXCLUDED`.

Worker-only tuning (all optional; the CLI flags override them):

| Variable | Default | Meaning |
| --- | --- | --- |
| `JOBS_POLL_INTERVAL_SECONDS` | 5 | sleep when the queue is empty |
| `JOBS_BATCH` | 10 | most jobs per pass |
| `JOBS_LEASE_SECONDS` | 300 | a claim's lease. At least 300 (`MIN_LEASE_SECONDS`): a lower value is refused at boot (exit 2). See "The lease rule" below. |
| `JOBS_MAX_HEARTBEAT_SECONDS` | 3600 | stop heartbeating after this, so a hung handler's job is re-offered |
| `JOBS_PRUNE_AFTER_DAYS` | 14 | delete `succeeded` jobs older than this, from an hourly `jobs.prune` job (0 = never). Only `succeeded` rows are ever deleted: queued, failed, running and dead rows are untouchable. |
| `JOBS_LOG_FORMAT` | text | `json` for structured logs |

`JOBS_PRUNE_AFTER_DAYS` is an operational knob, not a feature flag, on
purpose: deleting finished job rows past their retention is queue upkeep, no
student sees it, and the SQL cannot reach unfinished work or dead letters.
Every worker that claims `jobs.prune` asks for a run once an hour, but a run
is only enqueued when no `jobs.prune` row is queued, failed or running and
none succeeded in the last hour (plus an hour-bucketed dedupe key for two
replicas racing), so N replicas give about one prune run per hour, not N.

### The lease rule

`claim_jobs` re-offers a running job once `locked_at` plus the CLAIMING
worker's lease has passed, not the lease of the worker running it. A heartbeat
therefore only protects a job from claimers whose lease is longer than the gap
between beats. So every worker:

1. refuses a lease under `MIN_LEASE_SECONDS` (300 s, `services/jobs.py`):
   `JOBS_LEASE_SECONDS` / `--lease-seconds` below it exits 2 at boot;
2. heartbeats every `MIN_LEASE_SECONDS / 3` (100 s) whatever its own lease.

Then a live job's `locked_at` is never more than 100 s old, and no worker in
the fleet, whatever lease it runs with, can re-claim it even if two beats are
lost. A longer lease only delays how soon THAT worker's claims pick up a job
whose heartbeat stopped (a crash, or a hung handler past
`JOBS_MAX_HEARTBEAT_SECONDS`). Changing `MIN_LEASE_SECONDS` itself needs every
worker on the new image (stop the old ones first).
