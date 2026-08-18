import { fileURLToPath } from "node:url";

const repositoryRoot = fileURLToPath(new URL("../..", import.meta.url));

const allowedDevOrigins = (
  process.env.NEXT_ALLOWED_DEV_ORIGINS ?? "192.168.1.102"
)
  .split(",")
  .map((origin) => origin.trim())
  .filter(Boolean)
  .map((origin) => origin.replace(/^https?:\/\//, "").replace(/:\d+$/, ""));

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  allowedDevOrigins,
  output: "standalone",
  outputFileTracingRoot: repositoryRoot,
  experimental: {
    useTypeScriptCli: false
  }
};

export default nextConfig;
