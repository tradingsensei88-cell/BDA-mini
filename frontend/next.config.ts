import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /** Standalone output keeps the production Docker image minimal. */
  output: "standalone",

  reactStrictMode: true,
  poweredByHeader: false,

  /** `three` ships untranspiled ESM consumed by @react-three/fiber. */
  transpilePackages: ["three"],

  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
};

export default nextConfig;
