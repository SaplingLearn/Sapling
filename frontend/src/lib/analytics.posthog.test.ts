// @vitest-environment jsdom
/**
 * The REAL posthog-js, driven through src/lib/analytics.ts, wherever the
 * SDK's own behaviour is what matters:
 * - anonymous page / opted-out student / failed account read / a signed-in
 *   student on a public page → zero requests (posthog-js never loads);
 * - leaving the app shell (Settings → /privacy) drops capture for that page
 *   at once, and returning resumes it;
 * - no autocapture: a clicked link never sends `attr__href` or
 *   `$elements_chain`;
 * - an allowed student → `$identify` + exactly one `$pageview`, no `/flags`;
 * - opting out mid-page stops capture at once; opting in captures only after
 *   the account save succeeded; a stale account read after a toggle is
 *   ignored;
 * - nothing is written to cookies, localStorage or sessionStorage;
 * - the `/auth/callback` handoff params are masked by the SDK itself before
 *   `before_send` runs (control case: without our list they are not), and
 *   nothing secret reaches the wire.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { gunzipSync } from "node:zlib";

import type { CaptureResult, PostHog as PostHogType } from "posthog-js";

import {
  __analyticsLoadedForTests,
  __resetAnalyticsForTests,
  applyAccountAnalytics,
  beginAccountRead,
  resumeAnalytics,
  buildPosthogConfig,
  chooseAnalytics,
  scrubEvent,
  stopAnalytics,
} from "./analytics";

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
let instances: PostHogType[];

function storageSnapshot(): string {
  const keys = (st: Storage) => Array.from({ length: st.length }, (_, i) => st.key(i)).sort().join(",");
  return `local=[${keys(localStorage)}] session=[${keys(sessionStorage)}] cookie=[${document.cookie}]`;
}

beforeEach(() => {
  sent = [];
  instances = [];
  localStorage.clear();
  sessionStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string | URL, init?: RequestInit) => {
      sent.push({ url: String(url), body: decode(init?.body) });
      return new Response(JSON.stringify({ status: 1 }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }),
  );
  window.history.replaceState({}, "", "/dashboard");
  __resetAnalyticsForTests({
    env: { NEXT_PUBLIC_POSTHOG_KEY: `phc_real_${Math.random().toString(36).slice(2, 8)}` },
    load: async () => {
      // Imported after fetch is stubbed: posthog-js captures `fetch` at load.
      const { PostHog } = await import("posthog-js");
      const ph = new PostHog();
      instances.push(ph);
      return ph;
    },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
/** Longer than posthog-js's 3 s batch flush. */
const FLUSH = 3500;

