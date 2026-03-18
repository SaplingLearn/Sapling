import type { NextConfig } from "next";

const isStaticExport = process.env.STATIC_EXPORT === "true";
const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:5000";

const nextConfig: NextConfig = {
  ...(isStaticExport
    ? { output: "export", images: { unoptimized: true } }
    : {
        output: "standalone",
        async rewrites() {
          return [
            {
              source: "/api/:path*",
              destination: `${BACKEND_URL}/api/:path*`,
            },
          ];
        },
      }),
  reactCompiler: true,
};

export default nextConfig;