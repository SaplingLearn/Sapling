/**
 * One id per student turn (#761/#762), sent UNCHANGED on the stream, its
 * JSON fallback and any Retry of that turn: the backend dedupes the turn's
 * writes on it and replays an already-persisted reply (`replayed: true`)
 * instead of running the turn twice. Must match `^[A-Za-z0-9_\-]{8,128}$`.
 * Re-exported by lib/api.ts, where its callers import it.
 */
export function newTurnId(): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  if (c?.randomUUID) return c.randomUUID();
  return `t${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
}
