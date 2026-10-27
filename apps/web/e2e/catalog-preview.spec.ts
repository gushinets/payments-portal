import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import ru from "../src/messages/ru.json";
import pt from "../src/messages/pt.json";
import { simulatedProduct } from "../tests/fixtures/catalog";
import { savedPurchase } from "../tests/fixtures/purchase";
import type { AccountPurchaseResponse } from "../src/generated/api-contracts/types.gen";

async function mockCatalog(page: Page, path: "" | "/products" | "/account") {
  const owned: AccountPurchaseResponse = { purchase_intent_id: savedPurchase.purchase_intent_id, product_id: savedPurchase.product_id, state: "linked", created_at: "2026-10-27T12:00:00Z" };
  const state = { products: [simulatedProduct], unavailable: false, purchases: [owned], inventoryUnavailable: false, catalogReads: 0 };
  await page.route("**/api/catalog/products{,/*}", async (route) => {
    state.catalogReads += 1;
    expect(route.request().headers().authorization).toBeUndefined();
    const productId = new URL(route.request().url()).pathname.split("/")[4];
    await route.fulfill(state.unavailable
      ? { status: 503, json: { detail: { code: "catalog_unavailable" } } }
      : { json: productId ? state.products.find((product) => product.product_id === productId) : { products: state.products } });
  });
  if (path === "/account") {
    await page.addInitScript(() => localStorage.setItem("anytoolai_session_token_v1", "catalog-session"));
    await page.route("**/api/auth/session", (route) => route.fulfill({ json: {
      authenticated: true,
      user: {
        tenant_id: "anytoolai", region: "ru",
        user_id: "11111111-1111-4111-8111-111111111111",
        email: "catalog@example.com", email_verified: true
      }
    } }));
  }
  await page.route("**/api/purchase-intents", (route) => route.fulfill(state.inventoryUnavailable
    ? { status: 503, json: { detail: { code: "unavailable" } } }
    : { json: { purchases: state.purchases, next_cursor: null } }));
  await page.route("**/api/purchase-intents/current?*", (route) => route.fulfill({ json: { purchase: savedPurchase } }));
  return state;
}

