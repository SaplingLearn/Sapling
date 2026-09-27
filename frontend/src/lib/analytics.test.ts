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
  gatedBeforeSend,
  getAnalyticsState,
  holdAnalytics,
  identifyUser,
  initAnalytics,
  isAnalyticsActive,
  isAnalyticsConfigured,
  readAnalyticsEnv,
  releaseAnonymousAnalytics,
  resetAnalytics,
  resolveAccountAnalytics,
  scrubEvent,
  scrubValue,
  chooseAnalytics,
  OPT_OUT_RECORDS_KEY,
  stripUrlQuery,
  subscribeAnalytics,
  type AnalyticsEnv,
} from "./analytics";
import { isTruthyBuildFlag } from "./testMode";

const KEY = "phc_test_public_key";

/**
 * A posthog-js stand-in with its consent model: an explicit stored choice
 * (pending/granted/denied), `opt_out_capturing_by_default` for pending, and
 * Do Not Track / GPC folded into every getter (respect_dnt) — including
 * get_explicit_consent_status(), exactly as the real SDK does.
 */
function fakePosthog(initial: { distinctId?: string; identified?: boolean; consent?: Consent } = {}) {
  let distinctId = initial.distinctId ?? "anon-1";
  let identified = initial.identified ?? false;
  let consent: Consent = initial.consent ?? "pending";
  let optOutByDefault = false;
  const gpc = () => (navigator as { globalPrivacyControl?: boolean }).globalPrivacyControl === true;
  const ph = {
    init: vi.fn((_key: string, config: { opt_out_capturing_by_default?: boolean }) => {
      optOutByDefault = config.opt_out_capturing_by_default === true;
    }),
    capture: vi.fn(),
    identify: vi.fn((id: string) => {
      distinctId = id;
      identified = true;
    }),
    reset: vi.fn(() => {
      distinctId = "anon-2";
      identified = false;
      // posthog-js's reset() wipes stored consent too.
      consent = "pending";
    }),
    get_distinct_id: vi.fn(() => distinctId),
    get_property: vi.fn((name: string) =>
      name === "$user_state" ? (identified ? "identified" : "anonymous") : undefined,
    ),
    has_opted_out_capturing: vi.fn(
      () => gpc() || consent === "denied" || (consent === "pending" && optOutByDefault),
    ),
    get_explicit_consent_status: vi.fn(() => (gpc() ? "denied" : consent)),
    opt_out_capturing: vi.fn(() => {
      consent = "denied";
    }),
    opt_in_capturing: vi.fn((...args: [{ captureEventName?: string | false | null }?]) => {
      void args;
      consent = "granted";
    }),
    storedConsent: () => consent,
  };
  return ph;
}
type Consent = "pending" | "granted" | "denied";

type Fake = ReturnType<typeof fakePosthog>;

async function start(env: AnalyticsEnv, ph: Fake = fakePosthog()) {
  const load = vi.fn(async () => ph as unknown as PostHog);
  const active = await initAnalytics(env, load);
  return { active, load, ph };
}

/** A new page load in the same browser: module state goes, storage stays. */
async function reload(ph: Fake = fakePosthog()) {
  __resetAnalyticsForTests();
  return start({ NEXT_PUBLIC_POSTHOG_KEY: KEY }, ph);
}

function records(): Record<string, string> {
  return JSON.parse(localStorage.getItem(OPT_OUT_RECORDS_KEY) ?? "{}");
}

function setGpc(on: boolean) {
  if (on) Object.defineProperty(navigator, "globalPrivacyControl", { value: true, configurable: true });
  else delete (navigator as { globalPrivacyControl?: boolean }).globalPrivacyControl;
}

const ok = () => Promise.resolve();
const fail = () => Promise.reject(new Error("500"));

beforeEach(() => {
  __resetAnalyticsForTests();
  localStorage.clear();
});

