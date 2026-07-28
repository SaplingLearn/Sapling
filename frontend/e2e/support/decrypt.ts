/**
 * Decrypt seam for raw-SQL readbacks (#392).
 *
 * Encrypted columns (`messages.content` here) must be asserted two ways:
 * ciphertext at rest, AND decrypting to the expected plaintext. The decrypt
 * half cannot be reimplemented in TS — the AES-GCM wire format and the
 * ENCRYPTION_KEY belong to `backend/services/encryption.py` — so this shells
 * out to the backend venv's python with cwd=backend/ (backend/.env supplies
 * ENCRYPTION_KEY via config's load_dotenv), exactly like
 * `support/db.ts::reseedBaseline` runs the seeder. Same python override env
 * var (E2E_SEED_PYTHON) on purpose: one knob points the harness at one venv.
 *
 * Mirrors the assertion pattern of
 * `backend/tests/integration/test_encryption_roundtrip.py` — note that
 * `decrypt_if_present` falls back to returning its input on undecryptable
 * values (legacy-plaintext tolerance), so a "decrypts to X" check is only
 * meaningful alongside the separate ciphertext-at-rest (`raw != plaintext`)
 * assertion. Specs must always make both.
 */
import { spawn } from "node:child_process";
import path from "node:path";

// Values travel on stdin / stdout as JSON arrays, so ciphertext never hits
// argv (length limits, shell-quoting hazards).
const PY_DECRYPT = `
import json, sys
from dotenv import load_dotenv
load_dotenv()  # services.encryption reads ENCRYPTION_KEY straight from env
from services.encryption import decrypt_if_present
values = json.load(sys.stdin)
sys.stdout.write(json.dumps([decrypt_if_present(v) for v in values]))
`;

/** Decrypt a batch of raw column values via the backend's own helper. */
export function decryptTexts(values: string[]): Promise<string[]> {
  const repoRoot = path.resolve(__dirname, "..", "..", "..");
  const backendDir = path.join(repoRoot, "backend");
  const python =
    process.env.E2E_SEED_PYTHON?.trim() ||
    path.join(backendDir, "venv", "bin", "python");

  return new Promise((resolve, reject) => {
    const child = spawn(python, ["-c", PY_DECRYPT], {
      cwd: backendDir,
      timeout: 30_000,
    });
    let out = "";
    let err = "";
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (err += d));
    child.on("error", reject);
    child.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(`decrypt helper exited ${code} (${python}):\n${err}`));
        return;
      }
      try {
        resolve(JSON.parse(out) as string[]);
      } catch (e) {
        reject(new Error(`decrypt helper returned non-JSON: ${out}\n${e}`));
      }
    });
    child.stdin.write(JSON.stringify(values));
    child.stdin.end();
  });
}

/** Decrypt one raw column value. */
export async function decryptText(value: string): Promise<string> {
  const [plain] = await decryptTexts([value]);
  return plain;
}
