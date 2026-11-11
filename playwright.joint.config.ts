import path from "node:path";
import { defineConfig } from "@playwright/test";
import portalConfig from "./playwright.config";

const repositoryRoot = process.cwd();

export default defineConfig(portalConfig, {
  testDir: path.join(repositoryRoot, "apps/web/e2e/joint"),
  testIgnore: [],
  outputDir: path.join(repositoryRoot, ".harness/playwright-joint-results"),
  fullyParallel: false,
  workers: 1,
  reporter: [
    ["list"],
    ["json", { outputFile: path.join(repositoryRoot, ".harness/playwright-joint-report/results.json") }],
    ["html", { outputFolder: path.join(repositoryRoot, ".harness/playwright-joint-report/html"), open: "never" }]
  ],
  use: {
    // Delegated credentials must not be retained in traces or videos.
    trace: "off",
    video: "off"
  }
});
