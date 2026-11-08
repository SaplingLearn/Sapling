/**
 * Restore the rich-seed baseline (TRUNCATE mutable tables + db.seed_local_rich).
 * Run by scripts/figma-capture.sh before teardown: the showcase overlay renames
 * rooms/invite codes, and `supabase stop` backs the DB up — left in place, the
 * next `make e2e-up` rich seed 409s on rooms.invite_code.
 *   node e2e/figma/reset-db.ts   (Node ≥ 23 strips the types)
 *
 * support/db.ts is written for Playwright's CJS transform and reads
 * `__dirname`; Node loads it as ESM here, so provide the global first.
 */
import path from "node:path";

(globalThis as Record<string, unknown>).__dirname = path.join(import.meta.dirname, "..", "support");

async function main(): Promise<void> {
  // @ts-expect-error TS5097 — run directly by Node (type stripping), not bundled
  const { resetDb } = await import("../support/db.ts");
  await resetDb();
  console.log("✓ DB reset to the rich-seed baseline");
}

void main().catch((e) => {
  console.error(e);
  process.exit(1);
});