/** Our SDK's requests (api_host "/ingest"); the masking runs use ph.test. */
function ingest(): Sent[] {
  return sent.filter((r) => r.url.startsWith("/ingest/"));
}
function eventBodies(): string {
  return ingest()
    .filter((r) => /^\/ingest\/(e|i\/v0\/e|batch|s)\//.test(r.url))
    .map((r) => r.body)
    .join("\n");
}
function count(haystack: string, needle: string): number {
  return haystack.split(needle).length - 1;
}

async function signIn(userId: string, optOut: unknown) {
  const gen = beginAccountRead(userId);
  applyAccountAnalytics(gen, userId, optOut);
  return (await __analyticsLoadedForTests()) as PostHogType | null;
}

describe("zero requests unless allowed, real posthog-js", () => {
  it("anonymous page: posthog-js never loads, zero requests", async () => {
    stopAnalytics();
    await sleep(300);
    expect(instances).toHaveLength(0);
    expect(ingest()).toEqual([]);
  });

  it("signed in, account opted out: zero requests", async () => {
    expect(await signIn("u-out", true)).toBeNull();
    await sleep(300);
    expect(instances).toHaveLength(0);
    expect(ingest()).toEqual([]);
  });

  it("signed in, account read fails (no answer): zero requests", async () => {
    beginAccountRead("u-fail");
    await sleep(300);
    expect(instances).toHaveLength(0);
    expect(ingest()).toEqual([]);
  });
});

describe("app-shell routes only, real posthog-js", () => {
  for (const path of ["/", "/privacy", "/auth/callback"]) {
    it(`signed in on ${path}: posthog-js never loads, zero requests`, async () => {
      window.history.replaceState({}, "", path);
      expect(await signIn("u-public", false)).toBeNull();
      resumeAnalytics();
      await sleep(300);
      expect(instances).toHaveLength(0);
      expect(ingest()).toEqual([]);
    });
  }

  it(
    "Settings → /privacy drops capture for that page at once; back in the shell it resumes",
    async () => {
      window.history.replaceState({}, "", "/settings");
      const ph = (await signIn("u-nav", false))!;
      await vi.waitFor(() => expect(eventBodies()).toContain("/settings"), { timeout: FLUSH + 2000 });
      window.history.pushState({}, "", "/privacy"); // posthog-js captures a history_change pageview here
      ph.capture("probe_on_privacy", {}, { send_instantly: true });
      window.history.pushState({}, "", "/dashboard");
      ph.capture("probe_back_in_shell", {}, { send_instantly: true });
      await vi.waitFor(() => expect(eventBodies()).toContain("probe_back_in_shell"), { timeout: 3000 });
      await sleep(FLUSH);
      const bodies = eventBodies();
      expect(bodies).not.toContain("probe_on_privacy");
      expect(bodies).not.toContain("/privacy");
    },
    15_000,
  );
});

describe("an allowed student, real posthog-js", () => {
  it(
    "$identify + exactly ONE $pageview, no /flags, nothing stored in the browser",
    async () => {
      const before = storageSnapshot();
      const ph = await signIn("u-allowed", false);
      expect(ph).not.toBeNull();
      await vi.waitFor(() => expect(eventBodies()).toContain("$pageview"), { timeout: FLUSH + 2000 });
      await sleep(FLUSH);
      const bodies = eventBodies();
      expect(count(bodies, '"event":"$identify"')).toBe(1);
      expect(count(bodies, '"event":"$pageview"')).toBe(1);
      expect(bodies).toContain("u-allowed");
      expect(ingest().some((r) => r.url.includes("/flags"))).toBe(false);
      expect(storageSnapshot()).toBe(before);
    },
    15_000,
  );

  it(
    "no autocapture: clicking a link sends no attr__href / $elements_chain",
    async () => {
      await signIn("u-click", false);
      const a = document.createElement("a");
      a.href = "/notetaker?note=secret-note-id";
      a.textContent = "My private note title";
      document.body.appendChild(a);
      a.addEventListener("click", (e) => e.preventDefault());
      a.click();
      a.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await sleep(FLUSH);
      const bodies = eventBodies();
      expect(bodies).toContain("$pageview"); // capture is running…
      expect(bodies).not.toContain("$autocapture"); // …but not autocapture
      expect(bodies).not.toContain("attr__href");
      expect(bodies).not.toContain("$elements_chain");
      expect(bodies).not.toContain("secret-note-id");
      expect(bodies).not.toContain("My private note title");
      a.remove();
    },
    10_000,
  );

  it("opting out mid-page stops capture at once (before the save resolves)", async () => {
    const ph = (await signIn("u-mid", false))!;
    let finish!: () => void;
    const done = chooseAnalytics("u-mid", false, () => new Promise<void>((r) => (finish = r)));
    ph.capture("probe_after_optout", {}, { send_instantly: true });
    await sleep(300);
    expect(eventBodies()).not.toContain("probe_after_optout");
    finish();
    await done;
    ph.capture("probe_after_save", {}, { send_instantly: true });
    await sleep(300);
    expect(eventBodies()).not.toContain("probe_after_save");
  });

  it("opting in captures only after the account save succeeded", async () => {
    await signIn("u-in", true);
    let finish!: () => void;
    const done = chooseAnalytics("u-in", true, () => new Promise<void>((r) => (finish = r)));
    await sleep(300);
    expect(instances).toHaveLength(0); // not even loaded while the save is pending
    expect(ingest()).toEqual([]);
    finish();
    expect(await done).toBe("saved");
    const ph = (await __analyticsLoadedForTests())!;
    ph.capture("probe_after_optin", {}, { send_instantly: true });
    await vi.waitFor(() => expect(eventBodies()).toContain("probe_after_optin"), { timeout: 3000 });
    expect(eventBodies()).toContain("u-in");
  });

  it("an account read that started before a toggle is ignored when it lands", async () => {
    const ph = (await signIn("u-stale", false))!;
    const staleGen = beginAccountRead("u-stale");
    await chooseAnalytics("u-stale", false, () => Promise.resolve());
    applyAccountAnalytics(staleGen, "u-stale", false); // the stale "allowed" answer
    ph.capture("probe_after_stale", {}, { send_instantly: true });
    await sleep(300);
    expect(eventBodies()).not.toContain("probe_after_stale");
  });
});

// ── masking at the source ───────────────────────────────────────────────────

const SECRET = "SECRET-HANDOFF-TOKEN";
const USER_ID = "3f1c0000-uuid-of-the-student";
const AVATAR = "https://lh3.googleusercontent.com/a/AVATAR-ID";

let preScrub: CaptureResult[];

async function runMaskingSdk(overrides: Record<string, unknown>, name: string): Promise<Sent[]> {
  preScrub = [];
  const qs = new URLSearchParams({ user_id: USER_ID, avatar: AVATAR, auth_token: SECRET, is_approved: "true" });
  window.history.replaceState({}, "", `/auth/callback?${qs}#frag`);
  const { PostHog } = await import("posthog-js");
  const ph = new PostHog();
  ph.init(
    `phc_${name}`,
    {
      ...buildPosthogConfig({ NEXT_PUBLIC_POSTHOG_KEY: "phc_test" }),
      api_host: "https://ph.test",
      request_batching: false,
      before_send: (e: CaptureResult | null) => {
        if (e) preScrub.push(JSON.parse(JSON.stringify(e)));
        return scrubEvent(e);
      },
      ...overrides,
    },
    name,
  );
  ph.capture("probe_event");
  await vi.waitFor(() => expect(sent.some((s) => s.url.startsWith("https://ph.test/e/"))).toBe(true));
  await sleep(50);
  return sent.filter((r) => r.url.startsWith("https://ph.test"));
}

function preScrubUrls(): string {
  return preScrub.map((e) => `${e.properties?.$current_url} ${JSON.stringify(e.$set_once ?? {})}`).join("\n");
}

describe("posthog-js masks the sign-in handoff at the source", () => {
  it("the SDK masks it before before_send, nothing secret is sent, and there is no /flags", async () => {
    const requests = await runMaskingSdk({}, "masked");
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
    const requests = await runMaskingSdk({ custom_personal_data_properties: [] }, "unmasked");
    expect(preScrubUrls()).toContain(SECRET);
    // …and before_send's scrub is what still keeps it off the wire.
    expect(requests.map((r) => r.body).join("")).not.toContain(SECRET);
  });
});
