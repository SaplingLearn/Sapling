// @vitest-environment jsdom
/**
 * RLS step 2e (#115): the study-room Realtime token lifecycle (no flag since
 * `realtime_rls` graduated; the fake client's own key is labelled "anon").
 *   - startRealtimeAuth: applied before anything subscribes, refreshed before
 *     it expires, not-authed reported AT expiry whatever the fetches do,
 *     transient failures retried with capped backoff, 404/503 permanent (the
 *     minted token dropped, no more fetches), refreshed on tab wake, reverted on stop, and
 *     an old lifecycle's revert never lands after a newer one's token.
 *   - acquireRealtimeAuth / useRealtimeAuth: one shared, ref-counted lifecycle
 *     (room/tab switches and StrictMode reuse it); `epoch` bumps on every
 *     (re)entry into `token`; 404/503 latches `unavailable` (REST only) and
 *     logs once; no Realtime client never requests a token.
 *   - superviseChannel: a channel that Realtime errors/closes re-joins after
 *     a token refresh, with bounded backoff.
 */
import React from "react";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  fetchJSON: vi.fn(),
}));

import { ApiError, fetchJSON } from "@/lib/api";
import {
  CHANNEL_RETRY_BASE_MS,
  CHANNEL_RETRY_MAX_MS,
  MAX_RETRY_MS,
  RECOVER_MIN_INTERVAL_MS,
  REFRESH_MARGIN_MS,
  RETRY_MS,
  acquireRealtimeAuth,
  channelRetryDelayMs,
  getRealtimeAuthSnapshot,
  recoverRealtimeAuth,
  refreshDelayMs,
  resetRealtimeAuthForTests,
  retryDelayMs,
  startRealtimeAuth,
  superviseChannel,
  useRealtimeAuth,
  type RealtimeToken,
} from "./realtimeAuth";

const T0 = Date.UTC(2026, 10, 8, 12, 0, 0);
const HOUR_S = 3600;
const HOUR_MS = HOUR_S * 1000;

function token(n: number, ttlS = HOUR_S): RealtimeToken {
  return { token: `tok-${n}`, expires_at: Math.floor(Date.now() / 1000) + ttlS };
}

/** A fake RealtimeClient: tracks the token it currently holds. */
function fakeRealtime() {
  const realtime = {
    current: "anon" as string,
    setAuth: vi.fn(async (t?: string | null) => {
      realtime.current = t ?? "anon";
    }),
  };
  return realtime;
}

function harness(fetchImpl?: () => Promise<RealtimeToken>) {
  let n = 0;
  const fetchToken = vi.fn(fetchImpl ?? (async () => token(++n)));
  const realtime = fakeRealtime();
  const onReady = vi.fn();
  const onFail = vi.fn();
  const onUnavailable = vi.fn();
  const life = startRealtimeAuth(realtime, { fetchToken, onReady, onFail, onUnavailable });
  return { fetchToken, realtime, setAuth: realtime.setAuth, onReady, onFail, onUnavailable, life };
}

/** Let the awaited fetch + queued setAuth chain settle. */
async function flush() {
  for (let i = 0; i < 20; i++) await Promise.resolve();
}

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
  document.dispatchEvent(new Event("visibilitychange"));
}

const httpError = (status: number) => new ApiError(`HTTP ${status}`, status);

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(T0);
  resetRealtimeAuthForTests();
});

afterEach(() => {
  resetRealtimeAuthForTests();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.mocked(fetchJSON).mockReset();
});

describe("delays", () => {
  it("refreshes REFRESH_MARGIN_MS before expiry", () => {
    expect(refreshDelayMs(T0 / 1000 + HOUR_S, T0)).toBe(HOUR_MS - REFRESH_MARGIN_MS);
  });

  it("never schedules a refresh in the past (expired or skewed token)", () => {
    expect(refreshDelayMs(T0 / 1000 - 10, T0)).toBe(5_000);
  });

  it("transient retries double from 30 s and cap", () => {
    expect([0, 1, 2, 3, 4, 9].map(retryDelayMs)).toEqual([
      RETRY_MS, 2 * RETRY_MS, 4 * RETRY_MS, 8 * RETRY_MS, MAX_RETRY_MS, MAX_RETRY_MS,
    ]);
  });

  it("channel re-joins double from 1 s and cap", () => {
    expect([0, 1, 2, 5, 20].map(channelRetryDelayMs)).toEqual([
      CHANNEL_RETRY_BASE_MS, 2 * CHANNEL_RETRY_BASE_MS, 4 * CHANNEL_RETRY_BASE_MS,
      CHANNEL_RETRY_MAX_MS, CHANNEL_RETRY_MAX_MS,
    ]);
  });
});