afterEach(() => {
  setGpc(false);
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
    // No feature flags (no /flags request) and no remote-UI extensions.
    expect(config).toMatchObject({
      advanced_disable_flags: true,
      disable_surveys: true,
      disable_surveys_automatic_display: true,
      disable_product_tours: true,
      disable_conversations: true,
      disable_web_experiments: true,
      opt_in_site_apps: false,
      opt_out_capturing_by_default: false,
    });
    expect(config.before_send).toBe(gatedBeforeSend);
    // Idempotent.
    expect(await initAnalytics({ NEXT_PUBLIC_POSTHOG_KEY: KEY }, load)).toBe(true);
    expect(ph.init).toHaveBeenCalledTimes(1);
  });

  it("NEXT_PUBLIC_POSTHOG_HOST overrides api_host", () => {
    expect(buildPosthogConfig({ NEXT_PUBLIC_POSTHOG_HOST: "https://us.i.posthog.com" }).api_host).toBe(
      "https://us.i.posthog.com",
    );
  });

  it("uses the app's one definition of the test build (lib/testMode.ts)", () => {
    for (const v of ["1", "true", "0", "false", "", "yes", undefined]) {
      const reason = analyticsDisabledReason({ NEXT_PUBLIC_POSTHOG_KEY: KEY, NEXT_PUBLIC_TEST_MODE: v });
      expect(reason === "test_mode", String(v)).toBe(isTruthyBuildFlag(v));
    }
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

describe("identify", () => {
  it("is a no-op while analytics is off", async () => {
    await start({});
    expect(() => identifyUser("u-1")).not.toThrow();
    expect(() => resetAnalytics()).not.toThrow();
    expect(() => resolveAccountAnalytics("u-1", true)).not.toThrow();
  });

  it("identifies with the UUID only — no traits — once the account says not opted out", async () => {
    const { ph } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY });
    holdAnalytics();
    resolveAccountAnalytics("3f1c-uuid", false);
    expect(ph.identify.mock.calls).toEqual([["3f1c-uuid"]]);
    resolveAccountAnalytics("3f1c-uuid", false); // same user again: skipped
    expect(ph.identify).toHaveBeenCalledTimes(1);
  });

  it("NEVER identifies an opted-out student — account, local choice, or DNT/GPC", async () => {
    const { ph } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY });
    resolveAccountAnalytics("u-account", true);
    identifyUser("u-account");
    expect(ph.identify).not.toHaveBeenCalled();

    await reload(ph);
    localStorage.setItem(OPT_OUT_RECORDS_KEY, JSON.stringify({ "u-local": "saved" }));
    resolveAccountAnalytics("u-local", undefined);
    expect(ph.identify).not.toHaveBeenCalled();

    await reload(fakePosthog());
    setGpc(true);
    const { ph: ph3 } = await reload();
    resolveAccountAnalytics("u-gpc", false);
    expect(ph3.identify).not.toHaveBeenCalled();
  });

  it("resets before identifying a DIFFERENT identified user, so the two are never merged", async () => {
    const { ph } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY }, fakePosthog({ distinctId: "u-A", identified: true }));
    resolveAccountAnalytics("u-B", false);
    expect(ph.reset).toHaveBeenCalledTimes(1);
    expect(ph.reset.mock.invocationCallOrder[0]).toBeLessThan(ph.identify.mock.invocationCallOrder[0]);
    expect(ph.identify.mock.calls).toEqual([["u-B"]]);
  });

  it("an answer that arrives while posthog-js loads is replayed after init", async () => {
    const ph = fakePosthog();
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const pending = initAnalytics({ NEXT_PUBLIC_POSTHOG_KEY: KEY }, async () => {
      await gate;
      return ph as unknown as PostHog;
    });
    holdAnalytics();
    resolveAccountAnalytics("early-user", false);
    expect(ph.identify).not.toHaveBeenCalled();
    release();
    await pending;
    expect(ph.identify.mock.calls).toEqual([["early-user"]]);
  });
});

