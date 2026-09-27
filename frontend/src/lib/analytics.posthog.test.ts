// @vitest-environment jsdom
/**
 * The REAL posthog-js, driven with buildPosthogConfig(): the sign-in handoff
 * on `/auth/callback?auth_token=…&user_id=…&avatar=…` must never leave the
 * browser — not in an event, and not in the `/flags` request body, which
 * carries `$initial_current_url` and which `before_send` never sees. That
 * body is only safe because `custom_personal_data_properties` masks the
 * params at the source; the control case below shows it leaks without it.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { gunzipSync } from "node:zlib";

import { buildPosthogConfig } from "./analytics";

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
