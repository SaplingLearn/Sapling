// Railway Infrastructure as Code for the backend's services (#114 / #116).
//
// UNVERIFIED AGAINST A LIVE PROJECT. Written from Railway's IaC docs
// (docs.railway.com/infrastructure-as-code, read 2026-11-08) without access
// to the Railway project. Read docs/deploy/railway.md before running
// anything; `railway config plan` must be read line by line before any apply.
//
// Why this and not railway.toml: Railway deprecated config-as-code
// (railway.toml / railway.json); those files stop being read on 2026-12-01.
// IaC is a TypeScript program; this file is the only one in .railway/.
//
// What it manages. It is a PARTIAL (`export const partial`): an apply only
// creates, changes or deletes resources this file declares and owns. Other
// services in the project (the frontend, anything created in the UI) are not
// touched. As committed it declares ONE service, the new `worker`. The API
// service is declared only when MANAGE_API is true (step 6 of the runbook),
// because declaring an existing service makes this partial own it, and the
// first apply would then delete any of its variables the file does not list.

import { defineRailway, github, project, service } from "railway/iac";

export const partial = "sapling-backend";

// ── Confirm these against the Railway project before the first plan ────────

/** The GitHub repository the backend services build from. */
const REPO = "saplinglearn/sapling";
/** The Railway project's name, as shown in the dashboard. */
const PROJECT = "sapling";
/** The existing API service's name (Service > Settings > Name). The worker's
 * variables are Railway references to it, `${{<name>.<VAR>}}`. */
const API_SERVICE = "backend";
/** Branch per Railway environment: `main` deploys staging, `production`
 * deploys production (backend/promotion/README.md). */
const BRANCH_FOR: Record<string, string> = { production: "production" };
const DEFAULT_BRANCH = "main";
/** Keep false until the runbook's step 6. */
const MANAGE_API = false;

/** Variables the worker takes from the API service, by reference (no secret
 * is written here, and the two cannot drift). Derived by grepping every
 * `os.getenv` / `os.environ` / config read on the code paths a worker runs:
 * boot (worker/__main__.py::boot), the job handlers (document.process,
 * document.index, course_context.refresh, jobs.prune, and gradescope.sync
 * once it lands) and the agents they call. Keep it in step with
 * backend/tests/test_railway_worker_env.py, which pins it.
 *
 * Railway does not document what a reference to a variable the API service
 * does NOT set becomes (docs.railway.com/variables, read 2026-11-08), so do
 * not leave one dangling: list every name the API lacks in NOT_ON_API below
 * (runbook step 3) and it is left out. Everything here treats unset as its
 * default. */
const BOOT_VARIABLES = [
  // validate_config() and the key canary: a worker missing one exits 2.
  "APP_ENV",
  "SUPABASE_URL",
  "SUPABASE_SERVICE_KEY",
  "ENCRYPTION_KEY",
  "SESSION_SECRET",
  "ANTHROPIC_API_KEY",
  "GEMINI_API_KEY",
  // read at boot: freeze_model_mode(), config's db_user_scope key warning.
  "SAPLING_MODEL_MODE",
  "SUPABASE_JWT_SIGNING_KEY",
  "SUPABASE_ANON_KEY",
];

const HANDLER_VARIABLES = [
  // services/extraction_service.py + extraction_backends/ (document.process)
  "OCR_ENGINE",
  "GEMINI_VISION_OCR_ENABLED",
  "GEMINI_VISION_OCR_MAX_PAGES",
  "GOT_OCR_ENABLED",
  "GOT_OCR_MODEL_PATH",
  // services/cache.py: the content-addressed OCR cache, shared with the API
  "REDIS_URL",
  // services/document_indexing.py (document.index)
  "INDEX_MAX_ATTEMPTS",
  "INDEX_LEASE_SECONDS",
  // services/durable.py (imported on the upload pipeline's path)
  "DBOS_ENABLED",
  "DBOS_DATABASE_URL",
  // services/events_service.py: handlers record events + LLM usage
  "EVENTS_LOGGING_ENABLED",
  "EVENTS_QUEUE_MAX",
  // services/posthog_client.py + config.py: the usage mirror and erasure
  "POSTHOG_PROJECT_TOKEN",
  "POSTHOG_HOST",
  "POSTHOG_API_HOST",
  "POSTHOG_PROJECT_ID",
  "POSTHOG_PERSONAL_API_KEY",
  "POSTHOG_DISABLED",
  // services/feature_flags.py: the same snapshot/roles TTLs as the API
  // (VERSION_CHECK_S arrives with the stateless-flags change above this one)
  "FEATURE_FLAGS_SNAPSHOT_TTL_S",
  "FEATURE_FLAGS_ROLES_TTL_S",
  "FEATURE_FLAGS_VERSION_CHECK_S",
  // config.py (read on import; the worker does not configure Logfire yet)
  "LOGFIRE_TOKEN",
];

