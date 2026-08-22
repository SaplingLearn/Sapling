/**
 * Session persistence — the half of leave-and-resume the backend can't do.
 *
 * `GET /api/quiz/attempts/{id}` restores which questions exist and which were
 * answered, but the resume payload is keyless and carries no `correct_index`
 * and no explanation, and the server has never heard of the session's scope,
 * queue, feedback mode or origin. Those live here, in localStorage, keyed by
 * nothing but "the one quiz this browser is in the middle of".
 *
 * Every read and write is wrapped: a private window, a full quota or a
 * disabled-storage browser must degrade to "no saved session", never to a
 * thrown error mid-quiz.
 */

import type { QuizSession } from "./types";

/** Max concepts in one multi-concept session — `get_recommendations`' own limit
 *  (`graph_service.py:914-945`, `limit=5`). The generation rate limit is 8/300s,
 *  so five 3-question attempts fit inside one session comfortably. */
export const QUEUE_MAX = 5;
/** Questions per attempt in a queued session (R-4). */
export const QUEUE_COUNT = 3;

export const STORAGE_KEY = "sapling_quiz_session";
export const PREFS_KEY = "sapling_quiz_prefs";
export const DISMISSED_KEY = "sapling_quiz_dismissed";

/** Cap on remembered discards, so the key can't grow without bound. */
const DISMISSED_MAX = 50;

function storage(): Storage | null {
  try {
    if (typeof window === "undefined") return null;
    return window.localStorage;
  } catch {
    return null;
  }
}

function readJson<T>(key: string): T | null {
  try {
    const raw = storage()?.getItem(key);
    if (!raw) return null;
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

function writeJson(key: string, value: unknown): void {
  try {
    storage()?.setItem(key, JSON.stringify(value));
  } catch {
    // Quota, private mode, storage disabled. Losing the resume record is a
    // downgrade, not a failure — the attempt itself is safe server-side.
  }
}

function removeKey(key: string): void {
  try {
    storage()?.removeItem(key);
  } catch {
    // See above.
  }
}

/** Cheap shape check, so a stale or hand-edited record can't crash a mount. */
function looksLikeSession(value: unknown): value is QuizSession {
  if (value === null || typeof value !== "object") return false;
  const s = value as Partial<QuizSession>;
  return typeof s.phase === "string"
    && Array.isArray(s.items)
    && typeof s.cursor === "number"
    && typeof s.source === "object"
    && s.source !== null;
}

export function saveSession(session: QuizSession): void {
  writeJson(STORAGE_KEY, session);
}

export function loadSession(): QuizSession | null {
  const parsed = readJson<unknown>(STORAGE_KEY);
  return looksLikeSession(parsed) ? parsed : null;
}

export function clearSession(): void {
  removeKey(STORAGE_KEY);
}

/**
 * Phases worth remembering. Nothing before `generating` has an attempt to come
 * back to, and once the attempt is scored the results live in memory and the
 * record is cleared — a stale `results` session would otherwise reopen a quiz
 * the student already finished.
 */
const PERSISTED_PHASES: ReadonlySet<QuizSession["phase"]> = new Set([
  "generating",
  "active",
  "answered",
  "confirm-leave",
  "submitting",
  "paused",
  "error",
]);

export function shouldPersist(session: QuizSession): boolean {
  return PERSISTED_PHASES.has(session.phase);
}

/** Save or clear, whichever this phase calls for. Called on every transition. */
export function persistSession(session: QuizSession): void {
  if (shouldPersist(session)) saveSession(session);
  else clearSession();
}

// ── Discarded attempts ─────────────────────────────────────────────────────
//
// There is no abandon endpoint (gap G4): an attempt only closes via submit or
// the 24h TTL sweep. "Discard" therefore hides the row client-side and leaves
// the server row to expire.
// TODO(#537-followup: abandon endpoint) — replace this with a real
// `POST /api/quiz/attempts/{id}/abandon` so a discard is visible on any device.

function readDismissed(): string[] {
  const parsed = readJson<unknown>(DISMISSED_KEY);
  return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === "string") : [];
}

export function dismissAttempt(id: string): void {
  if (!id) return;
  const existing = readDismissed().filter(v => v !== id);
  writeJson(DISMISSED_KEY, [id, ...existing].slice(0, DISMISSED_MAX));
}

export function isDismissed(id: string): boolean {
  return readDismissed().includes(id);
}

export function clearDismissed(): void {
  removeKey(DISMISSED_KEY);
}
