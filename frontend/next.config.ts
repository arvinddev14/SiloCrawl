import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output is for the Docker image (`node server.js`). Vercel builds
  // with its own output pipeline, so only opt in when BUILD_STANDALONE=1 (set in
  // the Dockerfile) — this keeps the Vercel build clean.
  output: process.env.BUILD_STANDALONE === "1" ? "standalone" : undefined,
};

export default nextConfig;
