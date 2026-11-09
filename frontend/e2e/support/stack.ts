/**
 * The already-booted local E2E stack (#384) that this harness targets.
 *
 * Which stack, in order: the env (E2E_FRONTEND_URL / E2E_BACKEND_URL /
 * E2E_DB_URL — scripts/e2e-cycle.sh exports them for its slot), else the
 * manifest the last `make e2e-up` in this checkout wrote (.e2e/stack.json,
 * scripts/lib/e2e-slot.sh), else the classic slot-0 contract CI boots:
 * frontend :3000, backend :5000, Postgres 127.0.0.1:54322, PostgREST :54321.
 * Locally those classic ports are the dev app's; slots use :310N / :510N.
 */
import fs from "node:fs";
import path from "node:path";

interface StackManifest {
  slot?: number;
  frontendUrl?: string;
  backendUrl?: string;
  dbUrl?: string;
  supabaseUrl?: string;
}

function readManifest(): StackManifest {
  try {
    const file = path.resolve(__dirname, "..", "..", "..", ".e2e", "stack.json");
    return JSON.parse(fs.readFileSync(file, "utf8")) as StackManifest;
  } catch {
    return {};
  }
}

const manifest = readManifest();

export const FRONTEND_URL =
  process.env.E2E_FRONTEND_URL?.trim() || manifest.frontendUrl || "http://localhost:3000";

export const BACKEND_URL =
  process.env.E2E_BACKEND_URL?.trim() || manifest.backendUrl || "http://localhost:5000";

/** The stack's Postgres — the only DB the harness may truncate or seed. */
export const DB_URL =
  process.env.E2E_DB_URL?.trim() ||
  manifest.dbUrl ||
  "postgresql://postgres:postgres@127.0.0.1:54322/postgres";

/** The stack's PostgREST, for the seeder (which reads SUPABASE_URL). */
export const SUPABASE_URL =
  manifest.supabaseUrl || process.env.SUPABASE_URL?.trim() || "http://127.0.0.1:54321";

/** The primary seeded user (db/seed_local_rich.py); mirrors the #397 pytest
 * integration fixtures' USER_ACTIVE. */
export const USER_ACTIVE = "rich-user-active";

/** The second seeded user (db/seed_local_rich.py, "Sam Second") — approved,
 * onboarded, and a member of the seeded study room alongside USER_ACTIVE.
 * Multi-user journeys (#394) sign this user into a second browser context
 * via support/session.ts. */
export const USER_SECOND = "rich-user-second";

/** The seeded user who has NOT completed onboarding (db/seed_local_rich.py:
 * onboarding_completed=False, is_approved=True) — the state a real student is
 * in the first time they reach the funnel.
 *
 * Note /onboarding is NOT in middleware.ts's PROTECTED list or its matcher,
 * and Onboarding.tsx only redirects when unauthenticated — so the route
 * renders for any signed-in user regardless of approval or onboarding state.
 * This user is chosen because it is the realistic one, not because the route
 * gates on it. */
export const USER_NEW = "rich-user-new";

async function isUp(url: string): Promise<boolean> {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(3_000) });
    return res.ok;
  } catch {
    return false;
  }
}

/**
 * Fail fast — with the exact fix — when the stack is not up. The harness
 * never boots servers itself (that is #384's `make e2e-up` contract), so a
 * down stack must be a clear error, not a hang or a cryptic ECONNREFUSED
 * mid-spec.
 */
export async function requireStackUp(): Promise<void> {
  const checks: Array<[name: string, url: string]> = [
    ["backend (uvicorn)", `${BACKEND_URL}/api/health`],
    ["frontend (next start)", `${FRONTEND_URL}/`],
  ];
  const down: string[] = [];
  for (const [name, url] of checks) {
    if (!(await isUp(url))) down.push(`${name} at ${url}`);
  }
  if (down.length > 0) {
    throw new Error(
      `E2E stack is not up — unreachable: ${down.join(", ")}.\n` +
        "Boot it first from the repo root — `scripts/e2e-cycle.sh -- <command>` " +
        "claims a free slot and runs the whole cycle, or `make e2e-up` " +
        "(see docs/local-supabase.md) — then re-run `npx playwright test`.",
    );
  }
}