describe("startRealtimeAuth", () => {
  it("applies the minted token, then reports ready", async () => {
    const h = harness();
    await flush();
    expect(h.setAuth).toHaveBeenCalledWith("tok-1");
    expect(h.onReady).toHaveBeenCalledTimes(1);
    expect(h.onFail).not.toHaveBeenCalled();
    h.life.stop();
  });

  it("re-fetches and re-applies before expiry", async () => {
    const h = harness();
    await flush();
    await vi.advanceTimersByTimeAsync(HOUR_MS - REFRESH_MARGIN_MS - 1);
    expect(h.fetchToken).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await flush();
    expect(h.fetchToken).toHaveBeenCalledTimes(2);
    expect(h.setAuth).toHaveBeenLastCalledWith("tok-2");
    expect(h.onReady).toHaveBeenCalledTimes(2);
    expect(h.onFail).not.toHaveBeenCalled();
    h.life.stop();
  });

  it("a failed first fetch reports failure and retries after RETRY_MS", async () => {
    let calls = 0;
    const h = harness(async () => {
      calls += 1;
      if (calls === 1) throw httpError(500);
      return token(calls);
    });
    await flush();
    expect(h.onFail).toHaveBeenCalledTimes(1);
    expect(h.setAuth).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(RETRY_MS);
    await flush();
    expect(h.setAuth).toHaveBeenCalledWith("tok-2");
    expect(h.onReady).toHaveBeenCalledTimes(1);
    h.life.stop();
  });

  it("transient failures (network, 5xx other than 503) back off and cap", async () => {
    const errors = [new TypeError("Failed to fetch"), httpError(500), httpError(502), httpError(504), httpError(500), httpError(500)];
    let calls = 0;
    const h = harness(async () => {
      const e = errors[calls++];
      if (e) throw e;
      return token(calls);
    });
    await flush();
    const expected = [RETRY_MS, 2 * RETRY_MS, 4 * RETRY_MS, 8 * RETRY_MS, MAX_RETRY_MS, MAX_RETRY_MS];
    for (let i = 0; i < expected.length; i++) {
      expect(h.fetchToken).toHaveBeenCalledTimes(i + 1);
      await vi.advanceTimersByTimeAsync(expected[i] - 1);
      expect(h.fetchToken).toHaveBeenCalledTimes(i + 1);
      await vi.advanceTimersByTimeAsync(1);
      await flush();
    }
    expect(h.fetchToken).toHaveBeenCalledTimes(7);
    expect(h.setAuth).toHaveBeenLastCalledWith("tok-7");
    expect(h.onUnavailable).not.toHaveBeenCalled();
    h.life.stop();
  });

  it("a failed refresh keeps the still-valid token, then reports not-authed AT expiry", async () => {
    let calls = 0;
    const h = harness(async () => {
      calls += 1;
      if (calls >= 2) throw new TypeError("network");
      return token(calls);
    });
    await flush();
    await vi.advanceTimersByTimeAsync(HOUR_MS - REFRESH_MARGIN_MS);
    await flush();
    expect(h.fetchToken).toHaveBeenCalledTimes(2);
    expect(h.onFail).not.toHaveBeenCalled();
    // Retries at +30 s and +60 s also fail; still inside the token's life.
    await vi.advanceTimersByTimeAsync(REFRESH_MARGIN_MS - 1);
    expect(h.onFail).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(h.onFail).toHaveBeenCalledTimes(1);
    h.life.stop();
  });

  it("reports not-authed at expiresAtMs even while a refresh hangs, and ready again on a later token", async () => {
    let calls = 0;
    let release!: (t: RealtimeToken) => void;
    const h = harness(() => {
      calls += 1;
      if (calls === 1) return Promise.resolve(token(1));
      return new Promise<RealtimeToken>((r) => { release = r; });
    });
    await flush();
    expect(h.onReady).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(HOUR_MS - REFRESH_MARGIN_MS);
    expect(h.fetchToken).toHaveBeenCalledTimes(2); // refresh in flight, hanging
    await vi.advanceTimersByTimeAsync(REFRESH_MARGIN_MS);
    expect(h.onFail).toHaveBeenCalledTimes(1);
    release(token(2));
    await flush();
    expect(h.setAuth).toHaveBeenLastCalledWith("tok-2");
    expect(h.onReady).toHaveBeenCalledTimes(2);
    h.life.stop();
  });

  it.each([404, 503])("HTTP %i is permanent: minted token dropped, no more fetches", async (status) => {
    const h = harness(async () => { throw httpError(status); });
    await flush();
    expect(h.onUnavailable).toHaveBeenCalledWith(status);
    expect(h.setAuth).toHaveBeenCalledWith();
    expect(h.realtime.current).toBe("anon");
    await vi.advanceTimersByTimeAsync(24 * HOUR_MS);
    setVisibility("visible");
    await flush();
    expect(h.fetchToken).toHaveBeenCalledTimes(1);
    expect(h.onFail).not.toHaveBeenCalled();
    await h.life.recover();
    expect(h.fetchToken).toHaveBeenCalledTimes(1);
    h.life.stop();
  });

  it("a 404 at refresh drops an applied token", async () => {
    let calls = 0;
    const h = harness(async () => {
      calls += 1;
      if (calls === 2) throw httpError(404);
      return token(calls);
    });
    await flush();
    expect(h.realtime.current).toBe("tok-1");
    await vi.advanceTimersByTimeAsync(HOUR_MS - REFRESH_MARGIN_MS);
    await flush();
    expect(h.realtime.current).toBe("anon");
    expect(h.onUnavailable).toHaveBeenCalledWith(404);
    // The expiry timer is cancelled with everything else.
    await vi.advanceTimersByTimeAsync(HOUR_MS);
    expect(h.onFail).not.toHaveBeenCalled();
    h.life.stop();
  });

  it("refreshes at once when a sleeping tab wakes past its refresh point", async () => {
    const h = harness();
    await flush();
    setVisibility("hidden");
    vi.setSystemTime(T0 + HOUR_MS - REFRESH_MARGIN_MS + 1);
    setVisibility("visible");
    await vi.advanceTimersByTimeAsync(0);
    await flush();
    expect(h.fetchToken).toHaveBeenCalledTimes(2);
    expect(h.setAuth).toHaveBeenLastCalledWith("tok-2");
    h.life.stop();
  });

  it("a wake past expiry reports not-authed at once, then ready on the new token", async () => {
    const h = harness();
    await flush();
    setVisibility("hidden");
    vi.setSystemTime(T0 + 2 * HOUR_MS);
    setVisibility("visible");
    expect(h.onFail).toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(0);
    await flush();
    expect(h.setAuth).toHaveBeenLastCalledWith("tok-2");
    expect(h.onReady).toHaveBeenCalledTimes(2);
    h.life.stop();
  });

  it("a wake before the refresh point does nothing", async () => {
    const h = harness();
    await flush();
    setVisibility("visible");
    await vi.advanceTimersByTimeAsync(0);
    expect(h.fetchToken).toHaveBeenCalledTimes(1);
    h.life.stop();
  });

  it("stop reverts to the client's own token and cancels refresh + expiry", async () => {
    const h = harness();
    await flush();
    h.life.stop();
    await flush();
    expect(h.setAuth).toHaveBeenLastCalledWith();
    expect(h.realtime.current).toBe("anon");
    await vi.advanceTimersByTimeAsync(2 * HOUR_MS);
    expect(h.fetchToken).toHaveBeenCalledTimes(1);
    expect(h.onReady).toHaveBeenCalledTimes(1);
    expect(h.onFail).not.toHaveBeenCalled();
  });

  it("stop during the first fetch never applies the late token", async () => {
    let release!: (t: RealtimeToken) => void;
    const h = harness(() => new Promise((r) => { release = r; }));
    h.life.stop();
    release(token(1));
    await flush();
    expect(h.setAuth).not.toHaveBeenCalledWith("tok-1");
    expect(h.onReady).not.toHaveBeenCalled();
  });

  it("an old lifecycle's slow revert never lands after a newer lifecycle's token", async () => {
    // realtime-js resolves setAuth() through the async accessToken callback:
    // model the revert as slow and the explicit token as instant.
    const realtime = {
      current: "anon",
      setAuth: vi.fn(async (t?: string | null) => {
        if (!t) await new Promise((r) => setTimeout(r, 50));
        realtime.current = t ?? "anon";
      }),
    };
    const noop = { onReady: () => {}, onFail: () => {} };
    const a = startRealtimeAuth(realtime, { ...noop, fetchToken: async () => ({ ...token(1), token: "tok-A" }) });
    await flush();
    expect(realtime.current).toBe("tok-A");
    a.stop(); // revert starts (slow)
    await flush();
    const b = startRealtimeAuth(realtime, { ...noop, fetchToken: async () => ({ ...token(2), token: "tok-B" }) });
    await vi.advanceTimersByTimeAsync(100);
    await flush();
    expect(realtime.current).toBe("tok-B");
    b.stop();
  });

  it("a stopped lifecycle's queued revert is skipped once a newer one owns the client", async () => {
    const h = harness();
    await flush();
    const before = h.setAuth.mock.calls.length;
    h.life.stop();
    const b = startRealtimeAuth(h.realtime, {
      onReady: () => {}, onFail: () => {}, fetchToken: async () => ({ ...token(9), token: "tok-B" }),
    });
    await flush();
    expect(h.setAuth.mock.calls.slice(before)).toEqual([["tok-B"]]);
    expect(h.realtime.current).toBe("tok-B");
    b.stop();
  });

  it("recover re-mints only when the applied token is not fresh, sharing one in-flight fetch", async () => {
    const h = harness();
    await flush();
    await h.life.recover();
    expect(h.fetchToken).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(RECOVER_MIN_INTERVAL_MS);
    const r1 = h.life.recover();
    const r2 = h.life.recover();
    await Promise.all([r1, r2]);
    expect(h.fetchToken).toHaveBeenCalledTimes(2);
    expect(h.setAuth).toHaveBeenLastCalledWith("tok-2");
    h.life.stop();
  });
});

