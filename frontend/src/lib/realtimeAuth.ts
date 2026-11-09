import { useEffect, useSyncExternalStore } from "react";

import { fetchJSON } from "@/lib/api";
import { statusOf } from "@/lib/errorMessage";

/**
 * RLS step 2e (#115, docs/security/realtime-jwt-bridge-design.md): behind the
 * `realtime_rls` flag, the study-room Realtime subscription authenticates with
 * a backend-minted token instead of the public anon key. The token's issuer
 * (`sapling-realtime`) is trusted by exactly one policy, SELECT on
 * room_messages for members of the message's room, so Supabase Realtime only
 * delivers changes for rooms this student is in.
 *
 * Three layers, bottom up:
 *   - `startRealtimeAuth`: one token lifecycle (fetch, apply with `setAuth`,
 *     refresh before expiry, report expiry, back off on transient failures,
 *     give up on permanent ones).
 *   - `acquireRealtimeAuth` / `useRealtimeAuth`: ONE shared, ref-counted
 *     lifecycle per page, because `setAuth` is global to the Realtime client:
 *     a room or tab switch must not revert to anon and re-mint, and only the
 *     last release reverts.
 *   - `superviseChannel`: a channel that re-joins (bounded backoff, after a
 *     token refresh) when Realtime errors, times out or closes it, which it
 *     does once the token it joined with expires.
 */
export type RealtimeToken = { token: string; expires_at: number };

/** GET /api/auth/realtime-token: 404 while the flag is off for this student,
 * 503 when the backend has no signing key. */
export function fetchRealtimeToken(): Promise<RealtimeToken> {
  return fetchJSON<RealtimeToken>("/api/auth/realtime-token");
}

/** Re-fetch this long before the token expires. */
export const REFRESH_MARGIN_MS = 5 * 60_000;
/** First wait after a transient fetch failure; doubles per failure... */
export const RETRY_MS = 30_000;
/** ...up to this. */
export const MAX_RETRY_MS = 5 * 60_000;
/** A channel-driven `recover()` re-mints only when the applied token is at
 * least this old: a channel that keeps failing for some other reason must not
 * turn into a token-minting loop. */
export const RECOVER_MIN_INTERVAL_MS = 30_000;
/** Never schedule a refresh sooner than this (a clock-skewed `expires_at`). */
const MIN_REFRESH_MS = 5_000;
/** Statuses retrying cannot fix in this page session: 404 = the flag resolved
 * off server-side, 503 = the backend has no signing key. */
const PERMANENT_STATUSES = new Set([404, 503]);

/** Milliseconds from `nowMs` until the token minted to expire at
 * `expiresAtSec` (unix seconds) should be refreshed. */
export function refreshDelayMs(expiresAtSec: number, nowMs: number): number {
  return Math.max(MIN_REFRESH_MS, expiresAtSec * 1000 - nowMs - REFRESH_MARGIN_MS);
}

/** Wait after the `failures`-th consecutive transient failure (0-based). */
export function retryDelayMs(failures: number): number {
  return Math.min(MAX_RETRY_MS, RETRY_MS * 2 ** Math.max(0, failures));
}

/** The slice of supabase-js's RealtimeClient this needs. `setAuth()` with no
 * argument reverts to the client's own token (the anon key here). */
export type RealtimeAuthTarget = { setAuth(token?: string | null): Promise<void> };

/**
 * Every `setAuth` on one Realtime client goes through ONE promise chain and
 * runs only if its lifecycle still owns the client when its turn comes.
 * realtime-js resolves `setAuth()` (the revert) through the client's async
 * accessToken callback, so without the chain an old lifecycle's revert could
 * land AFTER a newer lifecycle's `setAuth(token)` and silently put the page
 * back on the anon key.
 */
type AuthSlot = { chain: Promise<unknown>; owner: symbol | null };
const slots = new WeakMap<RealtimeAuthTarget, AuthSlot>();

function slotFor(target: RealtimeAuthTarget): AuthSlot {
  let slot = slots.get(target);
  if (!slot) {
    slot = { chain: Promise.resolve(), owner: null };
    slots.set(target, slot);
  }
  return slot;
}

function enqueue(slot: AuthSlot, run: () => Promise<boolean>): Promise<boolean> {
  const next = slot.chain.then(run, run).catch(() => false);
  slot.chain = next;
  return next;
}

