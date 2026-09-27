/**
 * The /ingest route handler: streams the batch upstream (no buffering),
 * never forwards the student's cookie or IP, refuses traversal, marks
 * versioned SDK bundles immutable — and is not an open relay: only the
 * SDK's own endpoints, only with a `sapling_session` that verifies, bodies
 * capped at 1 MiB, and only events for this deployment's project key.
 */
import { describe, it, expect, vi, afterEach, beforeAll, beforeEach } from "vitest";

import { MAX_INGEST_BODY_BYTES } from "@/lib/ingestProxy";
import { signSession } from "@/lib/sessionToken";

import { GET, HEAD, POST } from "./route";

type Call = { url: string; init: RequestInit & { duplex?: string } };

const SECRET = "route-test-session-secret-at-least-32-bytes";
const KEY = "phc_ours";
let SESSION: { cookie: string };
/** A minimal event body for THIS project. */
const EVENT = JSON.stringify({ event: "$pageview", properties: { token: KEY } });

beforeAll(async () => {
  vi.stubEnv("SESSION_SECRET", SECRET);
  SESSION = { cookie: `theme=dark; sapling_session=${await signSession("u-1")}` };
  vi.unstubAllEnvs();
});
beforeEach(() => {
  vi.stubEnv("SESSION_SECRET", SECRET);
  vi.stubEnv("NEXT_PUBLIC_POSTHOG_KEY", KEY);
});

function stubUpstream(response: () => Response, consumeBody = false): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url: String(url), init });
      // Like a real fetch: read the (possibly capped) body to the end.
      if (consumeBody && init.body) await new Response(init.body as ReadableStream).arrayBuffer();
      return response();
    }),
  );
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("POST /ingest/e/", () => {
  it("forwards the (capped, checked) body with no cookie or client IP", async () => {
    const calls = stubUpstream(() => new Response('{"status":1}', { status: 200 }));
    const payload = JSON.stringify({ api_key: KEY, batch: [{ event: "$pageview", properties: { token: KEY } }] });
    const res = await POST(
      new Request("https://saplinglearn.com/ingest/e/?ver=1", {
        method: "POST",
        body: payload,
        headers: {
          ...SESSION,
          "content-type": "application/json",
          "cf-connecting-ip": "203.0.113.9",
          "x-forwarded-for": "203.0.113.9",
        },
      }),
    );
    expect(res.status).toBe(200);
    expect(calls).toHaveLength(1);
    const { url, init } = calls[0];
    expect(url).toBe("https://us.i.posthog.com/e/?ver=1");
    expect(new TextDecoder().decode(init.body as Uint8Array)).toBe(payload);
    const headers = init.headers as Headers;
    expect(headers.get("cookie")).toBeNull();
    expect(headers.get("cf-connecting-ip")).toBeNull();
    expect(headers.get("x-forwarded-for")).toBeNull();
    expect(headers.get("content-type")).toBe("application/json");
  });

  it("a PostHog outage is a quiet 502", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("down"); }));
    const res = await POST(
      new Request("https://saplinglearn.com/ingest/e/", { method: "POST", body: EVENT, headers: SESSION }),
    );
    expect(res.status).toBe(502);
  });
});

