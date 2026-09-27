/**
 * The /ingest PostHog proxy must route to the right PostHog host and must
 * never forward the student's cookies (the `sapling_session` credential) or
 * let PostHog set cookies on the app's domain.
 */
import { describe, it, expect } from "vitest";

import {
  IMMUTABLE_CACHE_CONTROL,
  downstreamResponseHeaders,
  ingestTokens,
  ingestTokensOk,
  isAllowedIngestRequest,
  readCappedBody,
  sessionTokenFrom,
  isImmutableAsset,
  normalisedIngestPath,
  upstreamRequestHeaders,
  upstreamTarget,
} from "./ingestProxy";

/** The upstream URL the proxy would call, or null when it refuses. */
const upstreamUrl = (pathname: string, search: string) => upstreamTarget(pathname, search)?.url ?? null;

describe("upstreamTarget", () => {
  it("routes events and flags to the ingestion host, keeping trailing slash + query", () => {
    expect(upstreamUrl("/ingest/e/", "?ip=0&_=1&ver=1.2")).toBe("https://us.i.posthog.com/e/?ip=0&_=1&ver=1.2");
    expect(upstreamUrl("/ingest/flags/", "?v=2")).toBe("https://us.i.posthog.com/flags/?v=2");
    expect(upstreamUrl("/ingest/i/v0/e/", "")).toBe("https://us.i.posthog.com/i/v0/e/");
  });

  it("routes static bundles and remote config to the assets host", () => {
    expect(upstreamUrl("/ingest/static/array.js", "")).toBe("https://us-assets.i.posthog.com/static/array.js");
    expect(upstreamUrl("/ingest/array/phc_x/config.js", "")).toBe(
      "https://us-assets.i.posthog.com/array/phc_x/config.js",
    );
  });

  it("refuses anything outside /ingest/ or with traversal", () => {
    expect(upstreamUrl("/ingest", "")).toBeNull();
    expect(upstreamUrl("/api/auth/me", "")).toBeNull();
    expect(upstreamUrl("/ingest/../api", "")).toBeNull();
    expect(upstreamUrl("/ingest//evil.com/x", "")).toBeNull();
  });

  it("refuses percent-encoded traversal in any case, before decoding", () => {
    for (const path of [
      "/ingest/%2e%2e/api/auth/me",
      "/ingest/%2E%2E/api",
      "/ingest/static/%2e%2e/flags/",
      "/ingest/static/..%2fflags/",
      "/ingest/static/%2E%2E%2Fflags/",
      "/ingest/static%2f..%2f..%2fapi",
      "/ingest/static/%5c..%5cflags",
      "/ingest/static/.%2e/e/",
      "/ingest/%252e%252e/api", // double-encoded
      "/ingest/static/./array.js",
      "/ingest/static/../e/",
      "/ingest/e\\..\\x",
      "/ingest/%zz/e/", // malformed escape
      "/ingest/e/%0d%0aHost:%20evil",
    ]) {
      expect(upstreamUrl(path, ""), path).toBeNull();
      expect(normalisedIngestPath(path), path).toBeNull();
    }
  });

  it("routes on the NORMALISED path: an encoded static/ prefix cannot pick the assets host", () => {
    // Harmless percent-encoding of ordinary characters decodes, and the
    // decoded path is what decides the host and what goes upstream.
    expect(normalisedIngestPath("/ingest/%65/")).toBe("/e/");
    expect(upstreamUrl("/ingest/%65/", "")).toBe("https://us.i.posthog.com/e/");
    expect(upstreamUrl("/ingest/%73tatic/array.js", "")).toBe("https://us-assets.i.posthog.com/static/array.js");
    // Every accepted target stays on a PostHog host.
    for (const path of ["/ingest/e/", "/ingest/static/array.js", "/ingest/array/phc_x/config.js"]) {
      const url = new URL(upstreamUrl(path, "?x=1")!);
      expect(["us.i.posthog.com", "us-assets.i.posthog.com"]).toContain(url.hostname);
    }
  });
});

