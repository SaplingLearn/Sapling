/**
 * The /ingest PostHog proxy must route to the right PostHog host and must
 * never forward the student's cookies (the `sapling_session` credential) or
 * let PostHog set cookies on the app's domain.
 */
import { describe, it, expect } from "vitest";

import {
  downstreamResponseHeaders,
  upstreamRequestHeaders,
  upstreamUrl,
} from "./ingestProxy";

describe("upstreamUrl", () => {
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
      }),
    );
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
