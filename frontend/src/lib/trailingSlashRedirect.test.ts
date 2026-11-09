/**
 * The next.config.ts trailing-slash redirect must behave like the built-in it
 * replaces (Next's `trailingSlash: false` rule, `/:path+/` → `/:path+`) for
 * every path except `/ingest/*` — matched and compiled with the same
 * path-to-regexp Next ships. The browser-level 308s are pinned by
 * e2e/analytics.spec.ts.
 */
import { createRequire } from "node:module";
import { describe, it, expect } from "vitest";

// Next's own compiled copy (untyped): the matcher its router and OpenNext use.
const { match, compile } = createRequire(import.meta.url)("next/dist/compiled/path-to-regexp") as {
  match: (path: string, opts: { decode: (s: string) => string }) => (p: string) => false | { params: Record<string, string | string[]> };
  compile: (path: string, opts: { encode: (s: string) => string; validate: boolean }) => (params: object) => string;
};

import { TRAILING_SLASH_REDIRECT } from "./trailingSlashRedirect";

const keep = (s: string) => s;

/** Where a rule sends `path`, or null when it does not match. */
function redirectWith(rule: { source: string; destination: string }, path: string): string | null {
  const m = match(rule.source, { decode: keep })(path);
  return m ? compile(rule.destination, { encode: keep, validate: false })(m.params) : null;
}

/** Next 16's built-in with `trailingSlash: false` (load-custom-routes.js). */
const BUILT_IN = { source: "/:path+/", destination: "/:path+" };

describe("TRAILING_SLASH_REDIRECT", () => {
  it("is a permanent (308) redirect", () => {
    expect(TRAILING_SLASH_REDIRECT.permanent).toBe(true);
  });

  it("matches Next's built-in everywhere outside /ingest, .well-known included", () => {
    for (const path of [
      "/settings/",
      "/news/some-post/",
      "/api/auth/me/",
      "/notes/a%20b/",
      "/news/caf%C3%A9/",
      "/a/b/c/",
      "/ingestion/",
      "/ingest-x/e/",
      // The trailing-slash: false built-in has no .well-known exclusion
      // (only the trailingSlash: true pair does), so neither does this.
      "/.well-known/security.txt/",
      "/.well-known/",
      // Not slash-terminated, or the root: no redirect either way.
      "/settings",
      "/",
    ]) {
      expect(redirectWith(TRAILING_SLASH_REDIRECT, path), path).toBe(redirectWith(BUILT_IN, path));
    }
    expect(redirectWith(TRAILING_SLASH_REDIRECT, "/news/caf%C3%A9/")).toBe("/news/caf%C3%A9");
    expect(redirectWith(TRAILING_SLASH_REDIRECT, "/.well-known/security.txt/")).toBe("/.well-known/security.txt");
  });

  it("leaves PostHog's slash-terminated /ingest endpoints alone", () => {
    for (const path of ["/ingest/e/", "/ingest/i/v0/e/", "/ingest/batch/", "/ingest/flags/"]) {
      expect(redirectWith(TRAILING_SLASH_REDIRECT, path), path).toBeNull();
    }
  });
});
