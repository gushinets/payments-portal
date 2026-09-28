import { fileURLToPath } from "node:url";
import createNextIntlPlugin from "next-intl/plugin";

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

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

export default withNextIntl(nextConfig);