export type RealtimeAuthOptions = {
  /** A token is applied (first time, and after every refresh). */
  onReady: () => void;
  /** Not authenticated: the applied token reached `expires_at` (whatever the
   * fetches are doing), or a fetch failed with no unexpired token. Realtime
   * closes channels on an expired token; refreshes keep going and the next
   * success calls `onReady` again. */
  onFail: () => void;
  /** Permanent failure (404/503): retries stopped and the client is back on
   * its own (anon) token for the rest of this lifecycle. */
  onUnavailable?: (status: number) => void;
  fetchToken?: () => Promise<RealtimeToken>;
};

export type RealtimeAuthLifecycle = {
  /** Cancel everything and revert the client to its own token, unless a newer
   * lifecycle has claimed it since. */
  stop: () => void;
  /** A channel was lost: refresh the token now unless the applied one is
   * fresh (RECOVER_MIN_INTERVAL_MS). Resolves once that attempt settles. */
  recover: () => Promise<void>;
};

/**
 * Apply a minted Realtime token to `realtime` now, keep it fresh, and refresh
 * at once when a sleeping tab comes back past its refresh point.
 */
export function startRealtimeAuth(
  realtime: RealtimeAuthTarget,
  { onReady, onFail, onUnavailable, fetchToken = fetchRealtimeToken }: RealtimeAuthOptions,
): RealtimeAuthLifecycle {
  const me = Symbol("realtime-auth");
  const slot = slotFor(realtime);
  slot.owner = me;

  let stopped = false;
  let unavailable = false;
  let refreshTimer: ReturnType<typeof setTimeout> | undefined;
  let expiryTimer: ReturnType<typeof setTimeout> | undefined;
  let expiresAtMs = 0;
  let appliedAtMs = 0;
  let failures = 0;
  let inFlight: Promise<void> | null = null;

  const live = () => !stopped && !unavailable;

  const apply = (token: string | null) =>
    enqueue(slot, async () => {
      if (slot.owner !== me || !live()) return false;
      if (token === null) await realtime.setAuth();
      else await realtime.setAuth(token);
      return true;
    });

  const schedule = (ms: number) => {
    if (refreshTimer !== undefined) clearTimeout(refreshTimer);
    refreshTimer = setTimeout(() => void refresh(), ms);
  };

  // Report not-authed AT expiry, independent of how the fetches are going: a
  // slow or failing refresh must not leave channels "joined" on a token
  // Realtime has already rejected.
  const armExpiry = () => {
    if (expiryTimer !== undefined) clearTimeout(expiryTimer);
    expiryTimer = setTimeout(() => {
      expiryTimer = undefined;
      if (live()) onFail();
    }, Math.max(0, expiresAtMs - Date.now()));
  };

  const clearTimers = () => {
    if (refreshTimer !== undefined) clearTimeout(refreshTimer);
    if (expiryTimer !== undefined) clearTimeout(expiryTimer);
    refreshTimer = expiryTimer = undefined;
  };

  async function attempt(): Promise<void> {
    let t: RealtimeToken;
    try {
      t = await fetchToken();
    } catch (err) {
      if (!live()) return;
      const status = statusOf(err);
      if (status !== undefined && PERMANENT_STATUSES.has(status)) {
        // Back to the client's own token first (a still-valid minted one
        // must not outlive the decision), then stop for good.
        await apply(null);
        if (!live()) return;
        unavailable = true;
        clearTimers();
        document.removeEventListener("visibilitychange", onVisible);
        onUnavailable?.(status);
        return;
      }
      if (Date.now() >= expiresAtMs) onFail();
      schedule(retryDelayMs(failures++));
      return;
    }
    if (!live()) return;
    if (!(await apply(t.token)) || !live()) return;
    failures = 0;
    appliedAtMs = Date.now();
    expiresAtMs = t.expires_at * 1000;
    armExpiry();
    onReady();
    schedule(refreshDelayMs(t.expires_at, Date.now()));
  }

  function refresh(): Promise<void> {
    if (!live()) return Promise.resolve();
    if (!inFlight) {
      inFlight = attempt().finally(() => {
        inFlight = null;
      });
    }
    return inFlight;
  }

  // Timers do not run in a sleeping tab: on wake, report an expired token at
  // once and refresh now if due.
  function onVisible() {
    if (document.visibilityState !== "visible" || !live()) return;
    const now = Date.now();
    if (expiresAtMs > 0 && now >= expiresAtMs) onFail();
    if (now >= expiresAtMs - REFRESH_MARGIN_MS) schedule(0);
  }
  document.addEventListener("visibilitychange", onVisible);

  void refresh();

  return {
    stop() {
      if (stopped) return;
      stopped = true;
      clearTimers();
      document.removeEventListener("visibilitychange", onVisible);
      if (slot.owner !== me) return;
      slot.owner = null;
      // Runs only if no newer lifecycle claimed the client before its turn.
      void enqueue(slot, async () => {
        if (slot.owner !== null) return false;
        await realtime.setAuth();
        return true;
      });
    },
    recover() {
      if (!live()) return Promise.resolve();
      if (inFlight) return inFlight;
      const now = Date.now();
      if (now < expiresAtMs && now - appliedAtMs < RECOVER_MIN_INTERVAL_MS) return Promise.resolve();
      return refresh();
    },
  };
}

