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
 * is written here, and the two cannot drift). The first block is what
 * `validate_config()` and the key canary require at boot: a worker missing
 * one exits 2. Add every other variable the API service has set that the
 * worker's code paths read (see the runbook's "Worker variables"); a
 * reference to a variable the API does not have resolves to "". */
const SHARED_VARIABLES = [
  // required at boot
  "APP_ENV",
  "SUPABASE_URL",
  "SUPABASE_SERVICE_KEY",
  "ENCRYPTION_KEY",
  "SESSION_SECRET",
  "ANTHROPIC_API_KEY",
  "GEMINI_API_KEY",
  // read by job handlers (confirm each is set on the API service first)
  "SAPLING_MODEL_MODE",
  "LOGFIRE_TOKEN",
  "POSTHOG_PROJECT_TOKEN",
];

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
