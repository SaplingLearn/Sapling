import type { NextConfig } from "next";
// The dev-mode OpenNext hook lets `next dev` continue to work locally
// against Cloudflare bindings (R2/KV/env vars). Safe no-op in prod builds.
import { initOpenNextCloudflareForDev } from "@opennextjs/cloudflare";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:5000";

const nextConfig: NextConfig = {
  // `standalone` is ignored by @opennextjs/cloudflare (it does its own
  // packaging), but keeping it lets `next build` alone still produce a
  // runnable Docker-style server if anyone ever deploys that way.
  output: "standalone",
  // The 3D knowledge graph stack is ESM-only and touches `window` at module
  // load. We import it via `next/dynamic({ ssr: false })`, but Next/OpenNext's
  // server bundler still needs to transpile these packages so the worker
  // build (Cloudflare Workers) doesn't choke on bare ESM or browser globals.
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
