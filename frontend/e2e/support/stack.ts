/**
 * The already-booted local E2E stack (#384) that this harness targets.
 *
 * Which stack, in order: the env (E2E_FRONTEND_URL / E2E_BACKEND_URL —
 * scripts/e2e-cycle.sh exports them for its slot), else the manifest the last
 * `make e2e-up` in this checkout wrote (.e2e/stack.json,
 * scripts/lib/e2e-slot.sh), else — in CI only — the classic slot-0 contract:
 * frontend :3000, backend :5000. Locally those classic ports are the DEV app,
 * whose database the per-test reset truncates, so with no slot booted the
 * harness refuses (requireStackUp) rather than fall back to them.
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
const IN_CI = process.env.CI === "true";

export const FRONTEND_URL =
  process.env.E2E_FRONTEND_URL?.trim() || manifest.frontendUrl || (IN_CI ? "http://localhost:3000" : "");

export const BACKEND_URL =
  process.env.E2E_BACKEND_URL?.trim() || manifest.backendUrl || (IN_CI ? "http://localhost:5000" : "");

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
 * Onboarding is enforced (2026-11-12): middleware.ts gates /onboarding like
 * the shell and, off the same GET /api/auth/me read, sends this user from any
 * app page to /onboarding (and an onboarded one from /onboarding to
 * /dashboard). So this user sees the funnel and nothing of the app until it
 * is finished. */
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
  if (!FRONTEND_URL || !BACKEND_URL) {
    throw new Error(
      "No E2E stack to target: E2E_FRONTEND_URL / E2E_BACKEND_URL are unset and there is " +
        "no .e2e/stack.json. Outside CI the classic :3000/:5000 are the DEV app, whose " +
        "database every test would truncate — refusing. Boot a slot first: " +
        "`scripts/e2e-cycle.sh -- <command>`, or `make e2e-up` (docs/local-supabase.md).",
    );
  }
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
