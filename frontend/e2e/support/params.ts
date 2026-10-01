/**
 * Learning-loop constants for the journeys (PKG-13): read from
 * backend/learning/params.py through the backend venv's python — never as a
 * TS literal — so a retuned constant retunes the journey with it. Same spawn
 * shape and python resolution as support/decrypt.ts (E2E_SEED_PYTHON, cwd
 * backend/); names travel on stdin, values come back as JSON on stdout.
 */
import { spawn } from "node:child_process";
import path from "node:path";

const PY_PARAMS = `
import json, sys
from learning import params
names = json.load(sys.stdin)
sys.stdout.write(json.dumps({n: getattr(params, n) for n in names}))
`;

/** The named `learning.params` constants (numbers or booleans). */
export function learningParams(names: string[]): Promise<Record<string, number | boolean>> {
  const repoRoot = path.resolve(__dirname, "..", "..", "..");
  const backendDir = path.join(repoRoot, "backend");
  const python =
    process.env.E2E_SEED_PYTHON?.trim() || path.join(backendDir, "venv", "bin", "python");

  return new Promise((resolve, reject) => {
    const child = spawn(python, ["-c", PY_PARAMS], { cwd: backendDir, timeout: 30_000 });
    let out = "";
    let err = "";
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (err += d));
    child.on("error", reject);
    child.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(`params helper exited ${code} (${python}):\n${err}`));
        return;
      }
      try {
        resolve(JSON.parse(out) as Record<string, number | boolean>);
      } catch (e) {
        reject(new Error(`params helper returned non-JSON: ${out}\n${e}`));
      }
    });
    child.stdin.write(JSON.stringify(names));
    child.stdin.end();
  });
}
