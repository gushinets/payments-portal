import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import ruMessages from "../src/messages/ru.json";

const routes = [
  "/ru",
  "/ru/products",
  "/ru/pricing",
  "/ru/products/document-summary",
  "/ru/products/prompt-optimizer",
  "/ru/account",
  "/ru/forgot-password",
  "/ru/reset-password",
  "/ru/privacy",
  "/ru/consent-personal-data",
  "/ru/offer",
  "/ru/cancellation",
  "/ru/cookies",
  "/ru/security"
];


for (const route of routes) {
  test(`${route} renders without browser or accessibility failures`, async ({ page }, testInfo) => {
    const safeRouteName = route.split("?")[0].replaceAll("/", "_") || "root";
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
    if (route === "/ru/account") {
      await expect(
        page.getByRole("main").getByRole("heading", { name: "Вход или регистрация" })
      ).toBeVisible();
    }
    if (route === "/ru/pricing") {
      const main = page.getByRole("main");
      await expect(
        main.getByRole("heading", { name: ruMessages.Pricing.title, level: 1 })
      ).toBeVisible();
      await expect(
        main.getByText(ruMessages.Pricing.placeholder.description, { exact: true })
      ).toBeVisible();
      await expect(main.getByRole("link")).toHaveCount(2);
      await expect(main.getByRole("button")).toHaveCount(0);
      await expect(
        main.getByRole("link", { name: ruMessages.Pricing.backAction })
      ).toHaveAttribute("href", "/ru");
      await expect(
        main.getByRole("link", { name: ruMessages.Pricing.productsAction })
      ).toHaveAttribute("href", "/ru/products");
      await expect(
        page.getByRole("navigation", { name: ruMessages.Navigation.mainAriaLabel })
          .getByRole("link", { name: ruMessages.Navigation.pricing })
      ).toHaveAttribute("aria-current", "page");
    }

    const accessibility = await new AxeBuilder({ page }).analyze();
    const critical = accessibility.violations.filter((violation) =>
      violation.impact === "critical" || violation.impact === "serious"
    );
    await testInfo.attach("runtime-evidence", {
      body: JSON.stringify(
        { route: route.split("?")[0], consoleErrors, failedRequests, accessibility: critical },
        null,
        2
      ),
      contentType: "application/json"
    });
    await page.screenshot({
      path: testInfo.outputPath(`${safeRouteName}.png`),
      fullPage: true
    });

    expect(consoleErrors).toEqual([]);
    expect(failedRequests).toEqual([]);
    expect(critical).toEqual([]);
  });
}
