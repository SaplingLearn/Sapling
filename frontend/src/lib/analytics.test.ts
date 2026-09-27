// @vitest-environment jsdom
/**
 * Product analytics (src/lib/analytics.ts), unit level with a posthog-js
 * stand-in. The model: posthog-js is loaded only for a signed-in student
 * whose account says `analytics_opt_out: false`; everything else is off.
 * The account flag is the single source of truth; nothing is stored in the
 * browser. The real-SDK behaviour is pinned in analytics.posthog.test.ts.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { CaptureResult, PostHog } from "posthog-js";

import {
  __analyticsLoadedForTests,
  __resetAnalyticsForTests,
  analyticsDisabledReason,
  applyAccountAnalytics,
  beginAccountRead,
  buildPosthogConfig,
  chooseAnalytics,
  gatedBeforeSend,
  getAnalyticsState,
  isAnalyticsConfigured,
  readAnalyticsEnv,
  scrubEvent,
  scrubValue,
  stopAnalytics,
  stripUrlQuery,
  subscribeAnalytics,
  type AnalyticsEnv,
} from "./analytics";
import { isTruthyBuildFlag } from "./testMode";

const KEY = "phc_test_public_key";
const ENV = { NEXT_PUBLIC_POSTHOG_KEY: KEY };

/** A posthog-js stand-in: init runs the `loaded` hook, as the SDK does. */
function fakePosthog() {
  let distinctId = "anon-1";
  let identified = false;
  const ph = {
    init: vi.fn((_key: string, config: { loaded?: (p: unknown) => void }) => {
      config.loaded?.(ph);
    }),
    capture: vi.fn(),
    identify: vi.fn((id: string) => {
      distinctId = id;
      identified = true;
    }),
    reset: vi.fn(() => {
      distinctId = "anon-2";
      identified = false;
    }),
    get_distinct_id: vi.fn(() => distinctId),
    get_property: vi.fn((name: string) =>
      name === "$user_state" ? (identified ? "identified" : "anonymous") : undefined,
    ),
    opt_out_capturing: vi.fn(),
    opt_in_capturing: vi.fn(),
  };
  return ph;
}
type Fake = ReturnType<typeof fakePosthog>;

let ph: Fake;
let load: ReturnType<typeof vi.fn>;

function setup(env: AnalyticsEnv = ENV) {
  ph = fakePosthog();
  load = vi.fn(async () => ph as unknown as PostHog);
  __resetAnalyticsForTests({ env, load: load as unknown as () => Promise<PostHog> });
}

/** A signed-in student whose account answers `optOut`. */
async function signIn(userId: string, optOut: unknown) {
  const gen = beginAccountRead(userId);
  applyAccountAnalytics(gen, userId, optOut);
  await __analyticsLoadedForTests();
}

function setGpc(on: boolean) {
  if (on) Object.defineProperty(navigator, "globalPrivacyControl", { value: true, configurable: true });
  else delete (navigator as { globalPrivacyControl?: boolean }).globalPrivacyControl;
}

const event = (name: string) => ({ event: name, uuid: "x", properties: {} }) as unknown as CaptureResult;
const ok = () => Promise.resolve();
const fail = () => Promise.reject(new Error("500"));

