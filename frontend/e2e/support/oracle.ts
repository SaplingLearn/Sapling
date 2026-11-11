/**
 * Run a backend oracle check from a journey (PKG-13 fix round).
 *
 * The fixtures truncate + re-seed BEFORE every test (support/db.ts), so after a
 * full Playwright run the database holds only the LAST test's rows — the
 * post-suite `python -m e2e_oracles` cannot see what the loop journey wrote.
 * The loop journey therefore runs `--check learn_loop --expect-loop-activity`
 * itself, right after its walk, while its rows exist (the flag makes an empty
 * or activity-free stack a finding, so the check can never pass vacuously).
 *
 * Same python resolution and cwd as support/decrypt.ts (E2E_SEED_PYTHON,
 * backend/ — backend/.env supplies SUPABASE_DB_URL and ENCRYPTION_KEY).
 */
import { spawn } from "node:child_process";
import path from "node:path";

export interface OracleRun {
  code: number | null;
  count: number;
  findings: { oracle: string; summary: string }[];
  stderr: string;
}

export function runOracle(args: string[]): Promise<OracleRun> {
  const repoRoot = path.resolve(__dirname, "..", "..", "..");
  const backendDir = path.join(repoRoot, "backend");
  const python =
    process.env.E2E_SEED_PYTHON?.trim() || path.join(backendDir, "venv", "bin", "python");

  return new Promise((resolve, reject) => {
    const child = spawn(python, ["-m", "e2e_oracles", "--json", ...args], {
      cwd: backendDir,
      timeout: 60_000,
    });
    let out = "";
    let err = "";
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (err += d));
    child.on("error", reject);
    child.on("close", (code) => {
      try {
        const parsed = JSON.parse(out) as { count: number; findings: OracleRun["findings"] };
        resolve({ code, count: parsed.count, findings: parsed.findings, stderr: err });
      } catch (e) {
        reject(new Error(`oracle exited ${code} with non-JSON output (${python}):\n${out}\n${err}\n${e}`));
      }
    });
  });
}