// ---------------------------------------------------------------------------
// The shared, ref-counted lifecycle.

/**
 * - `off`: nobody holds the lifecycle.
 * - `pending`: waiting for a (fresh) token; channels must not join.
 * - `token`: a minted token is applied. `epoch` increments every time the
 *   state ENTERS `token`, so effects keyed on it re-join after an expiry even
 *   when React only ever renders the final state.
 * - `anon`: permanent 404/503, today's anon subscription for the rest of this
 *   page session (latched until reload).
 */
export type RealtimeAuthMode = "off" | "pending" | "token" | "anon";
export type RealtimeAuthSnapshot = { mode: RealtimeAuthMode; epoch: number };

/** Wait this long after the last release before stopping, so a StrictMode
 * remount (or a same-commit consumer swap) reuses the lifecycle. */
const RELEASE_GRACE_MS = 0;

type Shared = {
  refs: number;
  lifecycle: RealtimeAuthLifecycle | null;
  stopTimer?: ReturnType<typeof setTimeout>;
};

let shared: Shared | null = null;
let snapshot: RealtimeAuthSnapshot = { mode: "off", epoch: 0 };
let anonForSession = false;
let warned = false;
const listeners = new Set<() => void>();

function setMode(mode: RealtimeAuthMode) {
  if (snapshot.mode === mode) return;
  snapshot = { mode, epoch: mode === "token" ? snapshot.epoch + 1 : snapshot.epoch };
  listeners.forEach((l) => l());
}

export function getRealtimeAuthSnapshot(): RealtimeAuthSnapshot {
  return snapshot;
}

