// @vitest-environment jsdom
/**
 * lib/accountSettings.ts: one in-flight GET /settings per student, shared by
 * the UserProvider and the Settings screen, and every answer feeds the
 * analytics account state — so the switch and the gate never disagree.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

const fetchSettings = vi.fn();
vi.mock("./api", () => ({ fetchSettings: (...a: unknown[]) => fetchSettings(...a) }));

import { __resetAnalyticsForTests, chooseAnalytics, getAnalyticsState } from "./analytics";
import { __resetAccountSettingsForTests, readAccountSettings } from "./accountSettings";

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  __resetAnalyticsForTests();
  __resetAccountSettingsForTests();
  fetchSettings.mockReset();
});

describe("readAccountSettings", () => {
  it("concurrent callers share one request and one answer", async () => {
    const d = deferred<{ analytics_opt_out: boolean }>();
    fetchSettings.mockReturnValue(d.promise);
    const a = readAccountSettings("u1");
    const b = readAccountSettings("u1");
    expect(fetchSettings).toHaveBeenCalledTimes(1);
    d.resolve({ analytics_opt_out: true });
    expect(await a).toBe(await b);
  });

  it("nothing is cached once it settles: the next call is a fresh GET", async () => {
    fetchSettings.mockResolvedValue({ analytics_opt_out: false });
    await readAccountSettings("u1");
    await readAccountSettings("u1");
    expect(fetchSettings).toHaveBeenCalledTimes(2);
  });

  it("every answer feeds the analytics switch, whoever asked", async () => {
    fetchSettings.mockResolvedValue({ analytics_opt_out: true });
    expect(getAnalyticsState()).toBe("unknown");
    await readAccountSettings("u1");
    expect(getAnalyticsState()).toBe("off");
  });

  it("a failure marks the switch unreadable and still rejects for the caller", async () => {
    fetchSettings.mockRejectedValue(new Error("500"));
    await expect(readAccountSettings("u1")).rejects.toThrow("500");
    expect(getAnalyticsState()).toBe("unreadable");
    fetchSettings.mockResolvedValue({ analytics_opt_out: false });
    await readAccountSettings("u1"); // e.g. Settings' "Try again"
    expect(getAnalyticsState()).toBe("on");
  });

  it("an answer that lands after a toggle does not overwrite it", async () => {
    fetchSettings.mockResolvedValue({ analytics_opt_out: false });
    await readAccountSettings("u1");
    const late = deferred<{ analytics_opt_out: boolean }>();
    fetchSettings.mockReturnValue(late.promise);
    const read = readAccountSettings("u1"); // in flight…
    expect(await chooseAnalytics("u1", false, async () => {})).toBe("saved"); // …the student opts out
    late.resolve({ analytics_opt_out: false }); // …and the stale answer lands
    await read;
    expect(getAnalyticsState()).toBe("off");
  });
});
