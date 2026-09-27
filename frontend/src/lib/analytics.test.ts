// @vitest-environment jsdom
/**
 * PostHog gating + privacy posture (src/lib/analytics.ts).
 *
 * The contract: no key, local mode and the E2E/test build each mean posthog-js
 * is never even LOADED (the loader is the lazy import), and a configured build
 * initialises with the privacy config — masked autocapture, no replay,
 * identified-only person profiles, UUID-only identify.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { CaptureResult, PostHog } from "posthog-js";

import {
  __resetAnalyticsForTests,
  analyticsDisabledReason,
  buildPosthogConfig,
  getAnalyticsState,
  identifyUser,
  initAnalytics,
  isAnalyticsActive,
  readAnalyticsEnv,
  resetAnalytics,
  scrubEvent,
  setAnalyticsEnabled,
  stripUrlQuery,
  subscribeAnalytics,
  type AnalyticsEnv,
} from "./analytics";

const KEY = "phc_test_public_key";

function fakePosthog() {
  let distinctId = "anon-1";
  let optedOut = false;
  const ph = {
    init: vi.fn(),
    identify: vi.fn((id: string) => {
      distinctId = id;
    }),
    reset: vi.fn(() => {
      distinctId = "anon-2";
      // posthog-js's reset() wipes stored consent too.
      optedOut = false;
    }),
    get_distinct_id: vi.fn(() => distinctId),
    has_opted_out_capturing: vi.fn(() => optedOut),
    opt_out_capturing: vi.fn(() => {
      optedOut = true;
    }),
    opt_in_capturing: vi.fn(() => {
      optedOut = false;
    }),
  };
  return ph;
}

type Fake = ReturnType<typeof fakePosthog>;

async function start(env: AnalyticsEnv, ph: Fake = fakePosthog()) {
  const load = vi.fn(async () => ph as unknown as PostHog);
  const active = await initAnalytics(env, load);
  return { active, load, ph };
}

beforeEach(() => {
  __resetAnalyticsForTests();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("init gating", () => {
  it("no key → never loads posthog-js", async () => {
    const { active, load } = await start({});
    expect(active).toBe(false);
    expect(load).not.toHaveBeenCalled();
    expect(isAnalyticsActive()).toBe(false);
    expect(analyticsDisabledReason({ NEXT_PUBLIC_POSTHOG_KEY: "   " })).toBe("no_key");
  });

  it("local UI mode → never loads, even with a key", async () => {
    const { active, load } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY, NEXT_PUBLIC_LOCAL_MODE: "true" });
    expect(active).toBe(false);
    expect(load).not.toHaveBeenCalled();
    expect(analyticsDisabledReason({ NEXT_PUBLIC_POSTHOG_KEY: KEY, NEXT_PUBLIC_LOCAL_MODE: "1" })).toBe("local_mode");
  });

  it("E2E/test build (NEXT_PUBLIC_TEST_MODE=1) → never loads, even with a key", async () => {
    const { active, load } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY, NEXT_PUBLIC_TEST_MODE: "1" });
    expect(active).toBe(false);
    expect(load).not.toHaveBeenCalled();
    expect(analyticsDisabledReason({ NEXT_PUBLIC_POSTHOG_KEY: KEY, NEXT_PUBLIC_TEST_MODE: "true" })).toBe("test_mode");
  });

  it("reads the build-time env vars", () => {
    vi.stubEnv("NEXT_PUBLIC_POSTHOG_KEY", KEY);
    vi.stubEnv("NEXT_PUBLIC_TEST_MODE", "1");
    expect(readAnalyticsEnv()).toMatchObject({ NEXT_PUBLIC_POSTHOG_KEY: KEY, NEXT_PUBLIC_TEST_MODE: "1" });
    expect(analyticsDisabledReason(readAnalyticsEnv())).toBe("test_mode");
  });

  it("a key → initialises once with the privacy config", async () => {
    const { active, load, ph } = await start({ NEXT_PUBLIC_POSTHOG_KEY: ` ${KEY} ` });
    expect(active).toBe(true);
    expect(load).toHaveBeenCalledTimes(1);
    expect(ph.init).toHaveBeenCalledTimes(1);
    const [key, config] = ph.init.mock.calls[0] as [string, Record<string, unknown>];
    expect(key).toBe(KEY);
    expect(config).toMatchObject({
      api_host: "/ingest",
      ui_host: "https://us.posthog.com",
      person_profiles: "identified_only",
      capture_pageview: "history_change",
      capture_pageleave: true,
      respect_dnt: true,
      disable_session_recording: true,
      capture_exceptions: false,
      mask_all_text: true,
      mask_all_element_attributes: true,
      autocapture: { capture_copied_text: false },
    });
    expect(config.before_send).toBe(scrubEvent);
    // Idempotent.
    expect(await initAnalytics({ NEXT_PUBLIC_POSTHOG_KEY: KEY }, load)).toBe(true);
    expect(ph.init).toHaveBeenCalledTimes(1);
  });

  it("NEXT_PUBLIC_POSTHOG_HOST overrides api_host", () => {
    expect(buildPosthogConfig({ NEXT_PUBLIC_POSTHOG_HOST: "https://us.i.posthog.com" }).api_host).toBe(
      "https://us.i.posthog.com",
    );
  });

  it("a loader failure leaves the app running with analytics off", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const load = vi.fn(async () => {
      throw new Error("blocked");
    });
    expect(await initAnalytics({ NEXT_PUBLIC_POSTHOG_KEY: KEY }, load)).toBe(false);
    expect(isAnalyticsActive()).toBe(false);
  });
});

describe("identify / reset", () => {
  it("is a no-op while analytics is off", async () => {
    await start({});
    expect(() => identifyUser("u-1")).not.toThrow();
    expect(() => resetAnalytics()).not.toThrow();
  });

  it("identifies with the UUID only — no traits", async () => {
    const { ph } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY });
    identifyUser("3f1c-uuid");
    expect(ph.identify).toHaveBeenCalledTimes(1);
    expect(ph.identify.mock.calls[0]).toEqual(["3f1c-uuid"]);
    // Re-identifying the same user is skipped.
    identifyUser("3f1c-uuid");
    expect(ph.identify).toHaveBeenCalledTimes(1);
  });

  it("replays an identify requested while posthog-js was still loading", async () => {
    const ph = fakePosthog();
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const load = vi.fn(async () => {
      await gate;
      return ph as unknown as PostHog;
    });
    const pending = initAnalytics({ NEXT_PUBLIC_POSTHOG_KEY: KEY }, load);
    identifyUser("early-user");
    expect(ph.identify).not.toHaveBeenCalled();
    release();
    await pending;
    expect(ph.identify.mock.calls).toEqual([["early-user"]]);
  });

  it("reset() on sign-out, keeping an opt-out in force", async () => {
    const { ph } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY });
    identifyUser("u-1");
    resetAnalytics();
    expect(ph.reset).toHaveBeenCalledTimes(1);
    expect(ph.opt_out_capturing).not.toHaveBeenCalled();

    setAnalyticsEnabled(false);
    resetAnalytics();
    expect(ph.reset).toHaveBeenCalledTimes(2);
    // reset() wiped consent; the opt-out was re-applied.
    expect(ph.has_opted_out_capturing()).toBe(true);
  });
});

describe("opt-out store", () => {
  it("is unavailable when analytics is off", async () => {
    await start({});
    expect(getAnalyticsState()).toBe("unavailable");
    setAnalyticsEnabled(false); // no throw, no effect
    expect(getAnalyticsState()).toBe("unavailable");
  });

  it("toggles opt_out/opt_in and notifies subscribers", async () => {
    const { ph } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY });
    const listener = vi.fn();
    const unsubscribe = subscribeAnalytics(listener);
    expect(getAnalyticsState()).toBe("on");
    setAnalyticsEnabled(false);
    expect(ph.opt_out_capturing).toHaveBeenCalledTimes(1);
    expect(getAnalyticsState()).toBe("off");
    setAnalyticsEnabled(true);
    expect(ph.opt_in_capturing).toHaveBeenCalledTimes(1);
    expect(getAnalyticsState()).toBe("on");
    expect(listener).toHaveBeenCalledTimes(2);
    unsubscribe();
  });

  it("reports browser_blocked under Do Not Track / GPC", async () => {
    await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY });
    Object.defineProperty(navigator, "globalPrivacyControl", { value: true, configurable: true });
    try {
      expect(getAnalyticsState()).toBe("browser_blocked");
    } finally {
      delete (navigator as { globalPrivacyControl?: boolean }).globalPrivacyControl;
    }
    expect(getAnalyticsState()).toBe("on");
  });
});

describe("before_send URL scrubbing", () => {
  it("strips query strings and fragments from absolute URLs only", () => {
    expect(stripUrlQuery("https://saplinglearn.com/auth/callback?user_id=u&auth_token=secret")).toBe(
      "https://saplinglearn.com/auth/callback",
    );
    expect(stripUrlQuery("https://saplinglearn.com/learn#topic")).toBe("https://saplinglearn.com/learn");
    expect(stripUrlQuery("/relative?x=1")).toBe("/relative?x=1");
    expect(stripUrlQuery(42)).toBe(42);
  });

  it("scrubs properties, $set and $set_once", () => {
    const event = {
      event: "$pageview",
      uuid: "x",
      properties: {
        $current_url: "https://saplinglearn.com/auth/callback?auth_token=secret&avatar=https%3A%2F%2Fx",
        $pathname: "/auth/callback",
        $referrer: "https://accounts.google.com/o/oauth2?code=abc",
      },
      $set_once: { $initial_current_url: "https://saplinglearn.com/?error=x" },
      $set: { $current_url: "https://saplinglearn.com/a?b=c" },
    } as unknown as CaptureResult;
    const out = scrubEvent(event)!;
    expect(JSON.stringify(out)).not.toContain("secret");
    expect(out.properties.$current_url).toBe("https://saplinglearn.com/auth/callback");
    expect(out.properties.$referrer).toBe("https://accounts.google.com/o/oauth2");
    expect(out.properties.$pathname).toBe("/auth/callback");
    expect(out.$set_once?.$initial_current_url).toBe("https://saplinglearn.com/");
    expect(out.$set?.$current_url).toBe("https://saplinglearn.com/a");
    expect(scrubEvent(null)).toBeNull();
  });
});
