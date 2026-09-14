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
  "growth_stages",
  "xp_rules",
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

/**
 * Mint XP the same way the app does — for journeys that need "the user just
 * earned XP" without driving a real quiz/session/upload through the UI
 * (gamification.spec.ts, Task 17).
 *
 * This is a straight port of `backend/services/xp_service.py::award_xp`,
 * NOT a call into the API (there is no XP-grant endpoint — every real award
 * happens as a side effect of some other action). Keep it in lock-step with
 * that module if the award path changes:
 *   1. resolve the amount from `xp_rules` (unless the caller overrides it —
 *      mirrors how achievement rewards pass an explicit `amount`);
 *   2. insert one `xp_events` row keyed on the same idempotency key
 *      (`rule_key:source_type:source_id`, `-` for a missing leg) via
 *      `ON CONFLICT (idempotency_key) DO NOTHING` — the JS equivalent of
 *      catching the Postgres 409 the Python side handles;
 *   3. on a fresh insert (not a duplicate), recompute `users.total_xp` /
 *      `users.level` from the ledger and write them back — `level` walks
 *      the `growth_stages` curve exactly like `services/growth.py::level_for_xp`
 *      (this is why `growth_stages`/`xp_rules` were added to
 *      TRUNCATE_DENYLIST above: they're migration-seeded reference tables
 *      `db/seed_local_rich.py` never re-inserts, so without the denylist
 *      entry every per-test reset would leave both tables empty and this
 *      helper — and the real HeroCard/LeaderboardTab/ActivityTab UI — with
 *      no curve/rules to read).
 */
export async function awardXp(
  userId: string,
  ruleKey: string,
  sourceType: string | null = null,
  sourceId: string | null = null,
  amount?: number,
): Promise<{
  awarded: number;
  totalXp: number;
  level: number;
  leveledUp: boolean;
  duplicate: boolean;
}> {
  return withDb(async (client) => {
    const value = amount ?? (await ruleAmount(client, ruleKey));
    const priorState = await userXpState(client, userId);
    if (value <= 0) {
      return { awarded: 0, totalXp: priorState.totalXp, level: priorState.level, leveledUp: false, duplicate: false };
    }

    const idempotencyKey = `${ruleKey}:${sourceType ?? "-"}:${sourceId ?? "-"}`;
    const inserted = await client.query(
      `INSERT INTO xp_events (user_id, rule_key, amount, source_type, source_id, idempotency_key)
       VALUES ($1, $2, $3, $4, $5, $6)
       ON CONFLICT (idempotency_key) DO NOTHING`,
      [userId, ruleKey, value, sourceType, sourceId, idempotencyKey],
    );
    if (inserted.rowCount === 0) {
      // Already paid out — same as award_xp's 409 branch: report current
      // state, don't touch the cache.
      return { awarded: 0, totalXp: priorState.totalXp, level: priorState.level, leveledUp: false, duplicate: true };
    }

    const totalXp = priorState.totalXp + value;
    const level = await levelForXp(client, totalXp);
    await client.query("UPDATE users SET total_xp = $1, level = $2 WHERE id = $3", [
      totalXp,
      level,
      userId,
    ]);
    return { awarded: value, totalXp, level, leveledUp: level > priorState.level, duplicate: false };
  });
}

async function ruleAmount(client: Client, ruleKey: string): Promise<number> {
  const rows = (
    await client.query<{ amount: number; enabled: boolean }>(
      "SELECT amount, enabled FROM xp_rules WHERE key = $1",
      [ruleKey],
    )
  ).rows;
  if (rows.length === 0 || !rows[0].enabled) return 0;
  return Number(rows[0].amount) || 0;
}

async function userXpState(
  client: Client,
  userId: string,
): Promise<{ totalXp: number; level: number }> {
  const rows = (
    await client.query<{ total_xp: number | null; level: number | null }>(
      "SELECT total_xp, level FROM users WHERE id = $1",
      [userId],
    )
  ).rows;
  if (rows.length === 0) return { totalXp: 0, level: 1 };
  return { totalXp: Number(rows[0].total_xp) || 0, level: Number(rows[0].level) || 1 };
}

/**
 * Mirrors `services/growth.py::level_for_xp` — walk the `growth_stages`
 * curve from level 1, spending XP per band, until it runs out or the
 * terminal (highest `min_level`) band is reached. Bands are read fresh
 * every call rather than cached: this is test-only code where a handful of
 * extra round trips per journey is not a real cost, and staying uncached
 * sidesteps ever needing an invalidation story here.
 */
async function levelForXp(client: Client, totalXp: number): Promise<number> {
  const rows = (
    await client.query<{ min_level: number; xp_to_complete: number | null }>(
      "SELECT min_level, xp_to_complete FROM growth_stages ORDER BY min_level ASC",
    )
  ).rows;
  if (rows.length === 0) return 1;

  const maxLevel = rows[rows.length - 1].min_level;
  const bands = rows.map((stage, i) => {
    const next = rows[i + 1];
    const span = next ? next.min_level - stage.min_level : 0;
    const cost = stage.xp_to_complete;
    return {
      minLevel: stage.min_level,
      perLevel: cost && span ? Math.floor(cost / span) : 0,
    };
  });
  const xpForLevel = (level: number): number => {
    let band: { minLevel: number; perLevel: number } | null = null;
    for (const b of bands) {
      if (level >= b.minLevel) band = b;
      else break;
    }
    return band ? band.perLevel : 0;
  };

  let level = 1;
  let spent = 0;
  while (level < maxLevel) {
    const cost = xpForLevel(level);
    if (cost <= 0 || spent + cost > totalXp) break;
    spent += cost;
    level += 1;
  }
  return level;
}
