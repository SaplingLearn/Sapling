import type { NextConfig } from "next";
// The dev-mode OpenNext hook lets `next dev` continue to work locally
// against Cloudflare bindings (R2/KV/env vars). Safe no-op in prod builds.
import { initOpenNextCloudflareForDev } from "@opennextjs/cloudflare";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:5000";

// Guard against the silent footgun that took staging's dashboard down: a
// deployment build (NODE_ENV=production) MUST set BACKEND_URL explicitly.
// Falling back to http://localhost:5000 bakes a :5000 port into the /api
// rewrite destination, which Next's path-to-regexp then misreads as a route
// param named "5000" ("TypeError: Expected \"5000\" to be a string") so every
// proxied /api/* call 500s at runtime. wrangler.toml [vars] is runtime-only and
// does NOT fix this — the rewrite is baked at build time. Fail the build loudly
// instead of shipping a worker that 500s on every API call.
if (process.env.NODE_ENV === "production" && !process.env.BACKEND_URL) {
  throw new Error(
    "BACKEND_URL is required for production builds. Set it to the backend origin " +
      "(prod: https://api.saplinglearn.com, staging: https://api.staging.saplinglearn.com) " +
      "as a build-time env var or Cloudflare Workers Builds variable. Without it the /api " +
      "rewrite bakes http://localhost:5000 and every proxied API call 500s.",
  );
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
  async rewrites() {
    return [
      { source: "/api/auth/session", destination: "/api/auth/session" },
      { source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` },
    ];
  },
  async redirects() {
    return [
      { source: "/auth", destination: "/", permanent: false },
    ];
  },
};

initOpenNextCloudflareForDev();

export default nextConfig;