describe("acquireRealtimeAuth (shared, ref-counted)", () => {
  it("two consumers share one lifecycle; only the last release reverts", async () => {
    const realtime = fakeRealtime();
    const fetchToken = vi.fn(async () => token(1));
    const releaseA = acquireRealtimeAuth(realtime, { fetchToken });
    const releaseB = acquireRealtimeAuth(realtime, { fetchToken });
    await flush();
    expect(fetchToken).toHaveBeenCalledTimes(1);
    expect(getRealtimeAuthSnapshot().mode).toBe("token");
    releaseA();
    await vi.advanceTimersByTimeAsync(10);
    await flush();
    expect(realtime.current).toBe("tok-1");
    releaseB();
    await vi.advanceTimersByTimeAsync(10);
    await flush();
    expect(realtime.current).toBe("anon");
    expect(getRealtimeAuthSnapshot().mode).toBe("off");
  });

  it("release + immediate re-acquire (StrictMode, consumer swap) keeps the token, no re-mint", async () => {
    const realtime = fakeRealtime();
    const fetchToken = vi.fn(async () => token(1));
    const release1 = acquireRealtimeAuth(realtime, { fetchToken });
    await flush();
    release1();
    const release2 = acquireRealtimeAuth(realtime, { fetchToken });
    await vi.advanceTimersByTimeAsync(10);
    await flush();
    expect(fetchToken).toHaveBeenCalledTimes(1);
    expect(realtime.setAuth).toHaveBeenCalledTimes(1);
    expect(realtime.current).toBe("tok-1");
    release2();
  });

  it("epoch bumps each time the token is (re)applied after a gap, not on a routine refresh", async () => {
    let calls = 0;
    const realtime = fakeRealtime();
    const fetchToken = vi.fn(async () => {
      calls += 1;
      // The second refresh and its retries (+30 s, +90 s, +210 s) fail; the
      // next retry (+450 s) lands after the token expired (+300 s).
      if (calls >= 3 && calls <= 6) throw new TypeError("network");
      return token(calls);
    });
    const release = acquireRealtimeAuth(realtime, { fetchToken });
    expect(getRealtimeAuthSnapshot().mode).toBe("pending");
    await flush();
    const first = getRealtimeAuthSnapshot();
    expect(first.mode).toBe("token");
    // Routine refresh: token stays, epoch unchanged (realtime-js pushes the
    // new token to joined channels itself).
    await vi.advanceTimersByTimeAsync(HOUR_MS - REFRESH_MARGIN_MS);
    await flush();
    expect(realtime.current).toBe("tok-2");
    expect(getRealtimeAuthSnapshot()).toBe(first);
    // Next refresh fails; the token expires -> pending.
    await vi.advanceTimersByTimeAsync(HOUR_MS - REFRESH_MARGIN_MS);
    await flush();
    expect(getRealtimeAuthSnapshot().mode).toBe("token");
    await vi.advanceTimersByTimeAsync(REFRESH_MARGIN_MS);
    expect(getRealtimeAuthSnapshot().mode).toBe("pending");
    // The backed-off retry lands: token again, with a NEW epoch.
    await vi.advanceTimersByTimeAsync(150_000);
    await flush();
    expect(fetchToken).toHaveBeenCalledTimes(7);
    expect(getRealtimeAuthSnapshot()).toEqual({ mode: "token", epoch: first.epoch + 1 });
    release();
  });

  it("404/503 latches unavailable for the session and logs once", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const realtime = fakeRealtime();
    const fetchToken = vi.fn(async () => { throw httpError(503); });
    const release = acquireRealtimeAuth(realtime, { fetchToken });
    await flush();
    expect(getRealtimeAuthSnapshot().mode).toBe("unavailable");
    release();
    await vi.advanceTimersByTimeAsync(10);
    const again = acquireRealtimeAuth(realtime, { fetchToken });
    expect(getRealtimeAuthSnapshot().mode).toBe("unavailable");
    await vi.advanceTimersByTimeAsync(HOUR_MS);
    expect(fetchToken).toHaveBeenCalledTimes(1);
    expect(warn).toHaveBeenCalledTimes(1);
    expect(String(warn.mock.calls[0][0])).toContain("HTTP 503");
    expect(String(warn.mock.calls[0][0])).toContain("REST");
    again();
  });

  it("recoverRealtimeAuth asks the shared lifecycle for a fresh token", async () => {
    const realtime = fakeRealtime();
    let n = 0;
    const fetchToken = vi.fn(async () => token(++n));
    const release = acquireRealtimeAuth(realtime, { fetchToken });
    await flush();
    await vi.advanceTimersByTimeAsync(RECOVER_MIN_INTERVAL_MS);
    await recoverRealtimeAuth();
    expect(fetchToken).toHaveBeenCalledTimes(2);
    expect(realtime.current).toBe("tok-2");
    release();
  });
});