describe("the per-user opt-out decision", () => {
  it("an account opt-out applies but is NOT recorded as a local choice", async () => {
    const { ph } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY });
    resolveAccountAnalytics("u-1", true);
    expect(ph.opt_out_capturing).toHaveBeenCalledTimes(1);
    expect(getAnalyticsState()).toBe("off");
    expect(records()).toEqual({});
  });

  it("an account false clears an account-derived opt-out on the next load", async () => {
    const { ph } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY });
    resolveAccountAnalytics("u-1", true);
    expect(getAnalyticsState()).toBe("off");
    // Next load: posthog-js still remembers "denied"; the account now says false.
    const next = fakePosthog({ consent: ph.storedConsent() });
    await reload(next);
    resolveAccountAnalytics("u-1", false);
    expect(next.opt_in_capturing).toHaveBeenCalledWith({ captureEventName: false });
    expect(getAnalyticsState()).toBe("on");
    expect(next.identify).toHaveBeenCalledWith("u-1");
  });

  it("(a) laptop A / laptop B: opting back in on B reaches A", async () => {
    // Laptop A: the student opts out in Settings; the account save succeeds.
    localStorage.setItem("sapling_user", JSON.stringify({ id: "u-1" }));
    const a1 = fakePosthog();
    await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY }, a1);
    resolveAccountAnalytics("u-1", false);
    expect(await chooseAnalytics("u-1", false, ok)).toBe("saved");
    expect(records()).toEqual({ "u-1": "saved" });
    const laptopA: Record<string, string> = {};
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)!;
      laptopA[k] = localStorage.getItem(k)!;
    }
    const aConsent = a1.storedConsent();

    // Laptop B (a different browser): the account's opt-out applies there.
    localStorage.clear();
    const b = fakePosthog();
    await reload(b);
    resolveAccountAnalytics("u-1", true);
    expect(getAnalyticsState()).toBe("off");
    expect(b.identify).not.toHaveBeenCalled();
    // …and the student opts back in there. The account is saved FIRST.
    const save = vi.fn(ok);
    expect(await chooseAnalytics("u-1", true, save)).toBe("saved");
    expect(save).toHaveBeenCalledWith(false);
    expect(save.mock.invocationCallOrder[0]).toBeLessThan(b.opt_in_capturing.mock.invocationCallOrder[0]);
    expect(getAnalyticsState()).toBe("on");

    // Back on laptop A: its "saved" note is superseded by the account's false.
    localStorage.clear();
    for (const [k, v] of Object.entries(laptopA)) localStorage.setItem(k, v);
    const a2 = fakePosthog({ consent: aConsent });
    await reload(a2);
    // Before the account answers, A's own note holds it off from init on.
    expect(a2.init.mock.calls[0][1]).toMatchObject({ opt_out_capturing_by_default: true });
    resolveAccountAnalytics("u-1", false);
    expect(getAnalyticsState()).toBe("on");
    expect(a2.identify).toHaveBeenCalledWith("u-1");
    expect(records()).toEqual({});
  });

  it("(b) shared browser: student Y never inherits student X's opt-out", async () => {
    localStorage.setItem("sapling_user", JSON.stringify({ id: "u-X" }));
    const ph = fakePosthog();
    await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY }, ph);
    resolveAccountAnalytics("u-X", false);
    await chooseAnalytics("u-X", false, ok);
    expect(getAnalyticsState()).toBe("off");

    // X signs out: the signed-out browser stays off for X…
    resetAnalytics();
    expect(ph.storedConsent()).toBe("denied");
    localStorage.setItem("sapling_user", JSON.stringify({ id: "u-Y" }));

    // …Y signs in on the next load, with an account that predates the column
    // or explicitly says false: Y is on, identified, and X's note is untouched.
    for (const account of [undefined, false]) {
      const next = fakePosthog({ consent: ph.storedConsent() });
      await reload(next);
      expect(next.init.mock.calls[0][1]).toMatchObject({ opt_out_capturing_by_default: false });
      resolveAccountAnalytics("u-Y", account);
      expect(getAnalyticsState()).toBe("on");
      expect(next.identify).toHaveBeenCalledWith("u-Y");
    }
    expect(records()).toEqual({ "u-X": "saved" });
  });

  it("the same handover inside one page load (no reload between them)", async () => {
    const { ph } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY }, fakePosthog());
    resolveAccountAnalytics("u-X", true);
    resetAnalytics(); // X signs out
    holdAnalytics(); // Y signs in
    resolveAccountAnalytics("u-Y", false);
    expect(getAnalyticsState()).toBe("on");
    expect(ph.identify.mock.calls).toEqual([["u-Y"]]);
  });

  it("an opt-out whose account save FAILED stands, even against an account false", async () => {
    const { ph } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY });
    resolveAccountAnalytics("u-1", false);
    expect(await chooseAnalytics("u-1", false, fail)).toBe("local_only");
    expect(records()).toEqual({ "u-1": "pending" });
    const next = fakePosthog({ consent: ph.storedConsent() });
    await reload(next);
    resolveAccountAnalytics("u-1", false);
    expect(getAnalyticsState()).toBe("off");
    expect(next.identify).not.toHaveBeenCalled();
  });

  it("a backend without the column (pre-#677): this browser's note decides", async () => {
    localStorage.setItem(OPT_OUT_RECORDS_KEY, JSON.stringify({ "u-1": "saved" }));
    const { ph } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY });
    resolveAccountAnalytics("u-1", undefined);
    expect(ph.opt_out_capturing).toHaveBeenCalled();
    expect(getAnalyticsState()).toBe("off");
    resolveAccountAnalytics("u-2", undefined);
    expect(getAnalyticsState()).toBe("on");
  });
});

