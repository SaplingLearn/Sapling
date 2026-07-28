/**
 * The ONE place Playwright touches the database (#385) — journeys never
 * hand-roll SQL plumbing. Direct Postgres via the `pg` devDependency (there
 * is no host `psql` in the documented setup; repo scripts run psql inside
 * the Supabase container, which the harness can't assume).
 *
 * Per-test isolation mirrors the #397 pytest integration fixtures
 * (backend/tests/integration/conftest.py — the authority for this pattern):
 * TRUNCATE every mutable public table RESTART IDENTITY CASCADE, preserving
 * the reference/catalog layer via a denylist, then restore the rich seed
 * baseline (db/seed_local_rich.py, deterministic `rich-*` ids).
 *
 * Safety (mirrors #397's non-negotiable): the truncate runs over a direct
 * Postgres connection, bypassing PostgREST entirely — so before any
 * connection opens, the DB URL host must be EXACTLY loopback. Raise loudly,
 * never skip: a silent skip would read as "safe" while a misconfigured
 * E2E_DB_URL wiped whatever it pointed at.
 */
import { execFile } from "node:child_process";
import path from "node:path";
import { promisify } from "node:util";

import { Client } from "pg";

const execFileAsync = promisify(execFile);

/** `make e2e-up`'s local Postgres (docs/local-supabase.md). */
const DEFAULT_DB_URL =
  "postgresql://postgres:postgres@127.0.0.1:54322/postgres";

const DB_URL = process.env.E2E_DB_URL?.trim() || DEFAULT_DB_URL;

// Exact-match loopback hosts — deliberately stricter than a substring check,
// so `postgresql://…@127.0.0.1.evil.com/…` is rejected (same rationale as
// backend/tests/integration/conftest.py::_db_url_is_local).
const LOCAL_DB_HOSTS = new Set(["127.0.0.1", "localhost", "::1", "[::1]"]);

function requireLocalDbUrl(url: string): void {
  let host = "";
  try {
    host = new URL(url).hostname.trim().toLowerCase();
  } catch {
    host = "";
  }
  if (!LOCAL_DB_HOSTS.has(host)) {
    throw new Error(
      "REFUSING to open the E2E Postgres connection: DB URL host is not local " +
        `(got ${JSON.stringify(url)}). The truncate isolation bypasses PostgREST ` +
        "and would wipe whatever this points at. Point E2E_DB_URL at the local " +
        `stack (${DEFAULT_DB_URL}) or unset it.`,
    );
  }
}

/**
 * Tables the reset must NOT truncate: the migration ledger plus
 * migration-seeded reference/catalog tables that `seed_local_rich` does not
 * restore (or re-upserts idempotently). KEEP IN SYNC with
 * backend/tests/integration/conftest.py::_TRUNCATE_DENYLIST — that list is
 * the authority; a new migration-seeded reference table must be added in
 * both places or its rows vanish on the first reset.
 */
const TRUNCATE_DENYLIST = [
  "schema_migrations",
  "terms",
  "roles",
  "achievements",
  "achievement_triggers",
  "cosmetics",
  "schools",
  "courses",
  "course_offerings",
];

// One DO block = one statement: enumerate the mutable public tables and
// truncate them together, so mutual FKs among the targets can't order-fail
// and CASCADE only ever reaches tables that are themselves targets.
const TRUNCATE_SQL = `
DO $$
DECLARE
  targets text;
BEGIN
  SELECT string_agg(format('%I', tablename), ', ')
    INTO targets
    FROM pg_tables
   WHERE schemaname = 'public'
     AND tablename NOT IN (${TRUNCATE_DENYLIST.map((t) => `'${t}'`).join(", ")});
  IF targets IS NOT NULL THEN
    EXECUTE 'TRUNCATE ' || targets || ' RESTART IDENTITY CASCADE';
  END IF;
END
$$;
`;

async function withDb<T>(fn: (client: Client) => Promise<T>): Promise<T> {
  requireLocalDbUrl(DB_URL);
  const client = new Client({ connectionString: DB_URL });
  await client.connect();
  try {
    return await fn(client);
  } finally {
    await client.end();
  }
}

/** Truncate all mutable tables (catalog layer preserved via the denylist). */
export async function truncateMutable(): Promise<void> {
  await withDb((client) => client.query(TRUNCATE_SQL));
}

/**
 * Restore the rich seed baseline by running the canonical seeder — not a
 * reimplementation: `db/seed_local_rich.py` owns the dataset (encrypted
 * columns included, which plain SQL could not reproduce). Runs the backend
 * venv's python from backend/ so backend/.env (local Supabase URL + keys,
 * ENCRYPTION_KEY) is picked up, exactly like `make e2e-up`'s seed step.
 */
export async function reseedBaseline(): Promise<void> {
  const repoRoot = path.resolve(__dirname, "..", "..", "..");
  const backendDir = path.join(repoRoot, "backend");
  const python =
    process.env.E2E_SEED_PYTHON?.trim() ||
    path.join(backendDir, "venv", "bin", "python");
  try {
    await execFileAsync(python, ["-m", "db.seed_local_rich"], {
      cwd: backendDir,
      timeout: 120_000,
    });
  } catch (err) {
    const e = err as { stdout?: string; stderr?: string; message?: string };
    throw new Error(
      `re-seed failed (${python} -m db.seed_local_rich):\n` +
        `${e.stderr || e.stdout || e.message}`,
    );
  }
}

/**
 * Per-test DB isolation (#385): truncate + re-seed BEFORE each test, so a
 * prior test's writes (or a crash) can never leak forward. Wired up as an
 * automatic fixture in e2e/support/fixtures.ts.
 */
export async function resetDb(): Promise<void> {
  await truncateMutable();
  await reseedBaseline();
}

/**
 * Raw-SQL readback for journey assertions (#392): journeys write through the
 * app and assert directly against Postgres (the #397 posture), so the read
 * must bypass PostgREST/the API entirely. Parameterized ($1, $2, …) SELECTs
 * only — mutations stay the fixtures' job. Runs behind the same
 * loopback-host guard as the reset.
 */
export async function queryRaw(
  sql: string,
  params: unknown[] = [],
): Promise<Record<string, unknown>[]> {
  return withDb(async (client) => (await client.query(sql, params)).rows);
}