describe("useRealtimeAuth", () => {
  const realtime = fakeRealtime();
  const getRealtime = () => realtime;
  const noRealtime = () => null;

  beforeEach(() => {
    realtime.setAuth.mockClear();
    realtime.current = "anon";
  });

  it("no Realtime client: never requests a token or touches setAuth", async () => {
    const { result } = renderHook(() => useRealtimeAuth(noRealtime));
    await act(async () => { await vi.advanceTimersByTimeAsync(HOUR_MS); });
    expect(fetchJSON).not.toHaveBeenCalled();
    expect(realtime.setAuth).not.toHaveBeenCalled();
    expect(result.current.mode).toBe("off");
  });

  it("fetches /api/auth/realtime-token once (StrictMode too) and reports token", async () => {
    vi.mocked(fetchJSON).mockImplementation(async () => token(1) as never);
    const { result, unmount } = renderHook(() => useRealtimeAuth(getRealtime), {
      wrapper: ({ children }) => <React.StrictMode>{children}</React.StrictMode>,
    });
    await act(async () => { await flush(); });
    expect(fetchJSON).toHaveBeenCalledTimes(1);
    expect(fetchJSON).toHaveBeenCalledWith("/api/auth/realtime-token");
    expect(result.current.mode).toBe("token");
    expect(realtime.current).toBe("tok-1");
    unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(10); await flush(); });
    expect(realtime.current).toBe("anon");
  });
});

