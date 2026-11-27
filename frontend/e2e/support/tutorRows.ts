/**
 * Z08 fixture: one tutor row saved exactly as the server saves a code-served
 * turn — `services/tutor/messages.py::save_message_sync`, its 🔒 content sealed
 * to the session (sec2 M13) — for journeys about what the transcript draws.
 *
 * The learning loop serves class material verbatim, with no model between the
 * upload and the page: an H2 hint is a classmate's shared passage, an H4 or H6
 * payload and a check pose are item text drafted from classmates' uploads. A
 * row of that text is what this writes, without seeding a passage and walking
 * the hint ladder up to it. Local stack only: the same loopback guard as the
 * other backend fixtures (learn-grade-recovery.spec.ts).
 */
import { spawn } from "node:child_process";
import path from "node:path";

const PY_SAVE_TUTOR_ROW = String.raw`
import json, os, sys
from urllib.parse import urlsplit
from dotenv import load_dotenv
load_dotenv()
if (os.getenv('APP_ENV') not in {'local', 'test'}
        or urlsplit(os.getenv('SUPABASE_URL', '')).hostname not in {'127.0.0.1', 'localhost', '::1'}):
    raise RuntimeError('the tutor-row fixture writes only to a local/test loopback stack')
from services.tutor.messages import save_message_sync
row = json.load(sys.stdin)
save_message_sync(row['session_id'], 'assistant', row['text'])
`;

/** Save `text` as the tutor's next row of `sessionId`. */
export function saveTutorRow(sessionId: string, text: string): Promise<void> {
  const backendDir = path.resolve(__dirname, "..", "..", "..", "backend");
  const python = process.env.E2E_SEED_PYTHON?.trim() || path.join(backendDir, "venv", "bin", "python");
  return new Promise((resolve, reject) => {
    // The cycle exports the slot's SUPABASE_URL; backend/.env never overrides it.
    const child = spawn(python, ["-c", PY_SAVE_TUTOR_ROW], { cwd: backendDir, timeout: 45_000 });
    let err = "";
    child.stderr.on("data", (d) => (err += d));
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`tutor-row fixture exited ${code} (${python}):\n${err}`));
    });
    child.stdin.end(JSON.stringify({ session_id: sessionId, text }));
  });
}