describe("immutable asset caching", () => {
  it("only versioned /static/ bundles are immutable", () => {
    expect(isImmutableAsset("/static/surveys.js", "?v=1.434.15")).toBe(true);
    expect(isImmutableAsset("/static/array.js", "")).toBe(false);
    expect(isImmutableAsset("/array/phc_x/config.js", "?v=1")).toBe(false);
    expect(isImmutableAsset("/e/", "?v=1")).toBe(false);
    // posthog-js's semver asset paths are versioned too.
    expect(isImmutableAsset("/static/1.434.15/surveys.js", "")).toBe(true);
    expect(isImmutableAsset("/static/1.434.15-beta.1/recorder.js", "")).toBe(true);
    expect(isImmutableAsset("/static/latest/surveys.js", "")).toBe(false);
  });

  it("shares one mount point with posthog-js's api_host", async () => {
    const { buildPosthogConfig } = await import("./analytics");
    const { INGEST_PREFIX } = await import("./ingestProxy");
    expect(buildPosthogConfig({ NEXT_PUBLIC_POSTHOG_KEY: "phc_x" }).api_host).toBe(INGEST_PREFIX);
  });

  it("upstreamTarget validates once and hands back the normalised path", () => {
    expect(upstreamTarget("/ingest/%73tatic/surveys.js", "?v=1")).toEqual({
      url: "https://us-assets.i.posthog.com/static/surveys.js?v=1",
      path: "/static/surveys.js",
    });
    expect(upstreamTarget("/ingest/static/%2e%2e/e/", "?v=1")).toBeNull();
  });

  it("overrides PostHog's short max-age for them", () => {
    const upstream = new Headers({ "cache-control": "public, max-age=14400", "content-type": "application/javascript" });
    expect(downstreamResponseHeaders(upstream, { immutable: true }).get("cache-control")).toBe(IMMUTABLE_CACHE_CONTROL);
    expect(downstreamResponseHeaders(upstream).get("cache-control")).toBe("public, max-age=14400");
  });
});

describe("header allowlists", () => {
  it("drops cookies, auth, host and client-IP headers on the way up", () => {
    const up = upstreamRequestHeaders(
      new Headers({
        cookie: "sapling_session=secret.token",
        authorization: "Bearer x",
        host: "saplinglearn.com",
        "x-forwarded-for": "203.0.113.9",
        "cf-connecting-ip": "203.0.113.9",
        "content-type": "text/plain",
        "user-agent": "UA/1.0",
        "if-none-match": '"etag-1"',
        "if-modified-since": "Sat, 26 Sep 2026 16:47:13 GMT",
      }),
    );
    // Conditional headers pass, so revalidation can come back 304.
    expect(up.get("if-none-match")).toBe('"etag-1"');
    expect(up.get("if-modified-since")).toBe("Sat, 26 Sep 2026 16:47:13 GMT");
    expect(up.get("cookie")).toBeNull();
    expect(up.get("authorization")).toBeNull();
    expect(up.get("host")).toBeNull();
    expect(up.get("x-forwarded-for")).toBeNull();
    expect(up.get("cf-connecting-ip")).toBeNull();
    expect(up.get("content-type")).toBe("text/plain");
    expect(up.get("user-agent")).toBe("UA/1.0");
  });

  it("never passes set-cookie or a stale content-encoding back down", () => {
    const down = downstreamResponseHeaders(
      new Headers({
        "set-cookie": "ph=1; Domain=saplinglearn.com",
        "content-encoding": "gzip",
        "content-length": "10",
        "content-type": "application/json",
        "cache-control": "public, max-age=300",
      }),
    );
    expect(down.get("set-cookie")).toBeNull();
    expect(down.get("content-encoding")).toBeNull();
    expect(down.get("content-length")).toBeNull();
    expect(down.get("content-type")).toBe("application/json");
    expect(down.get("cache-control")).toBe("public, max-age=300");
  });
});

