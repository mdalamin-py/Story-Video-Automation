import type { NextConfig } from "next";

const config: NextConfig = {
  async rewrites() {
    const backend = process.env.STUDIO_API_URL ?? "http://127.0.0.1:8765";
    return [{ source: "/api/:path*", destination: backend + "/api/:path*" },
            { source: "/classic", destination: backend + "/" }];
  },
};
export default config;
