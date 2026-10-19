import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import ru from "../src/messages/ru.json";
import pt from "../src/messages/pt.json";
import { simulatedProduct } from "../tests/fixtures/catalog";

// Browser regression with a visibly simulated Portal HTTP response. Real
// PostgreSQL/API/browser acceptance is a separate human walkthrough.
test("anonymous list, canonical-ID direct load and hard reload work without marketing metadata", async ({ page }, testInfo) => {
  const authorization: (string | undefined)[] = [];
  let details = 0;
  await page.route("**/api/catalog/products{,/*}", async (route) => {
    authorization.push(route.request().headers().authorization);
    const list = new URL(route.request().url()).pathname === "/api/catalog/products";
    if (!list) details += 1;
    await route.fulfill({ json: list ? { products: [simulatedProduct] } : simulatedProduct });
  });
  await page.goto("/ru/products/proposal_ai");
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { level: 1, name: ru.CatalogPreview.productTitle })).toBeVisible();
  await expect(main.getByText(ru.CatalogPreview.fallback)).toBeVisible();
  await expect(main.getByText(ru.CatalogPreview.simulated)).toBeVisible();
  await page.reload();
  await expect(main.getByText(ru.CatalogPreview.simulated)).toBeVisible();
  expect(details).toBeGreaterThanOrEqual(2);
  await main.getByRole("link", { name: ru.Catalog.backToCatalog }).click();
  await main.getByRole("link", { name: ru.CatalogPreview.details }).click();
  await expect(page).toHaveURL(/\/ru\/products\/proposal_ai$/);
  await expect(main.getByText(ru.CatalogPreview.simulated)).toBeVisible();
  await expect(main.getByText("9 007 199 254 740 993,01 RUB")).toBeVisible();
  expect(authorization.length).toBeGreaterThanOrEqual(4);
  expect(authorization.every((value) => value === undefined)).toBe(true);
  await expect(main.getByRole("button")).toHaveCount(0);
  await page.getByRole("button", { name: ru.CookieBanner.acceptAction, exact: true }).click();
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations.filter((violation) => ["critical", "serious"].includes(violation.impact ?? ""))).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await testInfo.attach("simulated-catalog-preview", {
    body: await page.screenshot({ fullPage: true }), contentType: "image/png"
  });
});

test("Brazilian Portuguese uses exact localized money and product-ID routing", async ({ page }) => {
  await page.route("**/api/catalog/products/*", (route) => route.fulfill({ json: simulatedProduct }));
  await page.goto("/pt/products/proposal_ai");
  await expect(page.getByRole("main").getByText(pt.CatalogPreview.simulated)).toBeVisible();
  await expect(page.getByRole("main").getByText("9.007.199.254.740.993,01 RUB")).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "pt-BR");
});

test("unknown ID and API failure remain distinct from an empty catalog", async ({ page }) => {
  await page.route("**/api/catalog/products{,/*}", (route) => {
    const list = new URL(route.request().url()).pathname === "/api/catalog/products";
    return route.fulfill(list ? { json: { products: [] } } : {
      status: 404, json: { detail: { code: "catalog_product_not_found" } }
    });
  });
  await page.goto("/ru/products");
  await expect(page.getByRole("main").getByRole("status")).toHaveText(ru.CatalogPreview.empty);
  await page.goto("/ru/products/unknown-source-id");
  await expect(page.getByRole("main").getByRole("status")).toHaveText(ru.CatalogPreview.notFound);
  await page.route("**/api/catalog/products/*", (route) => route.fulfill({
    status: 503, json: { detail: { code: "catalog_unavailable" } }
  }));
  await page.reload();
  await expect(page.getByRole("main").getByRole("status")).toContainText(ru.CatalogPreview.failed);
  await expect(page.getByRole("main")).not.toContainText("RUB");
});