describe("relay guards", () => {
  it("allows exactly the SDK's event endpoints (POST) and static bundles (GET/HEAD)", () => {
    for (const p of ["/e/", "/i/v0/e/", "/batch/"]) {
      expect(isAllowedIngestRequest("POST", p), p).toBe(true);
      expect(isAllowedIngestRequest("GET", p), p).toBe(false);
    }
    for (const p of ["/static/surveys.js", "/static/1.434.15/recorder.js"]) {
      expect(isAllowedIngestRequest("GET", p), p).toBe(true);
      expect(isAllowedIngestRequest("HEAD", p), p).toBe(true);
      expect(isAllowedIngestRequest("POST", p), p).toBe(false);
    }
    for (const p of ["/flags/", "/decide/", "/array/phc_x/config.js", "/array/phc_x/config", "/s/", "/e", "/static/x.css", "/static/a/b/c.js"]) {
      expect(isAllowedIngestRequest("POST", p), p).toBe(false);
      expect(isAllowedIngestRequest("GET", p), p).toBe(false);
    }
  });

  it("sessionTokenFrom reads a non-empty sapling_session, by exact name", () => {
    const h = (cookie?: string) => new Headers(cookie ? { cookie } : {});
    expect(sessionTokenFrom(h("sapling_session=abc"))).toBe("abc");
    expect(sessionTokenFrom(h("a=1; sapling_session=abc.def=; b=2"))).toBe("abc.def=");
    expect(sessionTokenFrom(h())).toBeNull();
    expect(sessionTokenFrom(h("sapling_session="))).toBeNull();
    expect(sessionTokenFrom(h("xsapling_session=abc"))).toBeNull();
    expect(sessionTokenFrom(h("sapling_session_old=abc"))).toBeNull();
  });

  it("readCappedBody returns a body under the cap and refuses one over it", async () => {
    const body = (n: number) => new Response(new Uint8Array(n)).body!;
    expect((await readCappedBody(body(100), 100))!.byteLength).toBe(100);
    expect(await readCappedBody(body(101), 100)).toBeNull();
    expect((await readCappedBody(null, 100))!.byteLength).toBe(0);
  });
});

describe("project-key check (ingestTokens / ingestTokensOk)", () => {
  const enc = (s: string) => new TextEncoder().encode(s);
  const KEY = "phc_ours";
  const beacon = (json: string) => {
    const bin = String.fromCharCode(...new TextEncoder().encode(json));
    return enc("data=" + encodeURIComponent(btoa(bin)));
  };

  it("reads the key from every body shape posthog-js sends (uncompressed)", () => {
    const shapes = [
      JSON.stringify({ api_key: KEY, batch: [{ event: "$pageview", properties: { token: KEY } }] }),
      JSON.stringify({ event: "$pageview", properties: { token: KEY } }),
      JSON.stringify([{ event: "$pageview", properties: { token: KEY } }]),
    ];
    for (const body of shapes) expect(ingestTokensOk(ingestTokens(enc(body), "?ver=1"), KEY), body).toBe(true);
    // sendBeacon ($pageleave) always uses base64 form encoding.
    const b = beacon(JSON.stringify({ event: "$pageleave", properties: { token: KEY, title: "Café" } }));
    expect(ingestTokensOk(ingestTokens(b, "?compression=base64"), KEY)).toBe(true);
  });

  it("refuses a foreign key, a mixed batch, or no key at all", () => {
    const foreign = JSON.stringify({ event: "x", properties: { token: "phc_someone_else" } });
    const mixed = JSON.stringify({ api_key: KEY, batch: [{ event: "x", properties: { token: "phc_other" } }] });
    const none = JSON.stringify({ event: "x", properties: {} });
    for (const body of [foreign, mixed, none]) expect(ingestTokensOk(ingestTokens(enc(body), ""), KEY), body).toBe(false);
    // …and nothing is OK when this build has no key.
    expect(ingestTokensOk([KEY], "")).toBe(false);
  });

  it("does not decompress: a gzip body or garbage is unparseable (null)", () => {
    expect(ingestTokens(enc("{}"), "?compression=gzip-js")).toBeNull();
    expect(ingestTokens(new Uint8Array([0x1f, 0x8b, 8, 0, 0xff]), "")).toBeNull();
    expect(ingestTokens(enc("not json"), "")).toBeNull();
    expect(ingestTokens(enc("data=%%%"), "")).toBeNull();
  });
});
