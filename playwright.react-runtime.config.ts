import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

const repositoryRoot = process.cwd();
const devServerPort = Number(
  process.env.PLAYWRIGHT_REACT_RUNTIME_PORT ?? "3100"
);

if (!Number.isInteger(devServerPort) || devServerPort < 1) {
  throw new Error("PLAYWRIGHT_REACT_RUNTIME_PORT must be a positive integer");
}

const baseURL = `http://127.0.0.1:${devServerPort}`;

export default defineConfig({
  testDir: path.join(repositoryRoot, "apps/web/e2e"),
  testMatch: "react-runtime.spec.ts",
  outputDir: path.join(
    repositoryRoot,
    ".harness/playwright-react-runtime-results"
  ),
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: [
    ["list"],
    [
      "json",
      {
        outputFile: path.join(
          repositoryRoot,
          ".harness/playwright-react-runtime-report/results.json"
        )
      }
    ],
    [
      "html",
      {
        outputFolder: path.join(
          repositoryRoot,
          ".harness/playwright-react-runtime-report/html"
        ),
        open: "never"
      }
    ]
  ],
  use: {
    baseURL,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure"
  },
  webServer: {
    command: `npm --workspace @anytoolai/web run dev -- --hostname 127.0.0.1 --port ${devServerPort}`,
    cwd: repositoryRoot,
    env: {
      ...process.env,
      NEXT_TELEMETRY_DISABLED: "1"
    },
    url: `${baseURL}/ru`,
    reuseExistingServer: false,
    stdout: "pipe",
    stderr: "pipe",
    timeout: 120_000
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
