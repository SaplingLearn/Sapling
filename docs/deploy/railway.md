# Railway: images, services and the worker

As of 2026-11-08 (Trov #114 phase 0 "Railway config in repo", #116 phase 2
"API image has no torch/Chromium"). Nothing here has been applied to Railway.
Every step below is for Andres to run, staging first.

## What is in the repo

| File | What it is |
| --- | --- |
| `backend/Dockerfile` | One file, four stages: `api`, `heavy`, `worker`, `full`. The last line picks one from the `SAPLING_IMAGE_TARGET` build argument (default `full`). |
| `backend/requirements.txt` | The API's dependencies. `requirements.lock` is exactly this file compiled (the lock did not change in the split). |
| `backend/requirements-worker.txt` | The worker-only extras: Docling, transformers, torch. Never in the lock (CPU torch index, see the Dockerfile). |
| `.railway/railway.ts` | Railway Infrastructure as Code: the `worker` service, and the API service behind `MANAGE_API`. Unverified against the live project. |

### The images

| Target | Contents | Command | Size driver |
| --- | --- | --- | --- |
| `api` | `requirements.txt` under the lock. No tesseract, no torch, no Docling, no Chromium. | `uvicorn main:app --port 5000` | small |
| `worker` | `api`'s packages + `requirements-worker.txt` (CPU torch) + tesseract + Chromium | `python -m worker` | torch, Chromium |
| `full` | the same as `worker` | `uvicorn main:app --port 5000` | torch, Chromium |

`full` is byte-for-byte the image Railway builds today (same apt packages,
same torch step, same lock constraints, same Chromium), and it is still what a
plain `docker build backend` produces. Nothing changes on Railway until a
service sets `SAPLING_IMAGE_TARGET`.

Choosing one:

- Railway: set the service variable `SAPLING_IMAGE_TARGET` to `api`, `worker`
  or `full`. Railway hands a service variable to the Docker build when the
  Dockerfile declares an `ARG` of that name, and the Dockerfile's last stage is
  `FROM ${SAPLING_IMAGE_TARGET}`. Unset means `full`. (Railway has no
  build-target setting; this is how the target gets chosen.) Changing it needs
  a redeploy, not just a restart: it is a build input.
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
  literal `env` value (it is Railway's reference-variable syntax in the UI).

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

```sh
railway config plan
```

The plan must show exactly: create service `worker` (source, start command,
replicas, the variables listed in `SHARED_VARIABLES` as references). Anything
else, and above all any **delete**, means a constant is wrong: stop and fix the
file. Never pass `--confirm-destructive`.

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
   `services/flashcard_import_service.py` and `services/calendar_service.py`
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

## Worker variables

The worker runs the same code as the API and boots through the same checks
(`worker/__main__.py::boot`: model-mode freeze, `validate_config()`, the
encryption-key canary), so it needs at least `APP_ENV`, `SUPABASE_URL`,
`SUPABASE_SERVICE_KEY`, `ENCRYPTION_KEY`, `SESSION_SECRET`,
`ANTHROPIC_API_KEY`, `GEMINI_API_KEY` (the `SHARED_VARIABLES` block). Add to
that list every variable the API service has set that a job handler can read:
`SAPLING_MODEL_MODE`, `LOGFIRE_TOKEN`, the `POSTHOG_*` set, `REDIS_URL`,
`OCR_ENGINE`, `GOT_OCR_*`, `GEMINI_VISION_OCR_*`, `EVENTS_LOGGING_ENABLED`,
`EVENTS_QUEUE_MAX`, any `SAPLING_FLAG_*` kill switch, `SUPABASE_JWT_SIGNING_KEY`
/ `SUPABASE_ANON_KEY` if set. A reference to a variable the API does not have
resolves to an empty string, which every one of these treats as unset.

Worker-only tuning (all optional; the CLI flags override them):

| Variable | Default | Meaning |
| --- | --- | --- |
| `JOBS_POLL_INTERVAL_SECONDS` | 5 | sleep when the queue is empty |
| `JOBS_BATCH` | 10 | most jobs per pass |
| `JOBS_LEASE_SECONDS` | 300 | a claim's lease; heartbeated every lease/3 while the handler runs |
| `JOBS_MAX_HEARTBEAT_SECONDS` | 3600 | stop heartbeating after this, so a hung handler's job is re-offered |
| `JOBS_PRUNE_AFTER_DAYS` | 14 | delete `succeeded` jobs older than this, from an hourly `jobs.prune` job (0 = never). Dead letters are never pruned. |
| `JOBS_LOG_FORMAT` | text | `json` for structured logs |
