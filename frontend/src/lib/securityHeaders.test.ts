/**
 * Pins the response security headers (next.config.ts headers() →
 * lib/securityHeaders.ts). A CSP change that breaks the app does so silently,
 * so every value is written out here: changing one is a deliberate edit to
 * this file, reviewed next to the reasoning in securityHeaders.ts.
 */
import { describe, expect, it } from "vitest";
import nextConfig from "../../next.config";
import {
  contentSecurityPolicy,
  contentSecurityPolicyReportOnly,
  securityHeaders,
  supabaseOrigins,
} from "./securityHeaders";

const PROD = { NODE_ENV: "production", NEXT_PUBLIC_SUPABASE_URL: "https://abcd1234.supabase.co" };

const ENFORCED_PROD =
  "img-src 'self' data: blob: https://abcd1234.supabase.co https://*.googleusercontent.com https://saplinglearn.com; " +
  "connect-src 'self' https://abcd1234.supabase.co wss://abcd1234.supabase.co; " +
  "frame-src 'self' https://www.geogebra.org; " +
  "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'";

const REPORT_ONLY_PROD =
  "default-src 'self'; " +
  "script-src 'self' 'unsafe-inline'; " +
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; " +
  "font-src 'self' data: https://fonts.saplinglearn.com https://fonts.gstatic.com; " +
  "worker-src 'self' blob:; media-src 'self' blob: data:; manifest-src 'self'; " +
  ENFORCED_PROD;

function asMap(headers: { key: string; value: string }[]): Record<string, string> {
  return Object.fromEntries(headers.map((h) => [h.key, h.value]));
}

describe("securityHeaders", () => {
  it("sets exactly this header set on a production build", () => {
    expect(asMap(securityHeaders(PROD))).toEqual({
      "Cross-Origin-Opener-Policy": "same-origin-allow-popups",
      "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "strict-origin-when-cross-origin",
      "X-Frame-Options": "DENY",
      "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
      "Content-Security-Policy": ENFORCED_PROD,
      "Content-Security-Policy-Report-Only": REPORT_ONLY_PROD,
    });
  });

  it("names each header once", () => {
    const keys = securityHeaders(PROD).map((h) => h.key.toLowerCase());
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("enforces no script-src, style-src or default-src (those are report-only)", () => {
    const enforced = contentSecurityPolicy(PROD);
    for (const d of ["script-src", "style-src", "default-src"]) {
      expect(enforced).not.toMatch(new RegExp(`(^|; )${d} `));
    }
    // ...and the report-only policy never allows eval in a production build.
    expect(contentSecurityPolicyReportOnly(PROD)).not.toContain("'unsafe-eval'");
  });

  it("never allows an arbitrary image or connect origin", () => {
    for (const policy of [contentSecurityPolicy(PROD), contentSecurityPolicyReportOnly(PROD)]) {
      for (const d of policy.split("; ")) {
        const [name, ...sources] = d.split(" ");
        if (name === "img-src" || name === "connect-src") {
          expect(sources).not.toContain("*");
          expect(sources).not.toContain("https:");
          expect(sources).not.toContain("http:");
        }
      }
    }
  });

  it("follows the build's Supabase project, including a local http one (E2E build:test)", () => {
    const csp = contentSecurityPolicy({ NODE_ENV: "production", NEXT_PUBLIC_SUPABASE_URL: "http://127.0.0.1:54321" });
    expect(csp).toContain("img-src 'self' data: blob: http://127.0.0.1:54321 ");
    expect(csp).toContain("connect-src 'self' http://127.0.0.1:54321 ws://127.0.0.1:54321;");
  });

  it("allows eval and a websocket only in a dev build", () => {
    const dev = { ...PROD, NODE_ENV: "development" };
    expect(contentSecurityPolicyReportOnly(dev)).toContain("script-src 'self' 'unsafe-inline' 'unsafe-eval';");
    expect(contentSecurityPolicy(dev)).toContain("wss://abcd1234.supabase.co ws:;");
    expect(contentSecurityPolicy(PROD)).not.toContain(" ws:");
  });
});

describe("supabaseOrigins", () => {
  it("takes the project origin and its realtime websocket origin", () => {
    expect(supabaseOrigins(" https://abcd1234.supabase.co/ ")).toEqual({
      http: "https://abcd1234.supabase.co",
      ws: "wss://abcd1234.supabase.co",
    });
  });

  it.each([undefined, "", "not a url", "javascript:alert(1)"])(
    "falls back to any supabase.co project for %s",
    (raw) => {
      expect(supabaseOrigins(raw)).toEqual({ http: "https://*.supabase.co", ws: "wss://*.supabase.co" });
    },
  );
});

describe("next.config.ts headers()", () => {
  it("sends the security header set on every route", async () => {
    const rules = await nextConfig.headers!();
    expect(rules).toHaveLength(1);
    expect(rules[0].source).toBe("/(.*)");
    expect(rules[0].headers).toEqual(securityHeaders(process.env));
  });
});
