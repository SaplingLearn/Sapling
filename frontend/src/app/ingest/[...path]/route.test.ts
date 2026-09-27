/**
 * The /ingest route handler: streams the batch upstream (no buffering),
 * never forwards the student's cookie or IP, refuses traversal, and marks
 * versioned SDK bundles immutable.
 */
import { describe, it, expect, vi, afterEach } from "vitest";

import { GET, POST } from "./route";

type Call = { url: string; init: RequestInit & { duplex?: string } };

function stubUpstream(response: () => Response): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url: String(url), init });
      return response();
    }),
  );
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

describe("POST /ingest/*", () => {
  it("streams the body upstream with duplex 'half' and no cookie or client IP", async () => {
    const calls = stubUpstream(() => new Response('{"status":1}', { status: 200 }));
    const payload = JSON.stringify({ api_key: "phc_x", batch: [{ event: "$pageview" }] });
    const res = await POST(
      new Request("https://saplinglearn.com/ingest/e/?ver=1", {
        method: "POST",
        body: payload,
        headers: {
          "content-type": "application/json",
          cookie: "sapling_session=secret.token",
          "cf-connecting-ip": "203.0.113.9",
          "x-forwarded-for": "203.0.113.9",
        },
      }),
    );
    expect(res.status).toBe(200);
    expect(calls).toHaveLength(1);
    const { url, init } = calls[0];
    expect(url).toBe("https://us.i.posthog.com/e/?ver=1");
    expect(init.body).toBeInstanceOf(ReadableStream);
    expect(init.duplex).toBe("half");
    expect(await new Response(init.body as ReadableStream).text()).toBe(payload);
    const headers = init.headers as Headers;
    expect(headers.get("cookie")).toBeNull();
    expect(headers.get("cf-connecting-ip")).toBeNull();
    expect(headers.get("x-forwarded-for")).toBeNull();
    expect(headers.get("content-type")).toBe("application/json");
  });

  it("a PostHog outage is a quiet 502", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("down"); }));
    const res = await POST(new Request("https://saplinglearn.com/ingest/e/", { method: "POST", body: "{}" }));
    expect(res.status).toBe(502);
  });
});

describe("GET /ingest/*", () => {
  it("refuses encoded traversal without calling upstream", async () => {
    const calls = stubUpstream(() => new Response("x"));
    const res = await GET(new Request("https://saplinglearn.com/ingest/static/%2E%2E%2Fflags/"));
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
    const res = await GET(new Request("https://saplinglearn.com/ingest/static/surveys.js?v=1.434.15"));
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
        headers: { "if-none-match": '"e1"', cookie: "sapling_session=secret" },
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
    const res = await GET(new Request("https://saplinglearn.com/ingest/static/surveys.js?v=9"));
    expect(res.status).toBe(404);
    expect(res.headers.get("cache-control")).toBe("no-store");
  });
});
