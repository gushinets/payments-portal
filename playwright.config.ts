import fs from "node:fs";
import path from "node:path";
import { defineConfig, devices } from "@playwright/test";
import runtimeEnv from "./playwright.runtime-env.cjs";

const { loadRuntimeEnv } = runtimeEnv as {
  loadRuntimeEnv: (repositoryRoot: string) => Record<string, string>;
};

type RuntimeConfig = {
  web_port: number;
  api_port: number;
  otlp_http_port?: number;
};

const repositoryRoot = process.cwd();
loadRuntimeEnv(repositoryRoot);

function runtimeConfig(): RuntimeConfig | null {
  const runtimePath = path.join(repositoryRoot, ".harness/runtime.json");
  if (!fs.existsSync(runtimePath)) {
    return null;
  }
  return JSON.parse(fs.readFileSync(runtimePath, "utf8")) as RuntimeConfig;
}

const runtime = runtimeConfig();
const runtimeCaddyPort =
  runtime?.otlp_http_port === undefined ? null : runtime.otlp_http_port + 1000;
const baseURL =
  process.env.PLAYWRIGHT_BASE_URL ??
  `http://localhost:${runtimeCaddyPort ?? runtime?.web_port ?? 3000}`;
const apiBaseURL =
  process.env.PLAYWRIGHT_API_BASE_URL ??
  `http://127.0.0.1:${runtime?.api_port ?? 8000}`;

process.env.PLAYWRIGHT_API_BASE_URL = apiBaseURL;

export default defineConfig({
  testDir: path.join(repositoryRoot, "apps/web/e2e"),
  outputDir: path.join(repositoryRoot, ".harness/playwright-results"),
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: [
    ["list"],
    ["json", { outputFile: path.join(repositoryRoot, ".harness/playwright-report/results.json") }],
    ["html", { outputFolder: path.join(repositoryRoot, ".harness/playwright-report/html"), open: "never" }]
  ],
  use: {
    baseURL,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure"
  },
  projects: [
    {
      name: "desktop-chromium",
      use: { ...devices["Desktop Chrome"] }
    },
    {
      name: "mobile-chromium",
      use: { ...devices["Pixel 7"] }
    }
  ]
});
