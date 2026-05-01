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