/** A fake realtime-js channel: the test drives its subscribe statuses. */
function fakeChannelFactory() {
  const channels: { topic: string; status: (s: string) => void; removed: boolean }[] = [];
  const create = vi.fn(() => {
    const entry = { topic: "room:r1", status: (s: string) => { void s; }, removed: false };
    const channel = {
      subscribe(cb: (s: string) => void) {
        entry.status = cb;
        return channel;
      },
      entry,
    };
    channels.push(entry);
    return channel;
  });
  const remove = vi.fn(async (c: { entry: { removed: boolean } }) => {
    c.entry.removed = true;
    return "ok";
  });
  return { channels, create, remove };
}

describe("superviseChannel", () => {
  it("joins at once and reports SUBSCRIBED", () => {
    const f = fakeChannelFactory();
    const onSubscribed = vi.fn();
    const stop = superviseChannel({ topic: "room:r1", create: f.create, remove: f.remove, onSubscribed });
    expect(f.create).toHaveBeenCalledTimes(1);
    f.channels[0].status("SUBSCRIBED");
    expect(onSubscribed).toHaveBeenCalledTimes(1);
    stop();
    expect(f.channels[0].removed).toBe(true);
  });

  it.each(["CHANNEL_ERROR", "TIMED_OUT", "CLOSED"])(
    "%s: removes the channel, recovers the token, re-joins only after both recovery and backoff",
    async (status) => {
      const f = fakeChannelFactory();
      let finishRecover!: () => void;
      const onLost = vi.fn(() => new Promise<void>((r) => { finishRecover = r; }));
      const stop = superviseChannel({ topic: "room:r1", create: f.create, remove: f.remove, onLost });
      f.channels[0].status(status);
      await flush();
      expect(f.channels[0].removed).toBe(true);
      expect(onLost).toHaveBeenCalledWith(status);
      await vi.advanceTimersByTimeAsync(CHANNEL_RETRY_MAX_MS);
      expect(f.create).toHaveBeenCalledTimes(1); // still waiting on the fresh token
      finishRecover();
      await flush();
      expect(f.create).toHaveBeenCalledTimes(2);
      stop();
    },
  );

  it("backs off 1 s, 2 s, 4 s ... capped, and resets on SUBSCRIBED", async () => {
    const f = fakeChannelFactory();
    const stop = superviseChannel({ topic: "room:r1", create: f.create, remove: f.remove });
    const waits = [1, 2, 4, 8, 16, 30, 30].map((s) => s * 1000);
    for (let i = 0; i < waits.length; i++) {
      f.channels[i].status("CHANNEL_ERROR");
      await flush();
      await vi.advanceTimersByTimeAsync(waits[i] - 1);
      expect(f.create).toHaveBeenCalledTimes(i + 1);
      await vi.advanceTimersByTimeAsync(1);
      await flush();
      expect(f.create).toHaveBeenCalledTimes(i + 2);
    }
    const last = f.channels[f.channels.length - 1];
    last.status("SUBSCRIBED");
    last.status("CLOSED");
    await flush();
    await vi.advanceTimersByTimeAsync(CHANNEL_RETRY_BASE_MS);
    await flush();
    expect(f.create).toHaveBeenCalledTimes(waits.length + 2);
    stop();
  });

  it("stop cancels a pending re-join and ignores late statuses", async () => {
    const f = fakeChannelFactory();
    const onSubscribed = vi.fn();
    const stop = superviseChannel({ topic: "room:r1", create: f.create, remove: f.remove, onSubscribed });
    f.channels[0].status("CLOSED");
    stop();
    await vi.advanceTimersByTimeAsync(CHANNEL_RETRY_MAX_MS);
    await flush();
    expect(f.create).toHaveBeenCalledTimes(1);
    f.channels[0].status("SUBSCRIBED");
    expect(onSubscribed).not.toHaveBeenCalled();
  });

  it("a new supervisor on the same topic joins only after the old channel's removal finishes", async () => {
    let finishRemoval!: () => void;
    const create = vi.fn(() => ({ subscribe: () => undefined }));
    const stop1 = superviseChannel({
      topic: "room:r9", create, remove: () => new Promise<void>((r) => { finishRemoval = r; }),
    });
    stop1();
    const stop2 = superviseChannel({ topic: "room:r9", create, remove: () => undefined });
    await flush();
    expect(create).toHaveBeenCalledTimes(1);
    finishRemoval();
    await flush();
    expect(create).toHaveBeenCalledTimes(2);
    stop2();
  });

  it("end to end: Realtime closes the channel on an expired token; it re-joins on the fresh token", async () => {
    const realtime = fakeRealtime();
    let n = 0;
    const release = acquireRealtimeAuth(realtime, { fetchToken: async () => token(++n) });
    await flush();
    const joinedWith: string[] = [];
    const statuses: ((s: string) => void)[] = [];
    const stop = superviseChannel({
      topic: "room:e2e",
      create: () => {
        joinedWith.push(realtime.current);
        return { subscribe: (cb: (s: string) => void) => { statuses.push(cb); } };
      },
      remove: () => undefined,
      onLost: () => recoverRealtimeAuth(),
    });
    statuses[0]("SUBSCRIBED");
    // Server-side the token is gone (clock skew / sleeping tab): CLOSED.
    await vi.advanceTimersByTimeAsync(RECOVER_MIN_INTERVAL_MS);
    statuses[0]("CLOSED");
    await vi.advanceTimersByTimeAsync(CHANNEL_RETRY_BASE_MS);
    await flush();
    expect(joinedWith).toEqual(["tok-1", "tok-2"]);
    stop();
    release();
  });
});