describe("Settings choices (chooseAnalytics)", () => {
  it("opt-out is local-first: capture stops before the save resolves", async () => {
    const { ph } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY });
    resolveAccountAnalytics("u-1", false);
    let finish!: () => void;
    const save = vi.fn(() => new Promise<void>((r) => (finish = r)));
    const done = chooseAnalytics("u-1", false, save);
    expect(ph.opt_out_capturing).toHaveBeenCalledTimes(1);
    expect(getAnalyticsState()).toBe("off");
    expect(records()).toEqual({ "u-1": "pending" });
    finish();
    expect(await done).toBe("saved");
    expect(records()).toEqual({ "u-1": "saved" });
    expect(save).toHaveBeenCalledWith(true);
  });

  it("opt-in is account-first: a failed save changes nothing", async () => {
    const { ph } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY });
    resolveAccountAnalytics("u-1", true);
    expect(await chooseAnalytics("u-1", true, fail)).toBe("failed");
    expect(ph.opt_in_capturing).not.toHaveBeenCalled();
    expect(getAnalyticsState()).toBe("off");
    expect(ph.identify).not.toHaveBeenCalled();
  });

  it("one choice at a time: a second toggle while a save is in flight is refused", async () => {
    await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY });
    resolveAccountAnalytics("u-1", false);
    let finish!: () => void;
    const save = vi.fn(() => new Promise<void>((r) => (finish = r)));
    const first = chooseAnalytics("u-1", false, save);
    expect(await chooseAnalytics("u-1", true, save)).toBe("busy");
    finish();
    await first;
    expect(save).toHaveBeenCalledTimes(1);
    expect(getAnalyticsState()).toBe("off");
  });

  it("an opt-in after a failed settings read opens the shut gate and identifies", async () => {
    const { ph } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY }, fakePosthog({ consent: "denied" }));
    holdAnalytics(); // the read failed: never resolved
    expect(await chooseAnalytics("u-1", true, ok)).toBe("saved");
    expect(gatedBeforeSend({ event: "x", uuid: "1", properties: {} } as unknown as CaptureResult)).not.toBeNull();
    expect(ph.identify).toHaveBeenCalledWith("u-1");
  });
});

describe("DNT / GPC is never persisted as the student's own opt-out", () => {
  it("GPC on → reset → GPC off: capture resumes and the switch follows", async () => {
    const { ph } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY });
    resolveAccountAnalytics("u-1", false);
    setGpc(true);
    expect(ph.get_explicit_consent_status()).toBe("denied"); // the getter folds GPC in
    expect(getAnalyticsState()).toBe("browser_blocked");
    resetAnalytics();
    expect(ph.opt_out_capturing).not.toHaveBeenCalled();
    setGpc(false);
    expect(ph.has_opted_out_capturing()).toBe(false);
    expect(getAnalyticsState()).toBe("on");
  });

  it("an account opt-out under GPC is still applied, so it outlives the signal", async () => {
    await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY });
    setGpc(true);
    resolveAccountAnalytics("u-1", true);
    setGpc(false);
    expect(getAnalyticsState()).toBe("off");
  });
});