describe("not an open relay", () => {
  it("403 without a sapling_session that verifies — forged, expired or missing — upstream never called", async () => {
    const calls = stubUpstream(() => new Response("x"));
    vi.stubEnv("SESSION_SECRET", "a-different-secret-that-is-also-32-bytes-long");
    const forgedElsewhere = await signSession("u-1"); // signed with the wrong secret
    vi.stubEnv("SESSION_SECRET", SECRET);
    const [payload] = SESSION.cookie.split("sapling_session=")[1].split(".");
    for (const cookie of [
      undefined,
      "theme=dark",
      "sapling_session=",
      "not_sapling_session=x",
      "sapling_session=secret.token", // merely present
      `sapling_session=${forgedElsewhere}`,
      `sapling_session=${payload}.AAAA`, // real payload, bad signature
    ]) {
      const res = await POST(
        new Request("https://saplinglearn.com/ingest/e/", {
          method: "POST",
          body: EVENT,
          headers: cookie ? { cookie } : {},
        }),
      );
      expect(res.status, String(cookie)).toBe(403);
    }
    expect((await GET(new Request("https://saplinglearn.com/ingest/static/surveys.js?v=1"))).status).toBe(403);
    expect(calls).toHaveLength(0);
  });

  it("404 for endpoints this SDK config never uses (flags, config, decide, recording) or wrong methods", async () => {
    const calls = stubUpstream(() => new Response("x"));
    const post = (p: string) =>
      POST(new Request(`https://saplinglearn.com/ingest${p}`, { method: "POST", body: EVENT, headers: SESSION }));
    const get = (p: string) => GET(new Request(`https://saplinglearn.com/ingest${p}`, { headers: SESSION }));
    for (const p of ["/flags/?v=2", "/decide/?v=3", "/s/", "/capture/", "/engage/", "/static/array.js"]) {
      expect((await post(p)).status, `POST ${p}`).toBe(404);
    }
    for (const p of ["/array/phc_x/config.js", "/array/phc_x/config", "/e/", "/api/projects/", "/static/x.css"]) {
      expect((await get(p)).status, `GET ${p}`).toBe(404);
    }
    expect(calls).toHaveLength(0);
  });

  it("the SDK's own endpoints pass: event POSTs and static bundle GET/HEAD", async () => {
    const calls = stubUpstream(() => new Response("ok"));
    for (const p of ["/e/", "/i/v0/e/", "/batch/"]) {
      const res = await POST(
        new Request(`https://saplinglearn.com/ingest${p}`, { method: "POST", body: EVENT, headers: SESSION }),
      );
      expect(res.status, p).toBe(200);
    }
    for (const p of ["/static/surveys.js?v=1.434.15", "/static/1.434.15/recorder.js"]) {
      expect((await GET(new Request(`https://saplinglearn.com/ingest${p}`, { headers: SESSION }))).status).toBe(200);
      expect(
        (await HEAD(new Request(`https://saplinglearn.com/ingest${p}`, { method: "HEAD", headers: SESSION }))).status,
      ).toBe(200);
    }
    expect(calls).toHaveLength(7);
  });

  it("403 for an event body naming another PostHog project — upstream never called", async () => {
    const calls = stubUpstream(() => new Response("x"));
    for (const body of [
      JSON.stringify({ event: "$pageview", properties: { token: "phc_someone_else" } }),
      JSON.stringify({ api_key: KEY, batch: [{ event: "x", properties: { token: "phc_someone_else" } }] }),
      JSON.stringify({ event: "$pageview", properties: {} }),
    ]) {
      const res = await POST(new Request("https://saplinglearn.com/ingest/e/", { method: "POST", body, headers: SESSION }));
      expect(res.status, body).toBe(403);
    }
    // …and everything is refused when this build has no key.
    vi.stubEnv("NEXT_PUBLIC_POSTHOG_KEY", "");
    const res = await POST(new Request("https://saplinglearn.com/ingest/e/", { method: "POST", body: EVENT, headers: SESSION }));
    expect(res.status).toBe(403);
    expect(calls).toHaveLength(0);
  });

  it("400 for a compressed or unparseable body — nothing is decompressed", async () => {
    const calls = stubUpstream(() => new Response("x"));
    for (const [search, body] of [["?compression=gzip-js", EVENT], ["", "not json"]] as const) {
      const res = await POST(
        new Request(`https://saplinglearn.com/ingest/e/${search}`, { method: "POST", body, headers: SESSION }),
      );
      expect(res.status).toBe(400);
    }
    expect(calls).toHaveLength(0);
  });

  it("413 when Content-Length declares more than the cap — upstream never called", async () => {
    const calls = stubUpstream(() => new Response("x"));
    const res = await POST(
      new Request("https://saplinglearn.com/ingest/e/", {
        method: "POST",
        body: "{}",
        headers: { ...SESSION, "content-length": String(MAX_INGEST_BODY_BYTES + 1) },
      }),
    );
    expect(res.status).toBe(413);
    expect(calls).toHaveLength(0);
  });

  it("413 when a streamed body (no or false length) runs past the cap", async () => {
    const calls = stubUpstream(() => new Response("x"), true);
    const big = new Uint8Array(64 * 1024);
    let sent = 0;
    const body = new ReadableStream<Uint8Array>({
      pull(controller) {
        if (sent > MAX_INGEST_BODY_BYTES + big.length) return controller.close();
        sent += big.length;
        controller.enqueue(big);
      },
    });
    const res = await POST(
      new Request("https://saplinglearn.com/ingest/e/", {
        method: "POST",
        body,
        headers: SESSION,
        // @ts-expect-error — `duplex` is required for a stream body but missing from lib.dom
        duplex: "half",
      }),
    );
    expect(res.status).toBe(413);
    expect(calls).toHaveLength(0);
  });

  it("a body under the cap goes through whole", async () => {
    const calls = stubUpstream(() => new Response("ok"));
    const payload = JSON.stringify({ event: "$pageview", properties: { token: KEY, pad: "x".repeat(200_000) } });
    const res = await POST(
      new Request("https://saplinglearn.com/ingest/e/", { method: "POST", body: payload, headers: SESSION }),
    );
    expect(res.status).toBe(200);
    expect(new TextDecoder().decode(calls[0].init.body as Uint8Array)).toBe(payload);
  });
});