/** Every server-side flag's env kill switch (services/feature_flags.py
 * REGISTRY, `SAPLING_FLAG_<KEY>`): a switch thrown on the API must hold in
 * the worker too, or the queue keeps doing what the API was told to stop.
 * The nav `hide_*` flags are frontend-only and left out. Includes the flags
 * the stack above this branch adds (llm_budget, llm_outage_drill,
 * async_db_client, stateless_rate_limit, stateless_locks), so it is right at
 * every step. */
const FLAG_KILL_SWITCHES = [
  "decision_router",
  "product_analytics",
  "llm_fallback",
  "jobs_queue",
  "db_user_scope",
  "realtime_rls",
  "llm_budget",
  "llm_outage_drill",
  "async_db_client",
  "stateless_rate_limit",
  "stateless_locks",
  "stateless_tutor_sessions",
].map((key) => `SAPLING_FLAG_${key.toUpperCase()}`);

/** Per-slot model overrides (agents/_providers.py: `SAPLING_MODEL_<TASK>`,
 * `SAPLING_MODEL_FALLBACK_<TASK>`) for the agent tasks a worker runs:
 * classifier/summary/concepts/syllabus (document.process), ocr_vision
 * (page OCR), course_summary (course_context.refresh). Without them a slot
 * rolled back on the API would still run the default model in the worker. */
const WORKER_AGENT_TASKS = [
  "classifier", "summary", "concepts", "syllabus", "ocr_vision", "course_summary",
];
const MODEL_SLOT_VARIABLES = WORKER_AGENT_TASKS.flatMap((task) => [
  `SAPLING_MODEL_${task.toUpperCase()}`,
  `SAPLING_MODEL_FALLBACK_${task.toUpperCase()}`,
]);

/** Names from the lists above that the API service does NOT set in this
 * project (runbook step 3 fills it from `railway variables`). They are not
 * referenced. Never put a BOOT_VARIABLES name here except the three optional
 * ones (SAPLING_MODEL_MODE, SUPABASE_JWT_SIGNING_KEY, SUPABASE_ANON_KEY). */
const NOT_ON_API: string[] = [];

const SHARED_VARIABLES = [
  ...BOOT_VARIABLES,
  ...HANDLER_VARIABLES,
  ...FLAG_KILL_SWITCHES,
  ...MODEL_SLOT_VARIABLES,
].filter((name) => !NOT_ON_API.includes(name));

// ── Services ────────────────────────────────────────────────────────────────

const ref = (name: string) => `\${{${API_SERVICE}.${name}}}`;

export default defineRailway((ctx) => {
  const branch = BRANCH_FOR[ctx.environmentName] ?? DEFAULT_BRANCH;
  const source = github(REPO, { branch, rootDirectory: "backend" });

  // `python -m worker` drains the jobs queue (backend/worker/__main__.py). No
  // healthcheck and no domain: it serves nothing. Any number of replicas is
  // safe (claims use FOR UPDATE SKIP LOCKED); start with one.
  const worker = service("worker", {
    source,
    start: "python -m worker",
    replicas: 1,
    domains: [],
    env: {
      // The Dockerfile's last stage resolves this build argument; Railway
      // passes a service variable to the build when the Dockerfile declares
      // an ARG of that name. `worker` = the OCR stack + Chromium, no API.
      SAPLING_IMAGE_TARGET: "worker",
      ...Object.fromEntries(SHARED_VARIABLES.map((name) => [name, ref(name)])),
    },
  });

  const resources = [worker];

  if (MANAGE_API) {
    // The API service as it should be described. Before flipping MANAGE_API,
    // paste the API's CURRENT variables into `env` below (`railway config
    // pull` writes them as preserve() entries), or the apply deletes them.
    const api = service(API_SERVICE, {
      source,
      start: "uvicorn main:app --host 0.0.0.0 --port 5000",
      healthcheck: "/api/health",
      env: {
        // `full` (the default when unset) until the cut-over in the runbook;
        // then `api`: no torch, no Docling, no Chromium.
        SAPLING_IMAGE_TARGET: "full",
        // ...the pulled preserve() entries go here.
      },
    });
    resources.push(api);
  }

  return project(PROJECT, { resources });
});
