import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import type { CatalogProductResponse, CatalogProductsResponse } from "../src/generated/api-contracts/types.gen";
import ru from "../src/messages/ru.json";

// Manual Step 6 acceptance. No page.route(), response fixture, or DB seeding in
// this test: the API must serve a separately published revision from the dev DB.
test("stored SIMULATED offer reaches the browser through the real Portal API", async ({ page, request }, testInfo) => {
  test.skip(process.env.CATALOG_PREVIEW_ACCEPTANCE !== "1", "Requires explicit dev publication; see DEVELOPMENT.md");

  const apiBase = process.env.PLAYWRIGHT_API_BASE_URL;
  if (!apiBase) throw new Error("PLAYWRIGHT_API_BASE_URL is required");
  const response = await request.get(`${apiBase}/api/catalog/products`);
  expect(response.status()).toBe(200);
  const payload: CatalogProductsResponse = await response.json();
  const product = payload.products.find((item) => item.product_id === "proposal_ai");
  expect(product?.availability).toBe("SIMULATED_PREVIEW");
  expect(product?.offer?.money.recurring_amount).toBe("200.02");
  expect(product?.offer?.money.connection_amount).toBe("14.06");
  expect(product?.offer?.allowance.quantity).toBe("25");

  const catalogRequests: { authorization: string | undefined }[] = [];
  page.on("request", (outbound) => {
    if (new URL(outbound.url()).pathname.startsWith("/api/catalog/products")) {
      catalogRequests.push({ authorization: outbound.headers().authorization });
    }
  });
  await page.goto("/ru/products");
  const main = page.getByRole("main");
  const card = main.getByRole("article").filter({ has: page.getByText("proposal_ai", { exact: true }) });
  await expect(card.getByText(ru.CatalogPreview.simulated)).toBeVisible();
  await expect(card.getByText("200,02 RUB", { exact: true })).toBeVisible();
  await expect(card.getByText("14,06 RUB", { exact: true })).toBeVisible();
  await card.getByRole("link", { name: ru.CatalogPreview.details }).click();
  await expect(page).toHaveURL(/\/ru\/products\/proposal_ai$/);
  await expect(main.getByText(ru.CatalogPreview.simulated)).toBeVisible();
  const reloadedOffer = page.waitForResponse((incoming) =>
    new URL(incoming.url()).pathname === "/api/catalog/products/proposal_ai"
  );
  await page.reload();
  const reloadedResponse = await reloadedOffer;
  expect(reloadedResponse.status()).toBe(200);
  const reloadedProduct: CatalogProductResponse = await reloadedResponse.json();
  expect(reloadedProduct.offer?.revision_id).toBe(product?.offer?.revision_id);
  await expect(main.getByRole("heading", { name: ru.CatalogPreview.productTitle, level: 1 })).toBeVisible();
  await expect(main.getByText(ru.CatalogPreview.simulated)).toBeVisible();
  await expect(main.getByText("200,02 RUB", { exact: true })).toBeVisible();
  await expect(main.getByRole("button")).toHaveCount(0);
  expect(catalogRequests.length).toBeGreaterThanOrEqual(3);
  expect(catalogRequests.every((outbound) => outbound.authorization === undefined)).toBe(true);
  await page.getByRole("button", { name: ru.CookieBanner.acceptAction, exact: true }).click();
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations.filter((violation) => ["critical", "serious"].includes(violation.impact ?? "")))
    .toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await testInfo.attach("real-api-stored-simulated-preview", {
    body: await page.screenshot({ fullPage: true }), contentType: "image/png"
  });
  await testInfo.attach("stored-revision", {
    body: JSON.stringify({ revision_id: product?.offer?.revision_id, evidence_mode: product?.evidence_mode }),
    contentType: "application/json"
  });
});
