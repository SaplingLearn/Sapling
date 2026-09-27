// @vitest-environment jsdom
/**
 * The REAL posthog-js, driven through our config and helpers, wherever the
 * SDK's own behaviour is what matters:
 * - the `/auth/callback` handoff params are masked by the SDK itself before
 *   `before_send` ever sees an event (control case: without our list they
 *   are not), and nothing secret reaches the wire;
 * - feature flags are off: zero `/flags` requests, and while a student is
 *   opted out no request carries a distinct id or their UUID;
 * - a recorded opt-out applies from init (`opt_out_capturing_by_default`);
 * - the capture gate: zero events while a signed-in student's account
 *   preference is pending, none after an account opt-out, `$identify` +
 *   `$pageview` after a not-opted-out answer;
 * - DNT/GPC survives `reset()` without being stored as an opt-out;
 * - a shared browser hands over cleanly from an opted-out student to one
 *   who is not.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { gunzipSync } from "node:zlib";

import type { CaptureResult, PostHog as PostHogType } from "posthog-js";

import {
  __resetAnalyticsForTests,
  buildPosthogConfig,
  chooseAnalytics,
  gatedBeforeSend,
  getAnalyticsState,
  holdAnalytics,
  initAnalytics,
  OPT_OUT_RECORDS_KEY,
  releaseAnonymousAnalytics,
  resetAnalytics,
  resolveAccountAnalytics,
} from "./analytics";

const SECRET = "SECRET-HANDOFF-TOKEN";
const USER_ID = "3f1c0000-uuid-of-the-student";
const AVATAR = "https://lh3.googleusercontent.com/a/AVATAR-ID";

type Sent = { url: string; body: string };

function decode(body: unknown): string {
  if (typeof body === "string") return body;
  if (body instanceof ArrayBuffer || ArrayBuffer.isView(body)) {
    const buf = Buffer.from(body instanceof ArrayBuffer ? body : body.buffer);
    try {
      return gunzipSync(buf).toString("utf8");
    } catch {
      return buf.toString("utf8");
    }
  }
  return String(body ?? "");
}

let sent: Sent[];

beforeEach(() => {
  __resetAnalyticsForTests();
  localStorage.clear();
  sent = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string | URL, init?: RequestInit) => {
      sent.push({ url: String(url), body: decode(init?.body) });
      return new Response(JSON.stringify({ featureFlags: {}, flags: {} }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }),
  );
  const qs = new URLSearchParams({ user_id: USER_ID, avatar: AVATAR, auth_token: SECRET, is_approved: "true" });
  window.history.replaceState({}, "", `/auth/callback?${qs}#frag`);
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});

/** What the SDK handed to before_send, before our scrub ran. */
let preScrub: CaptureResult[];

async function runSdk(overrides: Record<string, unknown>, name: string): Promise<Sent[]> {
  preScrub = [];
  releaseAnonymousAnalytics(); // an anonymous page: the capture gate is open
  // Imported after fetch is stubbed: posthog-js captures `fetch` at load.
  const { PostHog } = await import("posthog-js");
  const ph = new PostHog();
  const config = buildPosthogConfig({ NEXT_PUBLIC_POSTHOG_KEY: "phc_test" });
  // A token per run: posthog-js persists `$initial_current_url` per token,
  // and the control case must not inherit the masked value.
  ph.init(
    `phc_${name}`,
    {
      ...config,
      api_host: "https://ph.test",
      request_batching: false,
      before_send: (e: CaptureResult | null) => {
        if (e) preScrub.push(JSON.parse(JSON.stringify(e)));
        return gatedBeforeSend(e);
      },
      ...overrides,
    },
    name,
  );
  ph.capture("probe_event");
  await vi.waitFor(() => expect(sent.some((s) => s.url.startsWith("https://ph.test/e/"))).toBe(true));
  await new Promise((r) => setTimeout(r, 50));
  return sent.filter((r) => r.url.startsWith("https://ph.test"));
}

function preScrubUrls(): string {
  return preScrub.map((e) => `${e.properties?.$current_url} ${JSON.stringify(e.$set_once ?? {})}`).join("\n");
}