export function subscribeRealtimeAuth(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Ask the shared lifecycle for a fresh token after a channel was lost. */
export function recoverRealtimeAuth(): Promise<void> {
  return shared?.lifecycle?.recover() ?? Promise.resolve();
}

/**
 * Hold the page's Realtime token lifecycle; returns the release function.
 * The first holder starts it; the last release stops it (reverting to anon).
 */
export function acquireRealtimeAuth(
  realtime: RealtimeAuthTarget,
  options: { fetchToken?: () => Promise<RealtimeToken> } = {},
): () => void {
  if (!shared) {
    const s: Shared = { refs: 0, lifecycle: null };
    shared = s;
    if (anonForSession) {
      setMode("anon");
    } else {
      setMode("pending");
      s.lifecycle = startRealtimeAuth(realtime, {
        fetchToken: options.fetchToken,
        onReady: () => { if (shared === s) setMode("token"); },
        onFail: () => { if (shared === s) setMode("pending"); },
        onUnavailable: (status) => {
          anonForSession = true;
          if (!warned) {
            warned = true;
            console.warn(
              `[realtime] minted token unavailable (HTTP ${status}); using the anon key for this session`,
            );
          }
          if (shared === s) setMode("anon");
        },
      });
    }
  }
  const s = shared;
  s.refs += 1;
  if (s.stopTimer !== undefined) {
    clearTimeout(s.stopTimer);
    s.stopTimer = undefined;
  }
  let released = false;
  return () => {
    if (released) return;
    released = true;
    s.refs -= 1;
    if (s.refs > 0) return;
    s.stopTimer = setTimeout(() => {
      s.stopTimer = undefined;
      if (s.refs > 0) return;
      s.lifecycle?.stop();
      if (shared === s) {
        shared = null;
        setMode("off");
      }
    }, RELEASE_GRACE_MS);
  };
}

/** Test-only: forget the shared lifecycle, the anon latch and the log-once. */
export function resetRealtimeAuthForTests(): void {
  if (shared?.stopTimer !== undefined) clearTimeout(shared.stopTimer);
  shared?.lifecycle?.stop();
  shared = null;
  anonForSession = false;
  warned = false;
  snapshot = { mode: "off", epoch: 0 };
  listeners.clear();
}

const OFF: RealtimeAuthSnapshot = { mode: "off", epoch: 0 };

/**
 * Hold the shared lifecycle while `enabled`. Disabled, it never fetches a
 * token or touches `setAuth`, and reports `off`. `getRealtime` must be stable.
 */
export function useRealtimeAuth(
  enabled: boolean,
  getRealtime: () => RealtimeAuthTarget | null | undefined,
): RealtimeAuthSnapshot {
  const snap = useSyncExternalStore(subscribeRealtimeAuth, getRealtimeAuthSnapshot, getRealtimeAuthSnapshot);
  useEffect(() => {
    if (!enabled) return;
    const realtime = getRealtime();
    if (!realtime) return;
    return acquireRealtimeAuth(realtime);
  }, [enabled, getRealtime]);
  return enabled ? snap : OFF;
}

// ---------------------------------------------------------------------------
// Channel supervision.

/** First re-join wait after a lost channel; doubles per consecutive loss... */
export const CHANNEL_RETRY_BASE_MS = 1_000;
/** ...up to this. */
export const CHANNEL_RETRY_MAX_MS = 30_000;
const LOST_STATUSES = new Set(["CHANNEL_ERROR", "TIMED_OUT", "CLOSED"]);

export function channelRetryDelayMs(attempt: number): number {
  return Math.min(CHANNEL_RETRY_MAX_MS, CHANNEL_RETRY_BASE_MS * 2 ** Math.max(0, attempt));
}

export type SupervisedChannel = { subscribe(callback: (status: string, err?: Error) => void): unknown };

/** In-flight removals per topic: realtime-js `channel(topic)` hands back the
 * existing (still leaving) channel until its removal has finished. */
const pendingRemovals = new Map<string, Promise<unknown>>();

/**
 * Join `create()`'s channel and keep it joined: on CHANNEL_ERROR, TIMED_OUT or
 * CLOSED the channel is removed and `onLost` runs (refresh the token); once
 * that has settled AND the backoff has elapsed, a fresh channel joins. The
 * backoff resets on SUBSCRIBED. Returns stop.
 */
export function superviseChannel<C extends SupervisedChannel>(opts: {
  topic: string;
  create: () => C;
  remove: (channel: C) => unknown;
  onSubscribed?: (channel: C) => void;
  onLost?: (status: string) => unknown;
}): () => void {
  const { topic } = opts;
  let stopped = false;
  let current: C | null = null;
  let attempt = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const removeTracked = (channel: C) => {
    let p: Promise<unknown>;
    try {
      p = Promise.resolve(opts.remove(channel)).catch(() => undefined);
    } catch {
      p = Promise.resolve();
    }
    const all = Promise.all([pendingRemovals.get(topic), p]);
    pendingRemovals.set(topic, all);
    void all.then(() => {
      if (pendingRemovals.get(topic) === all) pendingRemovals.delete(topic);
    });
  };

  const lost = (channel: C | null, status: string) => {
    current = null;
    if (channel) removeTracked(channel);
    const delay = channelRetryDelayMs(attempt++);
    const waited = new Promise<void>((resolve) => {
      timer = setTimeout(resolve, delay);
    });
    const recovered = Promise.resolve()
      .then(() => opts.onLost?.(status))
      .catch(() => undefined);
    void Promise.all([waited, recovered]).then(() => join());
  };

  const open = () => {
    if (stopped) return;
    let channel: C;
    try {
      channel = opts.create();
      current = channel;
      channel.subscribe((status) => {
        if (stopped || current !== channel) return;
        if (status === "SUBSCRIBED") {
          attempt = 0;
          opts.onSubscribed?.(channel);
          return;
        }
        if (LOST_STATUSES.has(status)) lost(channel, status);
      });
    } catch {
      // realtime-js throws on a second subscribe of a channel it still holds
      // under this topic: back off and try again like any lost channel.
      lost(current, "CHANNEL_ERROR");
    }
  };

  const join = () => {
    if (stopped) return;
    const pending = pendingRemovals.get(topic);
    if (pending) void pending.then(open);
    else open();
  };

  join();

  return () => {
    if (stopped) return;
    stopped = true;
    if (timer !== undefined) clearTimeout(timer);
    if (current) {
      removeTracked(current);
      current = null;
    }
  };
}
