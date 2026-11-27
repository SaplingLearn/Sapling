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
from services.encryption import bind, decrypt_if_present
items = json.load(sys.stdin)
sys.stdout.write(json.dumps([
    decrypt_if_present(
        i["value"],
        bind=bind(i["table"], i["column"], tuple(i["row"]) if isinstance(i["row"], list) else i["row"]),
    )
    for i in items
]))
`;

/** One encrypted cell: its raw value plus the (table, column, row key) it is
 *  bound to (sec2 M13: a v2 value only opens in its own cell). `row` is the
 *  registry key for that column in `backend/services/encryption.py`
 *  (`ENCRYPTED_COLUMNS`), e.g. a message's `session_id` or a row's `id`. */
export type EncryptedCell = {
  value: string;
  table: string;
  column: string;
  row: string | string[];
};

/** Decrypt a batch of raw column values via the backend's own helper. */
export function decryptTexts(values: EncryptedCell[]): Promise<string[]> {
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
export async function decryptText(value: EncryptedCell): Promise<string> {
  const [plain] = await decryptTexts([value]);
  return plain;
}

// Nested ciphertexts (encryption.NESTED_CIPHERTEXTS) bind with nested_bind —
// table|column|path|row — e.g. sessions.loop_state#reasoning_encrypted (W2.3).
const PY_DECRYPT_NESTED = `
import json, sys
from dotenv import load_dotenv
load_dotenv()
from services.encryption import decrypt_if_present, nested_bind
items = json.load(sys.stdin)
sys.stdout.write(json.dumps([
    decrypt_if_present(
        i["value"],
        bind=nested_bind(
            i["table"], i["column"], i["path"],
            tuple(i["row"]) if isinstance(i["row"], list) else i["row"],
        ),
    )
    for i in items
]))
`;

/** One nested ciphertext cell: column JSON path + the row key nested_bind uses. */
export type NestedEncryptedCell = EncryptedCell & { path: string };

/** Decrypt a batch of nested ciphertext values via the backend's nested_bind. */
export function decryptNestedTexts(values: NestedEncryptedCell[]): Promise<string[]> {
  const repoRoot = path.resolve(__dirname, "..", "..", "..");
  const backendDir = path.join(repoRoot, "backend");
  const python =
    process.env.E2E_SEED_PYTHON?.trim() ||
    path.join(backendDir, "venv", "bin", "python");

  return new Promise((resolve, reject) => {
    const child = spawn(python, ["-c", PY_DECRYPT_NESTED], {
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
        reject(new Error(`nested decrypt helper exited ${code} (${python}):\n${err}`));
        return;
      }
      try {
        resolve(JSON.parse(out) as string[]);
      } catch (e) {
        reject(new Error(`nested decrypt helper returned non-JSON: ${out}\n${e}`));
      }
    });
    child.stdin.write(JSON.stringify(values));
    child.stdin.end();
  });
}

/** Decrypt one nested ciphertext value. */
export async function decryptNestedText(value: NestedEncryptedCell): Promise<string> {
  const [plain] = await decryptNestedTexts([value]);
  return plain;
}
