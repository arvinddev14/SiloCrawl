import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit a self-contained .next/standalone tree so the Docker image can run
  // `node server.js` without a full node_modules install.
  output: "standalone",
};

export default nextConfig;
