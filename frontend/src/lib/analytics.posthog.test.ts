// @vitest-environment jsdom
/**
 * The REAL posthog-js, driven with buildPosthogConfig(): the sign-in handoff
 * on `/auth/callback?auth_token=…&user_id=…&avatar=…` must never leave the
 * browser — not in an event, and not in the `/flags` request body, which
 * carries `$initial_current_url` and which `before_send` never sees. That
 * body is only safe because `custom_personal_data_properties` masks the
 * params at the source; the control case below shows it leaks without it.
 *
 * Also driven with the real SDK: the capture gate (zero events before a
 * signed-in student's account preference resolves, and none at all for an
 * account opt-out or a failed read), and DNT/GPC surviving `reset()` without
 * being stored as an opt-out.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { gunzipSync } from "node:zlib";

import type { PostHog as PostHogType } from "posthog-js";

import {
  __resetAnalyticsForTests,
  buildPosthogConfig,
  getAnalyticsState,
  holdAnalytics,
  initAnalytics,
  releaseAnonymousAnalytics,
  resetAnalytics,
  resolveAccountAnalytics,
  setAnalyticsEnabled,
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

async function runSdk(overrides: Record<string, unknown>, name: string): Promise<Sent[]> {
  releaseAnonymousAnalytics(); // an anonymous page: the capture gate is open
  // Imported after fetch is stubbed: posthog-js captures `fetch` at load.
  const { PostHog } = await import("posthog-js");
  const ph = new PostHog();
  const config = buildPosthogConfig({ NEXT_PUBLIC_POSTHOG_KEY: "phc_test" });
  // A token per run: posthog-js persists `$initial_current_url` per token,
  // and the control case must not inherit the masked value.
  ph.init(
    `phc_${name}`,
    { ...config, api_host: "https://ph.test", request_batching: false, ...overrides },
    name,
  );
  ph.capture("probe_event");
  await vi.waitFor(() => expect(sent.some((s) => s.url.includes("/flags/"))).toBe(true));
  await new Promise((r) => setTimeout(r, 50));
  return sent;
}

describe("posthog-js masks the sign-in handoff at the source", () => {
  it("no request — events or /flags — carries the token, user id or avatar", async () => {
    const requests = await runSdk({}, "masked");
    expect(requests.length).toBeGreaterThan(1);
    for (const { url, body } of requests) {
      for (const needle of [SECRET, USER_ID, "AVATAR-ID", "#frag"]) {
        expect(`${url} ${body}`, `${needle} leaked to ${url}`).not.toContain(needle);
      }
    }
    // The /flags body — which before_send never sees — was masked by the SDK.
    const flags = requests.find((r) => r.url.includes("/flags/"))!;
    expect(flags.body).toContain("auth_token=<masked>");
  });

  it("control: without custom_personal_data_properties the /flags body leaks the token", async () => {
    const requests = await runSdk({ custom_personal_data_properties: [] }, "unmasked");
    const flags = requests.find((r) => r.url.includes("/flags/"))!;
    expect(flags.body).toContain(SECRET);
  });
});

/** Event requests only — `/flags` is a config read, not an event. */
function eventRequests(): Sent[] {
  // Only this suite's SDK (api_host "/ingest"); the masking tests above point
  // theirs at https://ph.test and may still flush a batch.
  return sent.filter((r) => r.url.startsWith("/ingest/") && !r.url.includes("/flags"));
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

describe("DNT / GPC across reset(), real posthog-js", () => {
  afterEach(() => {
    delete (navigator as { globalPrivacyControl?: boolean }).globalPrivacyControl;
  });

  it("GPC on → reset → GPC off: nothing was stored, capture resumes, the switch follows", async () => {
    const ph = await startRealSdk("phc_gpc_reset");
    releaseAnonymousAnalytics();
    Object.defineProperty(navigator, "globalPrivacyControl", { value: true, configurable: true });
    expect(ph.has_opted_out_capturing()).toBe(true); // respect_dnt
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
    releaseAnonymousAnalytics();
    setAnalyticsEnabled(false);
    resetAnalytics();
    expect(ph.get_explicit_consent_status()).toBe("denied");
    expect(getAnalyticsState()).toBe("off");
  });
});
