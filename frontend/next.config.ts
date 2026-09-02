import type { NextConfig } from "next";
// The dev-mode OpenNext hook lets `next dev` continue to work locally
// against Cloudflare bindings (R2/KV/env vars). Safe no-op in prod builds.
import { initOpenNextCloudflareForDev } from "@opennextjs/cloudflare";
import { checkFrontendDeployEnv, resolveFrontendEnv } from "./src/lib/deployGuard";

// Cross-check BEFORE deriving: checkFrontendDeployEnv's "explicit lock"
// branch exists to fail the build when DEPLOY_ENV disagrees with explicit
// BACKEND_URL/NEXT_PUBLIC_API_URL/COOKIE_DOMAIN vars (the "staging config on
// the prod worker" footgun). It must see the operator-provided env — running
// it after the derivation below would only ever see the already-corrected
// values, silently converting the fail-loud guard into an auto-correct that
// masks a wrong DEPLOY_ENV pasted into the other environment's build panel.
if (process.env.NODE_ENV === "production") {
  const deployProblems = checkFrontendDeployEnv(process.env);
  if (deployProblems.length) {
    throw new Error(
      "Frontend deploy-config guard failed:\n  - " +
        deployProblems.join("\n  - ") +
        "\nCheck the Cloudflare Workers Build variables and deploy command " +
        "(prod: 'npx wrangler deploy'; staging: 'npx wrangler deploy --env staging').",
    );
  }
}

// DEPLOY_ENV is the single knob: when a Workers Build sets DEPLOY_ENV=staging|
// production, the build-time BACKEND_URL (the /api rewrite target) and the
// inlined NEXT_PUBLIC_API_URL / COOKIE_DOMAIN are DERIVED from FRONTEND_ENVS so
// they cannot be half-set or point at the wrong environment. Setting these on
// process.env before Next reads them keeps NEXT_PUBLIC_* inlining consistent.
// When DEPLOY_ENV is unset we leave the explicit vars alone (local/docker, or a
// legacy build that sets BACKEND_URL directly).
const RESOLVED = resolveFrontendEnv(process.env);
if (RESOLVED.derived) {
  process.env.BACKEND_URL = RESOLVED.apiUrl;
  process.env.NEXT_PUBLIC_API_URL = RESOLVED.apiUrl;
  if (RESOLVED.cookieDomain) process.env.COOKIE_DOMAIN = RESOLVED.cookieDomain;
}

// .trim() defends against a stray leading/trailing space in the build
// variable: an untrimmed " https://..." makes the /api rewrite destination
// start with a space, which Next rejects at build time as "Invalid rewrite
// found". Trimming makes the build tolerant; the guard below still rejects a
// genuinely malformed value.
const BACKEND_URL = (process.env.BACKEND_URL ?? "").trim() || "http://localhost:5000";

// Guard against the silent footgun that took staging's dashboard down: a
// deployment build (NODE_ENV=production) MUST set BACKEND_URL explicitly.
// Falling back to http://localhost:5000 bakes a :5000 port into the /api
// rewrite destination, which Next's path-to-regexp then misreads as a route
// param named "5000" ("TypeError: Expected \"5000\" to be a string") so every
// proxied /api/* call 500s at runtime. wrangler.toml [vars] is runtime-only and
// does NOT fix this — the rewrite is baked at build time. Fail the build loudly
// instead of shipping a worker that 500s on every API call.
if (process.env.NODE_ENV === "production") {
  const configured = (process.env.BACKEND_URL ?? "").trim();
  if (!configured) {
    throw new Error(
      "BACKEND_URL is required for production builds. Set it to the backend origin " +
        "(prod: https://api.saplinglearn.com, staging: https://api.staging.saplinglearn.com) " +
        "as a build-time env var or Cloudflare Workers Builds variable. Without it the /api " +
        "rewrite bakes http://localhost:5000 and every proxied API call 500s.",
    );
  }
  if (!/^https?:\/\//.test(configured)) {
    throw new Error(
      "BACKEND_URL must be an absolute http(s) origin, got " +
        JSON.stringify(process.env.BACKEND_URL) +
        ". A stray leading/trailing space is the usual cause (Next then rejects the " +
        "/api rewrite as 'Invalid rewrite found') — check the Cloudflare Workers Builds variable.",
    );
  }

  // The "staging config on the prod worker" cross-check runs ABOVE, before
  // the DEPLOY_ENV derivation mutates process.env — see the comment there.
}

const nextConfig: NextConfig = {
  // `standalone` is ignored by @opennextjs/cloudflare (it does its own
  // packaging), but keeping it lets `next build` alone still produce a
  // runnable Docker-style server if anyone ever deploys that way.
  output: "standalone",
  // The 3D knowledge graph stack is ESM-only and touches `window` at module
  // load. We import it via `next/dynamic({ ssr: false })`, but Next/OpenNext's
  // server bundler still needs to transpile these packages so the worker
  // build doesn't choke on bare ESM or browser globals.
  //
  // Tried `serverExternalPackages` alone (mutually exclusive with
  // transpilePackages); broke local Next.js builds because the RSC bundler
  // still resolves the module graph at static-analysis time and crashes
  // on `window is not defined`. transpilePackages with `dynamic({ssr:false})`
  // is the local-build-clean configuration; CF behavior is investigated
  // separately via the dashboard logs.
  transpilePackages: [
    "react-force-graph-3d",
    "3d-force-graph",
    "three-render-objects",
    "d3-force-3d",
    "react-kapsule",
    "three",
  ],
  // The /api proxy MUST NOT shadow the app's own route handlers — the session
  // BFF (src/app/api/auth/session) is the only thing that can mint the
  // `sapling_session` cookie, and the backend has no such endpoint.
  //
  // The array form is `afterFiles`, which Next 16 checks BEFORE app-router
  // route handlers, so `/api/:path*` swallowed every local /api route and the
  // OAuth callback's `POST /api/auth/session` 404'd — sign-in reached Google,
  // came back approved, and then died one step from the finish line. The
  // `{ source: "/api/auth/session", destination: "/api/auth/session" }`
  // self-rewrite that used to sit above it was the attempted exemption; a
  // rewrite whose destination is its own source resolves to not-found rather
  // than re-entering route matching, so it 404'd just the same.
  //
  // `fallback` is the phase that runs only AFTER filesystem and dynamic routes
  // have all missed. Anything this app serves itself wins; everything else
  // proxies to the backend. That ordering is what the config wants and holds
  // for any future BFF route without a per-path exemption.
  // Guarded by e2e/auth-session.spec.ts and next.config.test.ts.
  async rewrites() {
    return {
      beforeFiles: [],
      afterFiles: [],
      fallback: [
        { source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` },
      ],
    };
  },
  async redirects() {
    return [
      { source: "/auth", destination: "/", permanent: false },
    ];
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          {
            key: "Cross-Origin-Opener-Policy",
            value: "same-origin-allow-popups",
          },
        ],
      },
    ];
  },
};

initOpenNextCloudflareForDev();

export default nextConfig;