describe("GET /ingest/static/*", () => {
  it("refuses encoded traversal without calling upstream", async () => {
    const calls = stubUpstream(() => new Response("x"));
    const res = await GET(new Request("https://saplinglearn.com/ingest/static/%2E%2E%2Fflags/", { headers: SESSION }));
    expect(res.status).toBe(404);
    expect(calls).toHaveLength(0);
  });

  it("marks a versioned SDK bundle immutable, and sends no body upstream for GET", async () => {
    const calls = stubUpstream(
      () =>
        new Response("/* js */", {
          status: 200,
          headers: { "cache-control": "public, max-age=14400", "content-type": "application/javascript", "set-cookie": "x=1" },
        }),
    );
    const res = await GET(new Request("https://saplinglearn.com/ingest/static/surveys.js?v=1.434.15", { headers: SESSION }));
    expect(calls[0].url).toBe("https://us-assets.i.posthog.com/static/surveys.js?v=1.434.15");
    expect(calls[0].init.body).toBeUndefined();
    expect(res.headers.get("cache-control")).toBe("public, max-age=31536000, immutable");
    expect(res.headers.get("set-cookie")).toBeNull();
    expect(await res.text()).toBe("/* js */");
  });

  it("forwards revalidation headers and passes a 304 back, still immutable", async () => {
    const calls = stubUpstream(() => new Response(null, { status: 304, headers: { etag: '"e1"' } }));
    const res = await GET(
      new Request("https://saplinglearn.com/ingest/static/surveys.js?v=1.434.15", {
        headers: { "if-none-match": '"e1"', ...SESSION },
      }),
    );
    const sent = calls[0].init.headers as Headers;
    expect(sent.get("if-none-match")).toBe('"e1"');
    expect(sent.get("cookie")).toBeNull();
    expect(res.status).toBe(304);
    expect(res.headers.get("etag")).toBe('"e1"');
    expect(res.headers.get("cache-control")).toBe("public, max-age=31536000, immutable");
  });

  it("does not mark an error response immutable", async () => {
    stubUpstream(() => new Response("nope", { status: 404, headers: { "cache-control": "no-store" } }));
    const res = await GET(new Request("https://saplinglearn.com/ingest/static/surveys.js?v=9", { headers: SESSION }));
    expect(res.status).toBe(404);
    expect(res.headers.get("cache-control")).toBe("no-store");
  });
});