describe("opt-out store", () => {
  it("is unavailable when analytics is off", async () => {
    await start({});
    expect(getAnalyticsState()).toBe("unavailable");
    expect(await chooseAnalytics("u-1", false, ok)).toBe("failed");
  });

  it("notifies subscribers on every change", async () => {
    await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY });
    const listener = vi.fn();
    const unsubscribe = subscribeAnalytics(listener);
    resolveAccountAnalytics("u-1", false);
    await chooseAnalytics("u-1", false, ok);
    await chooseAnalytics("u-1", true, ok);
    expect(listener).toHaveBeenCalledTimes(3);
    unsubscribe();
  });

  it("reports browser_blocked under Do Not Track / GPC", async () => {
    await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY });
    setGpc(true);
    expect(getAnalyticsState()).toBe("browser_blocked");
    setGpc(false);
    expect(getAnalyticsState()).toBe("on");
  });
});

describe("capture gate", () => {
  const pageview = () => ({ event: "$pageview", uuid: "x", properties: {} }) as unknown as CaptureResult;
  const click = () => ({ event: "$autocapture", uuid: "y", properties: {} }) as unknown as CaptureResult;

  it("is CLOSED from page load: nothing passes before_send until identity settles", async () => {
    await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY });
    expect(gatedBeforeSend(pageview())).toBeNull();
    expect(gatedBeforeSend(click())).toBeNull();
  });

  it("an anonymous visitor opens it, and the swallowed pageview is re-sent once", async () => {
    const { ph } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY });
    expect(gatedBeforeSend(pageview())).toBeNull();
    releaseAnonymousAnalytics();
    expect(ph.capture.mock.calls).toEqual([["$pageview"]]);
    expect(gatedBeforeSend(pageview())).not.toBeNull(); // the re-sent one passes
    releaseAnonymousAnalytics();
    expect(ph.capture).toHaveBeenCalledTimes(1);
  });

  it("the gate is already open when $identify is captured (it is an event too)", async () => {
    const { ph } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY });
    holdAnalytics();
    let passed: CaptureResult | null = null;
    ph.identify.mockImplementation(() => {
      passed = gatedBeforeSend({ event: "$identify", uuid: "i", properties: {} } as unknown as CaptureResult);
    });
    resolveAccountAnalytics("u-1", false);
    expect(passed).not.toBeNull();
  });

  it("a signed-in student: held until the preference arrives, then identified + pageview", async () => {
    const { ph } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY });
    holdAnalytics();
    expect(gatedBeforeSend(pageview())).toBeNull();
    expect(ph.identify).not.toHaveBeenCalled();
    resolveAccountAnalytics("u-1", false);
    expect(ph.identify.mock.calls).toEqual([["u-1"]]);
    expect(ph.capture.mock.calls).toEqual([["$pageview"]]);
    expect(ph.identify.mock.invocationCallOrder[0]).toBeLessThan(ph.capture.mock.invocationCallOrder[0]);
  });

  it("an opted-out student's swallowed pageview is not re-sent", async () => {
    const { ph } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY });
    holdAnalytics();
    gatedBeforeSend(pageview());
    resolveAccountAnalytics("u-1", true);
    expect(ph.capture).not.toHaveBeenCalled();
  });

  it("fails closed: no answer (the settings read failed) keeps the gate shut", async () => {
    const { ph } = await start({ NEXT_PUBLIC_POSTHOG_KEY: KEY });
    releaseAnonymousAnalytics();
    holdAnalytics();
    expect(gatedBeforeSend(pageview())).toBeNull();
    expect(gatedBeforeSend(click())).toBeNull();
    expect(ph.identify).not.toHaveBeenCalled();
  });

  it("an opt-out that arrives while posthog-js loads is applied before anything opens", async () => {
    const ph = fakePosthog();
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const pending = initAnalytics({ NEXT_PUBLIC_POSTHOG_KEY: KEY }, async () => {
      await gate;
      return ph as unknown as PostHog;
    });
    holdAnalytics();
    resolveAccountAnalytics("u-1", true);
    expect(gatedBeforeSend(pageview())).toBeNull();
    release();
    await pending;
    expect(ph.opt_out_capturing).toHaveBeenCalledTimes(1);
    expect(ph.identify).not.toHaveBeenCalled();
    expect(ph.capture).not.toHaveBeenCalled();
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
