import type { NextConfig } from "next";

// Static export: every page is rendered at build time from the JSON in public/data,
// so the deployed site never depends on a live database or API.
const nextConfig: NextConfig = {
  output: "export",
  images: { unoptimized: true },
  reactCompiler: true,
  turbopack: {
    root: process.cwd(),
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