for (const locale of ["ru", "pt"] as const) {
  for (const path of ["", "/products"] as const) {
    test(`${locale}${path || "/"} displays all published products with exact localized terms`, async ({ page }, testInfo) => {
      const messages = locale === "pt" ? pt : ru;
      const state = await mockCatalog(page, path);
      const main = page.getByRole("main");
      await page.goto(`/${locale}${path}`);
      await expect(main.getByText("proposal_ai", { exact: true })).toBeVisible();
      await expect(main).not.toContainText(/Document Summary|Prompt Optimizer/);

      // Simulate a subsequent CLI publication becoming visible in the same API.
      state.products = [...state.products, { ...simulatedProduct, product_id: "new_published_tool" }];
      await page.reload();
      await expect(main.getByRole("article")).toHaveCount(2);
      for (const product of state.products) {
        const card = main.getByRole("article").filter({ has: page.getByText(product.product_id, { exact: true }) });
        await expect(card.getByText(messages.CatalogPreview.simulated)).toBeVisible();
        await expect(card.getByText(locale === "ru" ? "9 007 199 254 740 993,01 RUB" : "9.007.199.254.740.993,01 RUB")).toBeVisible();
        await expect(card.getByText(locale === "ru" ? "1 месяц" : "1 mês", { exact: true })).toBeVisible();
        await expect(card.getByText(messages.CatalogPreview.periodAnchors.instance_start, { exact: true })).toBeVisible();
        await expect(card.getByText(messages.CatalogPreview.quantity).locator("..")).toContainText("1");
        await expect(card.getByRole("link", { name: messages.CatalogPreview.details }))
          .toHaveAttribute("href", `/${locale}/products/${product.product_id}`);
        for (const slot of ["access", "usage"] as const) {
          const status = messages.Account.products.state[slot];
          await expect(card.getByText(status.label, { exact: true })).toHaveCount(0);
          await expect(card.getByText(status.description, { exact: true })).toHaveCount(0);
        }
        await expect(card.getByText(messages.Account.products.state.commercial.description, { exact: true })).toHaveCount(0);
      }
      await page.getByRole("button", { name: messages.CookieBanner.acceptAction, exact: true }).click();
      const accessibility = await new AxeBuilder({ page }).analyze();
      expect(accessibility.violations.filter(({ impact }) => impact === "critical" || impact === "serious")).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      await testInfo.attach("published-catalog", { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
    });

    test(`${locale}${path || "/"} supports product navigation and recovers from a catalog failure`, async ({ page }) => {
      const messages = locale === "pt" ? pt : ru;
      const state = await mockCatalog(page, path);
      state.products = [...state.products, { ...simulatedProduct, product_id: "new_published_tool" }];
      const main = page.getByRole("main");
      await page.goto(`/${locale}${path}`);
      await expect(main.getByRole("article")).toHaveCount(2);
      await page.getByRole("button", { name: messages.CookieBanner.acceptAction, exact: true }).click();
      const link = main.getByRole("article").last().getByRole("link", { name: messages.CatalogPreview.details });
      await link.click();
      await expect(page).toHaveURL(new RegExp(`/${locale}/products/new_published_tool$`));
      await expect(main.getByText(messages.CatalogPreview.simulated)).toBeVisible();
      await page.reload();
      await expect(main.getByText(messages.CatalogPreview.simulated)).toBeVisible();
      // A separately published ID also works on a fresh, direct navigation.
      await page.goto(`/${locale}/products/new_published_tool`);
      await expect(main.getByText(messages.CatalogPreview.simulated)).toBeVisible();
      await expect(main.locator(".account-product-statuses")).toHaveCount(0);
      const offerCard = main.locator(".tool-card");
      await expect(offerCard).toHaveCount(1);
      for (const slot of ["access", "usage"] as const) {
        await expect(offerCard.getByText(messages.Account.products.state[slot].label, { exact: true })).toHaveCount(0);
        await expect(offerCard.getByText(messages.Account.products.state[slot].description, { exact: true })).toHaveCount(0);
      }

      state.unavailable = true;
      await page.goto(`/${locale}${path}`);
      await expect(main.getByText(messages.CatalogPreview.failed)).toBeVisible();
      await expect(main.getByRole("article")).toHaveCount(0);
      state.unavailable = false;
      await main.getByRole("button", { name: messages.CatalogPreview.retry }).click();
      await expect(main.getByRole("article")).toHaveCount(2);
      state.products = [];
      await page.reload();
      await expect(main.getByText(messages.CatalogPreview.empty)).toBeVisible();
      await expect(main.getByRole("article")).toHaveCount(0);
    });
  }
  test(`${locale}/account lists only owned purchases despite new catalog publications`, async ({ page }, testInfo) => {
    const messages = locale === "pt" ? pt : ru;
    const state = await mockCatalog(page, "/account");
    await page.goto(`/${locale}/account`);
    const products = page.getByRole("region", { name: messages.Account.products.title });
    await expect(products.getByRole("article")).toHaveCount(1);
    state.products.push({ ...simulatedProduct, product_id: "new_published_tool" });
    await page.reload();
    await expect(products.getByRole("article")).toHaveCount(1);
    await expect(products.getByText("new_published_tool", { exact: true })).toHaveCount(0);
    await expect(products.getByRole("link", { name: messages.Account.products.detailAction })).toHaveAttribute("href", `/${locale}/products/proposal_ai`);
    await expect(products.getByRole("link", { name: messages.Account.products.allProducts })).toHaveAttribute("href", `/${locale}/products`);
    await expect(products.getByText(messages.Account.products.prepared)).toBeVisible();
    expect(state.catalogReads).toBe(0);
    await page.getByRole("button", { name: messages.CookieBanner.acceptAction, exact: true }).click();
    const accessibility = await new AxeBuilder({ page }).analyze();
    expect(accessibility.violations.filter(({ impact }) => impact === "critical" || impact === "serious")).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await testInfo.attach("owned-products", { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
  });

  test(`${locale}/account opens product detail and distinguishes unavailable inventory from empty`, async ({ page }) => {
    const messages = locale === "pt" ? pt : ru;
    const state = await mockCatalog(page, "/account");
    await page.goto(`/${locale}/account`);
    await page.getByRole("button", { name: messages.CookieBanner.acceptAction, exact: true }).click();
    const products = page.getByRole("region", { name: messages.Account.products.title });
    await products.getByRole("link", { name: messages.Account.products.detailAction }).click();
    await expect(page).toHaveURL(new RegExp(`/${locale}/products/proposal_ai$`), { timeout: 20000 });
    await expect(page.getByRole("link", { name: messages.Purchase.manage })).toBeVisible();
    state.unavailable = true;
    await page.goto(`/${locale}/account`);
    await expect(products.getByRole("article")).toHaveCount(1);
    state.inventoryUnavailable = true;
    await page.reload();
    await expect(products.getByText(messages.Account.products.unavailable)).toBeVisible();
    await expect(products.getByText(messages.Account.products.empty)).toHaveCount(0);
    state.inventoryUnavailable = false;
    await products.getByRole("button", { name: messages.Purchase.retry }).click();
    await expect(products.getByRole("article")).toHaveCount(1);
    state.purchases = [];
    await page.reload();
    await expect(products.getByText(messages.Account.products.empty)).toBeVisible();
    await expect(products.getByRole("article")).toHaveCount(0);
  });
}

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
