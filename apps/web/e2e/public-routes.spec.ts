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
    if (testInfo.project.use.isMobile) {
      await page.setViewportSize({ width: 390, height: 844 });
    }
    const consoleErrors: string[] = [];
    const failedRequests: string[] = [];
    const pageErrors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") {
        consoleErrors.push(message.text());
      }
    });
    page.on("pageerror", (error) => {
      pageErrors.push(error.message);
    });
    page.on("requestfailed", (request) => {
      failedRequests.push(`${request.method()} ${request.url()}: ${request.failure()?.errorText}`);
    });

    const response = await page.goto(route, { waitUntil: "networkidle" });
    expect(response?.ok()).toBeTruthy();
    await expect(page.locator("main")).toBeVisible();
    const navigation = page.getByRole("navigation", { name: ruMessages.Navigation.mainAriaLabel });
    const productsLink = navigation.getByRole("link", { name: ruMessages.Navigation.products, exact: true });
    const pricingLink = navigation.getByRole("link", { name: ruMessages.Navigation.pricing, exact: true });
    await expect(productsLink).toHaveAttribute("href", "/ru/products");
    await expect(pricingLink).toHaveAttribute("href", "/ru/pricing");
    if (route === "/ru/products") {
      await expect(productsLink).toHaveAttribute("aria-current", "page");
    } else if (route.startsWith("/ru/products/")) {
      await expect(productsLink).toHaveAttribute("aria-current", "location");
    } else {
      await expect(productsLink).not.toHaveAttribute("aria-current");
    }
    if (route === "/ru/pricing") {
      await expect(pricingLink).toHaveAttribute("aria-current", "page");
    } else {
      await expect(pricingLink).not.toHaveAttribute("aria-current");
    }
    if (route === "/ru/account") {
      await expect(
        page.getByRole("main").getByRole("heading", { name: "Вход или регистрация" })
      ).toBeVisible();
    }
    if (route === "/ru/pricing") {
      const main = page.getByRole("main");
      await expect(page).toHaveTitle(ruMessages.Metadata.title);
      await expect(page.locator('meta[name="description"]'))
        .toHaveAttribute("content", ruMessages.Metadata.description);
      await expect(
        main.getByRole("heading", { name: ruMessages.Pricing.title, level: 1 })
      ).toBeVisible();
      await expect(
        main.getByText(ruMessages.Pricing.placeholder.description, { exact: true })
      ).toBeVisible();
      const placeholder = main.getByRole("article", { name: ruMessages.Pricing.placeholder.title });
      await expect(placeholder.getByRole("heading", {
        name: ruMessages.Pricing.placeholder.title,
        level: 2
      })).toBeVisible();
      await expect(placeholder.getByText(ruMessages.Pricing.placeholder.badge, { exact: true })).toBeVisible();
      await expect(main.getByRole("link")).toHaveCount(2);
      await expect(main.getByRole("button")).toHaveCount(0);
      await expect(main.getByRole("term")).toHaveCount(0);
      await expect(main.getByRole("definition")).toHaveCount(0);
      await expect(main.getByRole("textbox")).toHaveCount(0);
      await expect(main.getByRole("combobox")).toHaveCount(0);
      await expect(main.getByRole("radio")).toHaveCount(0);
      await expect(main.getByRole("checkbox")).toHaveCount(0);
      await expect(main).not.toContainText(
        /\d|₽|€|\$|\b(?:RUB|free|pro|default|CloudPayments|LBX)\b|бесплатн[а-яё]*|безлимит|подписк|автопродлен|в месяц|в год|ежемесячн|ежегодн/i
      );
      await expect(
        main.getByRole("link", { name: ruMessages.Pricing.backAction })
      ).toHaveAttribute("href", "/ru");
      await expect(
        main.getByRole("link", { name: ruMessages.Pricing.productsAction })
      ).toHaveAttribute("href", "/ru/products");
    }

    const accessibility = await new AxeBuilder({ page }).analyze();
    const critical = accessibility.violations.filter((violation) =>
      violation.impact === "critical" || violation.impact === "serious"
    );
    await testInfo.attach("runtime-evidence", {
      body: JSON.stringify(
        { route: route.split("?")[0], consoleErrors, pageErrors, failedRequests, accessibility: critical },
        null,
        2
      ),
      contentType: "application/json"
    });
    // Keep the cookie notice in the accessibility check, then uncover the composition for review.
    await page.getByRole("button", { name: ruMessages.CookieBanner.acceptAction, exact: true }).click();
    await expect.poll(() => page.evaluate(() =>
      Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) -
      document.documentElement.clientWidth
    )).toBeLessThanOrEqual(0);
    await page.evaluate(async () => {
      await document.fonts.ready;
      window.scrollTo(0, 0);
    });
    const screenshotName = `${testInfo.project.name}${safeRouteName}`;
    const screenshotPath = testInfo.outputPath(`${screenshotName}.png`);
    await page.screenshot({
      path: screenshotPath,
      animations: "disabled",
      caret: "hide",
      scale: "css",
      fullPage: true
    });
    await testInfo.attach(screenshotName, { path: screenshotPath, contentType: "image/png" });
    await testInfo.attach("visual-review-context", {
      body: JSON.stringify({
        route,
        viewport: page.viewportSize(),
        reference: "docs/exec-plans/active/portal-ru-anytools.html",
        review: "Compare composition and navy background, flat dark surfaces, thin borders, amber accent, compact radii/spacing, typography and dashboard/cards. Purple/indigo glass and bento must not dominate. Human review only; no pixel baseline."
      }, null, 2),
      contentType: "application/json"
    });

    expect(consoleErrors).toEqual([]);
    expect(pageErrors).toEqual([]);
    expect(failedRequests).toEqual([]);
    expect(critical).toEqual([]);
  });
}
