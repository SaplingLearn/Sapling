// @vitest-environment jsdom
/**
 * RLS step 2e (#115): the Realtime token lifecycle behind `realtime_rls`.
 * Applied before anything subscribes, refreshed before it expires, refreshed
 * at once when a sleeping tab wakes past its refresh point, retried after a
 * failed fetch, and reverted to the client's own (anon) token on stop.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  REFRESH_MARGIN_MS,
  RETRY_MS,
  refreshDelayMs,
  startRealtimeAuth,
  type RealtimeToken,
} from "./realtimeAuth";

const T0 = Date.UTC(2026, 10, 8, 12, 0, 0);
const HOUR_S = 3600;

function token(n: number, ttlS = HOUR_S): RealtimeToken {
  return { token: `tok-${n}`, expires_at: Math.floor(Date.now() / 1000) + ttlS };
}

function harness(fetchImpl?: () => Promise<RealtimeToken>) {
  let n = 0;
  const fetchToken = vi.fn(fetchImpl ?? (async () => token(++n)));
  const setAuth = vi.fn(async (token?: string | null) => { void token; });
  const onReady = vi.fn();
  const onFail = vi.fn();
  const stop = startRealtimeAuth({ setAuth }, { fetchToken, onReady, onFail });
  return { fetchToken, setAuth, onReady, onFail, stop };
}

/** Let the awaited fetch + setAuth chain settle. */
async function flush() {
  for (let i = 0; i < 5; i++) await Promise.resolve();
}

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
  document.dispatchEvent(new Event("visibilitychange"));
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(T0);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("refreshDelayMs", () => {
  it("refreshes REFRESH_MARGIN_MS before expiry", () => {
    expect(refreshDelayMs(T0 / 1000 + HOUR_S, T0)).toBe(HOUR_S * 1000 - REFRESH_MARGIN_MS);
  });

  it("never schedules in the past (expired or skewed token)", () => {
    expect(refreshDelayMs(T0 / 1000 - 10, T0)).toBe(5_000);
  });
});

describe("startRealtimeAuth", () => {
  it("applies the minted token, then reports ready", async () => {
    const h = harness();
    await flush();
    expect(h.setAuth).toHaveBeenCalledWith("tok-1");
    expect(h.onReady).toHaveBeenCalledTimes(1);
    expect(h.onFail).not.toHaveBeenCalled();
    h.stop();
  });

  it("re-fetches and re-applies before expiry", async () => {
    const h = harness();
    await flush();
    await vi.advanceTimersByTimeAsync(HOUR_S * 1000 - REFRESH_MARGIN_MS - 1);
    expect(h.fetchToken).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await flush();
    expect(h.fetchToken).toHaveBeenCalledTimes(2);
    expect(h.setAuth).toHaveBeenLastCalledWith("tok-2");
    expect(h.onReady).toHaveBeenCalledTimes(2);
    h.stop();
  });

  it("a failed first fetch reports failure and retries", async () => {
    let calls = 0;
    const h = harness(async () => {
      calls += 1;
      if (calls === 1) throw new Error("503");
      return token(calls);
    });
    await flush();
    expect(h.onFail).toHaveBeenCalledTimes(1);
    expect(h.setAuth).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(RETRY_MS);
    await flush();
    expect(h.setAuth).toHaveBeenCalledWith("tok-2");
    expect(h.onReady).toHaveBeenCalledTimes(1);
    h.stop();
  });

  it("a failed refresh keeps the still-valid token (no failure yet)", async () => {
    let calls = 0;
    const h = harness(async () => {
      calls += 1;
      if (calls === 2) throw new Error("network");
      return token(calls);
    });
    await flush();
    await vi.advanceTimersByTimeAsync(HOUR_S * 1000 - REFRESH_MARGIN_MS);
    await flush();
    expect(h.fetchToken).toHaveBeenCalledTimes(2);
    expect(h.onFail).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(RETRY_MS);
    await flush();
    expect(h.setAuth).toHaveBeenLastCalledWith("tok-3");
    h.stop();
  });

  it("refreshes at once when a sleeping tab wakes past its refresh point", async () => {
    const h = harness();
    await flush();
    setVisibility("hidden");
    // The tab slept: the clock moved but no timer fired.
    vi.setSystemTime(T0 + HOUR_S * 1000);
    setVisibility("visible");
    await vi.advanceTimersByTimeAsync(0);
    await flush();
    expect(h.fetchToken).toHaveBeenCalledTimes(2);
    expect(h.setAuth).toHaveBeenLastCalledWith("tok-2");
    h.stop();
  });

  it("a wake before the refresh point does nothing", async () => {
    const h = harness();
    await flush();
    setVisibility("visible");
    await vi.advanceTimersByTimeAsync(0);
    expect(h.fetchToken).toHaveBeenCalledTimes(1);
    h.stop();
  });

  it("stop reverts to the client's own token and cancels the refresh", async () => {
    const h = harness();
    await flush();
    h.stop();
    expect(h.setAuth).toHaveBeenLastCalledWith();
    await vi.advanceTimersByTimeAsync(2 * HOUR_S * 1000);
    expect(h.fetchToken).toHaveBeenCalledTimes(1);
    expect(h.onReady).toHaveBeenCalledTimes(1);
  });

  it("stop during the first fetch never applies the late token", async () => {
    let release!: (t: RealtimeToken) => void;
    const h = harness(() => new Promise((r) => { release = r; }));
    h.stop();
    release(token(1));
    await flush();
    expect(h.setAuth).not.toHaveBeenCalledWith("tok-1");
    expect(h.onReady).not.toHaveBeenCalled();
  });
});