beforeEach(() => setup());
afterEach(() => {
  setGpc(false);
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("build gating", () => {
  it("no key, local mode or the test build → unavailable, never loaded", async () => {
    for (const env of [
      {},
      { NEXT_PUBLIC_POSTHOG_KEY: "   " },
      { ...ENV, NEXT_PUBLIC_LOCAL_MODE: "true" },
      { ...ENV, NEXT_PUBLIC_TEST_MODE: "1" },
    ]) {
      setup(env);
      expect(isAnalyticsConfigured()).toBe(false);
      await signIn("u-1", false);
      expect(getAnalyticsState()).toBe("unavailable");
      expect(load).not.toHaveBeenCalled();
    }
    expect(analyticsDisabledReason({ ...ENV, NEXT_PUBLIC_TEST_MODE: "true" })).toBe("test_mode");
  });

  it("uses the app's one definition of a build flag (lib/testMode.ts)", () => {
    for (const v of ["1", "true", "0", "false", "", "yes", undefined]) {
      const reason = analyticsDisabledReason({ ...ENV, NEXT_PUBLIC_TEST_MODE: v });
      expect(reason === "test_mode", String(v)).toBe(isTruthyBuildFlag(v));
    }
  });

  it("reads the build-time env vars", () => {
    vi.stubEnv("NEXT_PUBLIC_POSTHOG_KEY", KEY);
    vi.stubEnv("NEXT_PUBLIC_TEST_MODE", "1");
    expect(readAnalyticsEnv()).toMatchObject({ NEXT_PUBLIC_POSTHOG_KEY: KEY, NEXT_PUBLIC_TEST_MODE: "1" });
  });

  it("the privacy config: memory persistence, no flags, no remote UI, masking", () => {
    const config = buildPosthogConfig(ENV);
    expect(config).toMatchObject({
      api_host: "/ingest",
      ui_host: "https://us.posthog.com",
      persistence: "memory",
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
      advanced_disable_flags: true,
      disable_surveys: true,
      disable_surveys_automatic_display: true,
      disable_product_tours: true,
      disable_conversations: true,
      disable_web_experiments: true,
      opt_in_site_apps: false,
    });
    expect(config.custom_personal_data_properties).toEqual(
      expect.arrayContaining(["auth_token", "user_id", "avatar", "popup_id"]),
    );
    expect(config.before_send).toBe(gatedBeforeSend);
    expect(config).not.toHaveProperty("opt_out_capturing_by_default");
    expect(buildPosthogConfig({ NEXT_PUBLIC_POSTHOG_HOST: "https://us.i.posthog.com" }).api_host).toBe(
      "https://us.i.posthog.com",
    );
  });

  it("a loader failure leaves the app running with analytics off", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    __resetAnalyticsForTests({
      env: ENV,
      load: async () => {
        throw new Error("blocked");
      },
    });
    await signIn("u-1", false);
    expect(await __analyticsLoadedForTests()).toBeNull();
  });
});

describe("only signed-in students whose account says false", () => {
  it("anonymous / signed out: not loaded, nothing passes the gate", async () => {
    stopAnalytics();
    expect(getAnalyticsState()).toBe("unknown");
    expect(load).not.toHaveBeenCalled();
    expect(gatedBeforeSend(event("$pageview"))).toBeNull();
  });

  it("account false: loaded, identified by UUID alone in `loaded`, events pass", async () => {
    await signIn("3f1c-uuid", false);
    expect(getAnalyticsState()).toBe("on");
    expect(load).toHaveBeenCalledTimes(1);
    expect(ph.identify.mock.calls).toEqual([["3f1c-uuid"]]);
    expect(gatedBeforeSend(event("$pageview"))).not.toBeNull();
  });

  it("account true: off, never loaded, never identified", async () => {
    await signIn("u-1", true);
    expect(getAnalyticsState()).toBe("off");
    expect(load).not.toHaveBeenCalled();
    expect(gatedBeforeSend(event("$pageview"))).toBeNull();
  });

  it("a missing field or a failed read (no answer): unknown, never loaded", async () => {
    await signIn("u-1", undefined);
    expect(getAnalyticsState()).toBe("unknown");
    beginAccountRead("u-1"); // the read that then fails never answers
    expect(getAnalyticsState()).toBe("unknown");
    expect(load).not.toHaveBeenCalled();
  });

  it("DNT / GPC: always off — never loaded, even when the account says false", async () => {
    setGpc(true);
    await signIn("u-1", false);
    expect(getAnalyticsState()).toBe("browser_blocked");
    expect(load).not.toHaveBeenCalled();
    expect(gatedBeforeSend(event("$pageview"))).toBeNull();
    expect(await chooseAnalytics("u-1", true, ok)).toBe("failed");
  });

  it("never touches posthog-js's own (persisted) opt-out / opt-in", async () => {
    await signIn("u-1", false);
    await chooseAnalytics("u-1", false, ok);
    await chooseAnalytics("u-1", true, ok);
    expect(ph.opt_out_capturing).not.toHaveBeenCalled();
    expect(ph.opt_in_capturing).not.toHaveBeenCalled();
  });

  it("sign-out stops capture at once; a different student later on the same page is never merged", async () => {
    await signIn("u-X", false);
    stopAnalytics();
    expect(gatedBeforeSend(event("$autocapture"))).toBeNull();
    expect(ph.reset).toHaveBeenCalledTimes(1);
    await signIn("u-Y", false);
    expect(ph.identify.mock.calls).toEqual([["u-X"], ["u-Y"]]);
    expect(load).toHaveBeenCalledTimes(1); // loaded once per page
  });
});

describe("stale account reads", () => {
  it("a read that started before a toggle is ignored", async () => {
    await signIn("u-1", false);
    const staleGen = beginAccountRead("u-1"); // e.g. a re-render's read, in flight
    await chooseAnalytics("u-1", false, ok); // the student opts out meanwhile
    applyAccountAnalytics(staleGen, "u-1", false); // …and the old answer lands
    expect(getAnalyticsState()).toBe("off");
    expect(gatedBeforeSend(event("$pageview"))).toBeNull();
  });

  it("a read for a user who has since signed out is ignored", async () => {
    const gen = beginAccountRead("u-1");
    stopAnalytics();
    applyAccountAnalytics(gen, "u-1", false);
    expect(getAnalyticsState()).toBe("unknown");
    expect(load).not.toHaveBeenCalled();
  });
});

describe("Settings choices (chooseAnalytics)", () => {
  it("opt-OUT stops capture before the save resolves", async () => {
    await signIn("u-1", false);
    let finish!: () => void;
    const save = vi.fn(() => new Promise<void>((r) => (finish = r)));
    const done = chooseAnalytics("u-1", false, save);
    expect(getAnalyticsState()).toBe("off");
    expect(gatedBeforeSend(event("$autocapture"))).toBeNull();
    finish();
    expect(await done).toBe("saved");
    expect(save).toHaveBeenCalledWith(true);
  });

  it("a failed opt-OUT save stays off for the page load", async () => {
    await signIn("u-1", false);
    expect(await chooseAnalytics("u-1", false, fail)).toBe("failed");
    expect(getAnalyticsState()).toBe("off");
  });

  it("opt-IN: nothing starts until the save succeeds", async () => {
    await signIn("u-1", true);
    let finish!: () => void;
    const save = vi.fn(() => new Promise<void>((r) => (finish = r)));
    const done = chooseAnalytics("u-1", true, save);
    expect(save).toHaveBeenCalledWith(false);
    expect(getAnalyticsState()).toBe("off");
    expect(load).not.toHaveBeenCalled();
    finish();
    expect(await done).toBe("saved");
    await __analyticsLoadedForTests();
    expect(getAnalyticsState()).toBe("on");
    expect(ph.identify.mock.calls).toEqual([["u-1"]]);
  });

  it("a failed opt-IN save changes nothing", async () => {
    await signIn("u-1", true);
    expect(await chooseAnalytics("u-1", true, fail)).toBe("failed");
    expect(getAnalyticsState()).toBe("off");
    expect(load).not.toHaveBeenCalled();
  });

  it("one toggle at a time", async () => {
    await signIn("u-1", false);
    let finish!: () => void;
    const save = vi.fn(() => new Promise<void>((r) => (finish = r)));
    const first = chooseAnalytics("u-1", false, save);
    expect(await chooseAnalytics("u-1", true, save)).toBe("busy");
    finish();
    await first;
    expect(save).toHaveBeenCalledTimes(1);
    expect(getAnalyticsState()).toBe("off");
  });

  it("refused before the account has answered (the switch is disabled then)", async () => {
    beginAccountRead("u-1");
    expect(await chooseAnalytics("u-1", true, ok)).toBe("failed");
  });

  it("notifies subscribers", async () => {
    const listener = vi.fn();
    subscribeAnalytics(listener);
    await signIn("u-1", false);
    await chooseAnalytics("u-1", false, ok);
    expect(listener.mock.calls.length).toBeGreaterThanOrEqual(3);
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
