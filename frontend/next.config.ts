import type { NextConfig } from "next";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:5000";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      { source: "/api/auth/session", destination: "/api/auth/session" },
      { source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` },
    ];
  },
};

export default nextConfig;
