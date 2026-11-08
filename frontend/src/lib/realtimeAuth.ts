import { fetchJSON } from "@/lib/api";

/**
 * RLS step 2e (#115, docs/security/realtime-jwt-bridge-design.md): behind the
 * `realtime_rls` flag, the study-room Realtime subscription authenticates with
 * a backend-minted token instead of the public anon key. The token's issuer
 * (`sapling-realtime`) is trusted by exactly one policy, SELECT on
 * room_messages for members of the message's room, so Supabase Realtime only
 * delivers changes for rooms this student is in.
 *
 * The token lives about an hour; Realtime closes a channel whose token has
 * expired, so it is re-fetched REFRESH_MARGIN_MS before `expires_at` and
 * applied with `setAuth` again (realtime-js pushes it to joined channels).
 */
export type RealtimeToken = { token: string; expires_at: number };

/** GET /api/auth/realtime-token: 404 while the flag is off for this student,
 * 503 when the backend has no signing key. */
export function fetchRealtimeToken(): Promise<RealtimeToken> {
  return fetchJSON<RealtimeToken>("/api/auth/realtime-token");
}

/** Re-fetch this long before the token expires. */
export const REFRESH_MARGIN_MS = 5 * 60_000;
/** Wait this long after a failed fetch before trying again. */
export const RETRY_MS = 30_000;
/** Never schedule a refresh sooner than this (a clock-skewed `expires_at`). */
const MIN_REFRESH_MS = 5_000;

/** Milliseconds from `nowMs` until the token minted to expire at
 * `expiresAtSec` (unix seconds) should be refreshed. */
export function refreshDelayMs(expiresAtSec: number, nowMs: number): number {
  return Math.max(MIN_REFRESH_MS, expiresAtSec * 1000 - nowMs - REFRESH_MARGIN_MS);
}

/** The slice of supabase-js's RealtimeClient this needs. `setAuth()` with no
 * argument reverts to the client's own token (the anon key here). */
export type RealtimeAuthTarget = { setAuth(token?: string | null): Promise<void> };

export type RealtimeAuthOptions = {
  /** A token is applied (first time, and after every refresh). */
  onReady: () => void;
  /** No usable token: the fetch failed and the last token (if any) expired.
   * The caller drops to REST-only; retries continue every RETRY_MS. */
  onFail: () => void;
  fetchToken?: () => Promise<RealtimeToken>;
};

/**
 * Apply a minted Realtime token to `realtime` now, keep it fresh, and refresh
 * at once when a sleeping tab comes back past its refresh point. Returns a
 * stop function: cancels everything and reverts `realtime` to its own token.
 */
export function startRealtimeAuth(
  realtime: RealtimeAuthTarget,
  { onReady, onFail, fetchToken = fetchRealtimeToken }: RealtimeAuthOptions,
): () => void {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let expiresAtMs = 0;
  let inFlight = false;

  const schedule = (ms: number) => {
    if (timer !== undefined) clearTimeout(timer);
    timer = setTimeout(() => void tick(), ms);
  };

  const revert = () => {
    realtime.setAuth().catch(() => {});
  };

  async function tick(): Promise<void> {
    if (stopped || inFlight) return;
    inFlight = true;
    try {
      const t = await fetchToken();
      if (stopped) return;
      await realtime.setAuth(t.token);
      // stop() ran while setAuth was in flight: its revert may have landed
      // first, so revert again rather than leave this token applied.
      if (stopped) return revert();
      expiresAtMs = t.expires_at * 1000;
      onReady();
      schedule(refreshDelayMs(t.expires_at, Date.now()));
    } catch {
      if (stopped) return;
      if (Date.now() >= expiresAtMs) onFail();
      schedule(RETRY_MS);
    } finally {
      inFlight = false;
    }
  }

  // Timers do not run in a sleeping tab: on wake, refresh now if due.
  const onVisible = () => {
    if (document.visibilityState !== "visible") return;
    if (Date.now() >= expiresAtMs - REFRESH_MARGIN_MS) schedule(0);
  };
  document.addEventListener("visibilitychange", onVisible);

  void tick();

  return () => {
    if (stopped) return;
    stopped = true;
    if (timer !== undefined) clearTimeout(timer);
    document.removeEventListener("visibilitychange", onVisible);
    revert();
  };
}