describe("posthog-js masks the sign-in handoff at the source", () => {
  it("the SDK masks it before before_send, nothing secret is sent, and there is no /flags", async () => {
    const requests = await runSdk({}, "masked");
    // Masked by posthog-js itself — our scrub had not run yet.
    expect(preScrubUrls()).toContain("auth_token=<masked>");
    expect(preScrubUrls()).not.toContain(SECRET);
    expect(requests.some((r) => r.url.includes("/flags"))).toBe(false);
    for (const { url, body } of requests) {
      for (const needle of [SECRET, USER_ID, "AVATAR-ID", "#frag"]) {
        expect(`${url} ${body}`, `${needle} leaked to ${url}`).not.toContain(needle);
      }
    }
  });

  it("control: without custom_personal_data_properties the SDK itself carries the token", async () => {
    const requests = await runSdk({ custom_personal_data_properties: [] }, "unmasked");
    expect(preScrubUrls()).toContain(SECRET);
    // …and before_send's scrub is what still keeps it off the wire.
    expect(requests.map((r) => r.body).join("")).not.toContain(SECRET);
  });
});

/** Event requests only — not `/flags` or remote config. */
function eventRequests(): Sent[] {
  // Only this suite's SDK (api_host "/ingest"); the masking tests above point
  // theirs at https://ph.test and may still flush a batch.
  return sent.filter((r) => /^\/ingest\/(e|i\/v0\/e|batch|s)\//.test(r.url));
}

/** initAnalytics() with a fresh real posthog-js instance; api_host is `/ingest`. */
async function startRealSdk(key: string): Promise<PostHogType> {
  const { PostHog } = await import("posthog-js");
  const ph = new PostHog();
  expect(await initAnalytics({ NEXT_PUBLIC_POSTHOG_KEY: key }, async () => ph)).toBe(true);
  return ph;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

describe("capture gate, real posthog-js", () => {
  beforeEach(() => window.history.replaceState({}, "", "/dashboard"));

  it(
    "a signed-in student: ZERO events while the preference is pending, none after an account opt-out",
    async () => {
      const ph = await startRealSdk("phc_gate_optout");
      holdAnalytics(); // the UserProvider found a session user; GET /settings in flight
      ph.capture("probe_while_pending", {}, { send_instantly: true });
      // Longer than posthog-js's batch flush: the init $pageview/autocapture
      // would have gone by now had the gate let them through. This is also
      // the fail-closed case — a read that never answers sends nothing.
      await sleep(3500);
      expect(eventRequests()).toEqual([]);

      resolveAccountAnalytics("u-opted-out", true);
      expect(ph.get_explicit_consent_status()).toBe("denied");
      ph.capture("probe_after_optout", {}, { send_instantly: true });
      await sleep(300);
      expect(eventRequests()).toEqual([]);
      expect(JSON.stringify(sent)).not.toContain("u-opted-out");
    },
    10_000,
  );

  it("not opted out: nothing before the answer, then the identify and the initial pageview", async () => {
    const ph = await startRealSdk("phc_gate_optin");
    holdAnalytics();
    ph.capture("probe_while_pending", {}, { send_instantly: true });
    await sleep(200);
    expect(eventRequests()).toEqual([]);

    resolveAccountAnalytics("u-in", false);
    await vi.waitFor(
      () => {
        const bodies = eventRequests().map((r) => r.body).join("\n");
        expect(bodies).toContain("$identify");
        expect(bodies).toContain("$pageview");
      },
      { timeout: 6000, interval: 100 },
    );
    const bodies = eventRequests().map((r) => r.body).join("\n");
    expect(bodies).not.toContain("probe_while_pending");
    expect(bodies).toContain("u-in");
  }, 10_000);
});

describe("flags off + init-time opt-out, real posthog-js", () => {
  it(
    "a recorded opt-out applies at init: no /flags, no distinct id, no UUID — only remote config",
    async () => {
      window.history.replaceState({}, "", "/dashboard");
      const UUID = "9d0f0000-opted-out-student";
      localStorage.setItem("sapling_user", JSON.stringify({ id: UUID, name: "T" }));
      localStorage.setItem(OPT_OUT_RECORDS_KEY, JSON.stringify({ [UUID]: "saved" }));
      const ph = await startRealSdk("phc_init_optout");
      // opt_out_capturing_by_default: opted out before the account answered.
      expect(ph.has_opted_out_capturing()).toBe(true);
      holdAnalytics();
      resolveAccountAnalytics(UUID, true);
      ph.capture("probe_after", {}, { send_instantly: true });
      await sleep(1500);
      // With flags off posthog-js skips remote config too, so this is empty
      // (also observed in Chromium against the OpenNext worker); the regex
      // below is the most that would ever be allowed — config, no identity.
      const ours = sent.filter((r) => r.url.startsWith("/ingest/"));
      const distinctId = ph.get_distinct_id();
      for (const r of ours) {
        expect(r.url).toMatch(/^\/ingest\/array\/phc_init_optout\/config(\.js)?(\?|$)/);
        expect(`${r.url} ${r.body}`).not.toContain(distinctId);
        expect(`${r.url} ${r.body}`).not.toContain(UUID);
      }
      expect(ours.some((r) => r.url.includes("/flags"))).toBe(false);
      expect(ph.get_distinct_id()).not.toBe(UUID); // never identified
    },
  );
});

describe("DNT / GPC across reset(), real posthog-js", () => {
  afterEach(() => {
    delete (navigator as { globalPrivacyControl?: boolean }).globalPrivacyControl;
  });

  it("GPC on → reset → GPC off: nothing was stored, capture resumes, the switch follows", async () => {
    const ph = await startRealSdk("phc_gpc_reset");
    resolveAccountAnalytics("u-gpc", false);
    Object.defineProperty(navigator, "globalPrivacyControl", { value: true, configurable: true });
    expect(ph.has_opted_out_capturing()).toBe(true); // respect_dnt
    expect(ph.get_explicit_consent_status()).toBe("denied"); // even this getter folds GPC in
    expect(getAnalyticsState()).toBe("browser_blocked");
    resetAnalytics();
    delete (navigator as { globalPrivacyControl?: boolean }).globalPrivacyControl;
    expect(ph.get_explicit_consent_status()).toBe("pending"); // nothing was stored
    expect(ph.has_opted_out_capturing()).toBe(false);
    expect(getAnalyticsState()).toBe("on");
    ph.capture("probe_after_gpc", {}, { send_instantly: true });
    await vi.waitFor(() => expect(eventRequests().map((r) => r.body).join("")).toContain("probe_after_gpc"), {
      timeout: 3000,
    });
  });

  it("control: an opt-out the student chose IS carried across reset()", async () => {
    const ph = await startRealSdk("phc_gpc_control");
    resolveAccountAnalytics("u-choice", false);
    await chooseAnalytics("u-choice", false, () => Promise.resolve());
    resetAnalytics();
    expect(ph.get_explicit_consent_status()).toBe("denied");
    expect(getAnalyticsState()).toBe("off");
  });
});

describe("shared browser handover, real posthog-js", () => {
  it("student Y is captured and identified after opted-out student X signs out", async () => {
    window.history.replaceState({}, "", "/dashboard");
    const ph = await startRealSdk("phc_handover");
    resolveAccountAnalytics("u-X", true); // X's account says opted out
    expect(ph.get_explicit_consent_status()).toBe("denied");
    resetAnalytics(); // X signs out; the browser stays off meanwhile
    expect(ph.get_explicit_consent_status()).toBe("denied");
    holdAnalytics(); // Y signs in
    resolveAccountAnalytics("u-Y", false);
    expect(getAnalyticsState()).toBe("on");
    ph.capture("probe_for_Y", {}, { send_instantly: true });
    await vi.waitFor(
      () => {
        const bodies = eventRequests().map((r) => r.body).join("\n");
        expect(bodies).toContain("probe_for_Y");
        expect(bodies).toContain("u-Y");
      },
      { timeout: 4000 },
    );
    const bodies = eventRequests().map((r) => r.body).join("\n");
    expect(bodies).not.toContain("u-X"); // X was never identified
    expect(bodies).not.toContain("$opt_in"); // a re-derivation, not a new choice
  });
});
