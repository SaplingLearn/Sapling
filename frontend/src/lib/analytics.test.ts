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
  applyAccountAnalyticsPreference,
  buildPosthogConfig,
  getAnalyticsState,
  identifyUser,
  initAnalytics,
  isAnalyticsActive,
  isAnalyticsConfigured,
  readAnalyticsEnv,
  resetAnalytics,
  scrubEvent,
  scrubValue,
  setAnalyticsEnabled,
  stripUrlQuery,
  subscribeAnalytics,
  type AnalyticsEnv,
} from "./analytics";

const KEY = "phc_test_public_key";

function fakePosthog(initial: { distinctId?: string; identified?: boolean } = {}) {
  let distinctId = initial.distinctId ?? "anon-1";
  let identified = initial.identified ?? false;
  let optedOut = false;
  const ph = {
    init: vi.fn(),
    identify: vi.fn((id: string) => {
      distinctId = id;
      identified = true;
    }),
    reset: vi.fn(() => {
      distinctId = "anon-2";
      identified = false;
      // posthog-js's reset() wipes stored consent too.
      optedOut = false;
    }),
    get_distinct_id: vi.fn(() => distinctId),
    get_property: vi.fn((name: string) =>
      name === "$user_state" ? (identified ? "identified" : "anonymous") : undefined,
    ),
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
      mask_personal_data_properties: true,
      disable_capture_url_hashes: true,
    });
    // The /auth/callback handoff params are masked by posthog-js at the source.
    expect(config.custom_personal_data_properties).toEqual(
      expect.arrayContaining(["auth_token", "user_id", "avatar", "popup_id"]),
    );
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

  it("isAnalyticsConfigured mirrors the gate", () => {
    expect(isAnalyticsConfigured({ NEXT_PUBLIC_POSTHOG_KEY: KEY })).toBe(true);
    expect(isAnalyticsConfigured({})).toBe(false);
    expect(isAnalyticsConfigured({ NEXT_PUBLIC_POSTHOG_KEY: KEY, NEXT_PUBLIC_TEST_MODE: "1" })).toBe(false);
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

  it("identifying an anonymous browser does not reset it", async () => {
    const { ph } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY });
    identifyUser("u-1");
    expect(ph.reset).not.toHaveBeenCalled();
    expect(ph.identify.mock.calls).toEqual([["u-1"]]);
  });

  it("resets before identifying a DIFFERENT identified user, so the two are never merged", async () => {
    const { ph } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY }, fakePosthog({ distinctId: "u-A", identified: true }));
    identifyUser("u-B");
    expect(ph.reset).toHaveBeenCalledTimes(1);
    expect(ph.reset.mock.invocationCallOrder[0]).toBeLessThan(ph.identify.mock.invocationCallOrder[0]);
    expect(ph.identify.mock.calls).toEqual([["u-B"]]);
    expect(ph.get_distinct_id()).toBe("u-B");
  });

  it("carries an opt-out across that reset", async () => {
    const { ph } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY }, fakePosthog({ distinctId: "u-A", identified: true }));
    setAnalyticsEnabled(false);
    identifyUser("u-B");
    expect(ph.reset).toHaveBeenCalledTimes(1);
    expect(ph.has_opted_out_capturing()).toBe(true);
  });

  it("the replayed identify after a slow load also resets a different identified user", async () => {
    const ph = fakePosthog({ distinctId: "u-A", identified: true });
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const pending = initAnalytics({ NEXT_PUBLIC_POSTHOG_KEY: KEY }, async () => {
      await gate;
      return ph as unknown as PostHog;
    });
    identifyUser("u-B");
    release();
    await pending;
    expect(ph.reset).toHaveBeenCalledTimes(1);
    expect(ph.identify.mock.calls).toEqual([["u-B"]]);
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

describe("account-level preference (user_settings.analytics_opt_out)", () => {
  it("an account opt-out turns this browser off and notifies", async () => {
    const { ph } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY });
    const listener = vi.fn();
    subscribeAnalytics(listener);
    applyAccountAnalyticsPreference(true);
    expect(ph.opt_out_capturing).toHaveBeenCalledTimes(1);
    expect(getAnalyticsState()).toBe("off");
    expect(listener).toHaveBeenCalledTimes(1);
    // Idempotent.
    applyAccountAnalyticsPreference(true);
    expect(ph.opt_out_capturing).toHaveBeenCalledTimes(1);
  });

  it("false or a missing field never overrides a local opt-out, and never opts in", async () => {
    const { ph } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY });
    setAnalyticsEnabled(false);
    for (const value of [false, undefined, null, "true"]) applyAccountAnalyticsPreference(value);
    expect(ph.opt_in_capturing).not.toHaveBeenCalled();
    expect(getAnalyticsState()).toBe("off");
  });

  it("a missing field leaves an opted-in browser on", async () => {
    const { ph } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY });
    applyAccountAnalyticsPreference(undefined);
    expect(ph.opt_out_capturing).not.toHaveBeenCalled();
    expect(getAnalyticsState()).toBe("on");
  });

  it("is a no-op while analytics is off", async () => {
    await start({});
    expect(() => applyAccountAnalyticsPreference(true)).not.toThrow();
    expect(getAnalyticsState()).toBe("unavailable");
  });

  it("an opt-out that arrives while posthog-js loads is applied before the replayed identify", async () => {
    const ph = fakePosthog();
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const pending = initAnalytics({ NEXT_PUBLIC_POSTHOG_KEY: KEY }, async () => {
      await gate;
      return ph as unknown as PostHog;
    });
    applyAccountAnalyticsPreference(true);
    identifyUser("u-1");
    release();
    await pending;
    expect(ph.opt_out_capturing).toHaveBeenCalledTimes(1);
    expect(ph.opt_out_capturing.mock.invocationCallOrder[0]).toBeLessThan(ph.identify.mock.invocationCallOrder[0]);
    expect(getAnalyticsState()).toBe("off");
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

  it("scrubs nested objects and arrays: web-vitals metrics and heatmap URL keys", () => {
    const event = {
      event: "$$heatmap",
      uuid: "x",
      properties: {
        $web_vitals_LCP_event: {
          name: "LCP",
          $current_url: "https://saplinglearn.com/auth/callback?auth_token=secret-1",
          attribution: { url: "https://saplinglearn.com/x?auth_token=secret-2" },
        },
        $heatmap_data: {
          "https://saplinglearn.com/auth/callback?auth_token=secret-3": [{ x: 1 }],
          "https://saplinglearn.com/auth/callback?user_id=secret-4": [{ x: 2 }],
          "https://saplinglearn.com/learn": [{ x: 3 }],
        },
        $elements: [{ attr__href: "https://saplinglearn.com/a?token=secret-5" }],
      },
    } as unknown as CaptureResult;
    const out = scrubEvent(event)!;
    expect(JSON.stringify(out)).not.toMatch(/secret/);
    const heatmap = out.properties.$heatmap_data as Record<string, unknown[]>;
    // Two URLs that collapse onto one page keep both pages' points.
    expect(heatmap["https://saplinglearn.com/auth/callback"]).toEqual([{ x: 1 }, { x: 2 }]);
    expect(heatmap["https://saplinglearn.com/learn"]).toEqual([{ x: 3 }]);
    expect(
      (out.properties.$web_vitals_LCP_event as { $current_url: string }).$current_url,
    ).toBe("https://saplinglearn.com/auth/callback");
  });

  it("opts every event out of GeoIP enrichment", () => {
    const out = scrubEvent({ event: "$pageview", uuid: "x", properties: {} } as unknown as CaptureResult)!;
    expect(out.properties.$geoip_disable).toBe(true);
  });

  it("stops at a depth limit instead of looping on a cycle", () => {
    const cyclic: Record<string, unknown> = { url: "https://x.test/?a=1" };
    cyclic.self = cyclic;
    expect(() => scrubValue(cyclic)).not.toThrow();
    expect(cyclic.url).toBe("https://x.test/");
  });
});
