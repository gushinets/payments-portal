import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";


const routes = [
  "/ru",
  "/ru/products",
  "/ru/privacy",
  "/ru/consent-personal-data",
  "/ru/offer",
  "/ru/cancellation",
  "/ru/cookies",
  "/ru/security"
];


for (const route of routes) {
  test(`${route} renders without browser or accessibility failures`, async ({ page }, testInfo) => {
    const consoleErrors: string[] = [];
    const failedRequests: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") {
        consoleErrors.push(message.text());
      }
    });
    page.on("requestfailed", (request) => {
      failedRequests.push(`${request.method()} ${request.url()}: ${request.failure()?.errorText}`);
    });

    const response = await page.goto(route, { waitUntil: "networkidle" });
    expect(response?.ok()).toBeTruthy();
    await expect(page.locator("main")).toBeVisible();

    const accessibility = await new AxeBuilder({ page }).analyze();
    const critical = accessibility.violations.filter((violation) =>
      violation.impact === "critical" || violation.impact === "serious"
    );
    await testInfo.attach("runtime-evidence", {
      body: JSON.stringify({ route, consoleErrors, failedRequests, accessibility: critical }, null, 2),
      contentType: "application/json"
    });
    await page.screenshot({
      path: testInfo.outputPath(`${route.replaceAll("/", "_") || "root"}.png`),
      fullPage: true
    });

    expect(consoleErrors).toEqual([]);
    expect(failedRequests).toEqual([]);
    expect(critical).toEqual([]);
  });
}
