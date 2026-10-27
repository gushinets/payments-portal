import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import type { PurchaseIntentResponse } from "../src/generated/api-contracts/types.gen";
import ru from "../src/messages/ru.json";
import { simulatedProduct } from "../tests/fixtures/catalog";
import { purchaseReview, purchaseUser, savedPurchase, widgetResponse } from "../tests/fixtures/purchase";

// Browser-only network/SDK substitutions. Every API route is intercepted; no LBX
// writes, payment, access grant or production mock switch is involved.
async function syntheticBilling(page: Page, signedIn = true) {
  const state = {
    owned: null as PurchaseIntentResponse | null,
    termsChanged: false, catalogUnavailable: false, scriptFailure: false,
    confirmations: [] as { key: string; body: unknown }[], advances: 0, advanceDelayMs: 0,
    bootstraps: [] as unknown[], beforeBootstrap: async (): Promise<void> => undefined
  };
  if (signedIn) await page.addInitScript(() => localStorage.setItem("anytoolai_session_token_v1", "synthetic-portal-session"));
  await page.route("https://billing.test/lbxwidget.js", (route) => state.scriptFailure ? route.abort("failed") : route.fulfill({
    contentType: "application/javascript", body: `window.lbxwidget = function(options) {
      return { render: function(id) { document.getElementById(id).textContent = options.disablePayments ? "Synthetic account view" : "Synthetic payment view"; } };
    };`
  }));
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/session") return route.fulfill({ json: { authenticated: true, user: purchaseUser } });
    if (path.startsWith("/api/catalog/products")) return route.fulfill(state.catalogUnavailable
      ? { status: 503, json: { detail: { code: "catalog_unavailable" } } }
      : { json: path === "/api/catalog/products" ? { products: [simulatedProduct] } : simulatedProduct });
    if (path === "/api/purchase-intents/current") return route.fulfill({ json: { purchase: state.owned } });
    if (path === "/api/purchases/review") return route.fulfill({ json: purchaseReview });
    if (path === "/api/purchase-intents") {
      state.confirmations.push({ key: route.request().headers()["idempotency-key"], body: route.request().postDataJSON() });
      if (state.termsChanged) {
        state.termsChanged = false;
        return route.fulfill({ status: 409, json: { detail: { code: "terms_changed", request_id: "synthetic-terms-change" } } });
      }
      state.owned = { ...savedPurchase, state: "created" };
      return route.fulfill({ json: state.owned });
    }
    if (path === `/api/purchase-intents/${savedPurchase.purchase_intent_id}/advance`) {
      state.advances += 1;
      state.owned = savedPurchase;
      if (state.advanceDelayMs) await new Promise((resolve) => setTimeout(resolve, state.advanceDelayMs));
      return route.fulfill({ json: state.owned });
    }
    if (path === `/api/purchase-intents/${savedPurchase.purchase_intent_id}`) return route.fulfill({ json: state.owned });
    if (path === "/api/billing/widget-bootstrap") {
      const body = route.request().postDataJSON();
      state.bootstraps.push(body);
      await state.beforeBootstrap();
      return route.fulfill({ json: widgetResponse(Boolean(body.purchase_intent_id)) });
    }
    return route.fulfill({ status: 503, json: { detail: { code: "synthetic_unexpected_request" } } });
  });
  return state;
}

async function openProduct(page: Page) {
  await page.goto("/ru/products/proposal_ai");
  await page.getByRole("button", { name: ru.CookieBanner.acceptAction, exact: true }).click();
  return page.getByRole("region", { name: ru.Purchase.title });
}

test("guest sees read-only details and a sign-in prompt", async ({ page }) => {
  const state = await syntheticBilling(page, false);
  const panel = await openProduct(page);
  await expect(panel.getByRole("link", { name: ru.Purchase.signIn })).toBeVisible();
  await expect(panel.getByRole("button", { name: ru.Purchase.buy, exact: true })).toHaveCount(0);
  expect(state.confirmations).toEqual([]);
  expect(state.bootstraps).toEqual([]);
});

test("review, changed terms, one purchase, real SDK boundary replacement and unpaid reload", async ({ page }, testInfo) => {
  const state = await syntheticBilling(page);
  state.termsChanged = true;
  const panel = await openProduct(page);
  await panel.getByRole("button", { name: ru.Billing.open, exact: true }).click();
  const frame = page.frameLocator(`iframe[title="${ru.Billing.frameTitle}"]`);
  await expect(frame.getByText("Synthetic account view")).toBeVisible();
  await panel.getByRole("button", { name: ru.Purchase.buy, exact: true }).click();
  await expect(panel.getByRole("button", { name: ru.Purchase.confirm })).toBeDisabled();
  await panel.getByRole("checkbox").check();
  await panel.getByRole("button", { name: ru.Purchase.confirm }).click();
  await expect(panel.getByRole("alert")).toContainText(ru.Billing.errors.termsChanged);
  await panel.getByRole("button", { name: ru.Purchase.buy, exact: true }).click();
  await expect(panel.getByRole("checkbox")).not.toBeChecked();
  await panel.getByRole("checkbox").check();
  await panel.getByRole("button", { name: ru.Purchase.confirm }).click();
  await expect(frame.getByText("Synthetic payment view")).toBeVisible();
  await expect(page.locator(`iframe[title="${ru.Billing.frameTitle}"]`)).toHaveCount(1);
  await expect(panel.getByText(/synthetic-agreement/)).toContainText("synthetic-seller");
  await expect(panel.getByText(ru.Purchase.awaitingVerification)).toBeVisible();
  expect(state.confirmations).toHaveLength(2); // First request was refused before pin.
  expect(state.advances).toBe(1);
  expect(state.bootstraps).toEqual([{}, { purchase_intent_id: savedPurchase.purchase_intent_id }]);
  await page.screenshot({ path: testInfo.outputPath("purchase-payment-synthetic.png"), fullPage: true });
  await panel.getByRole("button", { name: ru.Billing.close }).click();
  await expect(panel.getByRole("button", { name: ru.Purchase.manage })).toBeEnabled();
  await page.reload();
  await expect(panel.getByRole("button", { name: ru.Purchase.manage })).toBeVisible();
  await expect(panel.getByRole("button", { name: ru.Purchase.buy, exact: true })).toHaveCount(0);
  await expect(panel.getByText(ru.Purchase.accessDeferred)).toBeVisible();
  expect(state.confirmations).toHaveLength(2);
  expect(state.advances).toBe(1);
  const storage = await page.evaluate(() => ({ local: { ...localStorage }, session: { ...sessionStorage }, url: location.href }));
  expect(JSON.stringify(storage)).not.toContain("synthetic-widget-token");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations.filter(({ impact }) => impact === "critical" || impact === "serious")).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("purchase-unpaid-reload.png"), fullPage: true });
});

test("preparation beyond five seconds completes without a false unavailable error", async ({ page }) => {
  const state = await syntheticBilling(page);
  state.advanceDelayMs = 5556;
  const panel = await openProduct(page);
  await panel.getByRole("button", { name: ru.Purchase.buy, exact: true }).click();
  await panel.getByRole("checkbox").check();
  await panel.getByRole("button", { name: ru.Purchase.confirm }).click();
  await expect(page.frameLocator(`iframe[title="${ru.Billing.frameTitle}"]`).getByText("Synthetic payment view")).toBeVisible({ timeout: 15000 });
  await expect(panel.getByRole("alert")).toHaveCount(0);
  expect(state.confirmations).toHaveLength(1);
  expect(state.advances).toBe(1);
  expect(state.bootstraps).toEqual([{ purchase_intent_id: savedPurchase.purchase_intent_id }]);
});

test("UNKNOWN recovery works without catalog and script failure can retry the same purchase", async ({ page }, testInfo) => {
  const state = await syntheticBilling(page);
  state.owned = { ...savedPurchase, state: "awaiting_external_result", reason: "purchase_pending" };
  state.catalogUnavailable = true;
  state.scriptFailure = true;
  const panel = await openProduct(page);
  await expect(panel.getByRole("button", { name: ru.Purchase.buy, exact: true })).toHaveCount(0);
  await panel.getByRole("button", { name: ru.Purchase.recover }).click();
  await expect(panel.getByRole("alert")).toContainText(ru.Billing.errors.sdk);
  await expect(panel.getByRole("alert")).toContainText("synthetic-request");
  await page.screenshot({ path: testInfo.outputPath("purchase-sdk-failure.png"), fullPage: true });
  state.scriptFailure = false;
  await panel.getByRole("button", { name: ru.Purchase.manage }).click();
  await expect(page.frameLocator(`iframe[title="${ru.Billing.frameTitle}"]`).getByText("Synthetic payment view")).toBeVisible();
  expect(state.confirmations).toEqual([]);
  expect(state.advances).toBe(1);
  await page.evaluate(() => {
    localStorage.removeItem("anytoolai_session_token_v1");
    window.dispatchEvent(new Event("anytoolai_session_changed"));
  });
  await expect(page.locator(`iframe[title="${ru.Billing.frameTitle}"]`)).toHaveCount(0);
  await expect(panel.getByRole("link", { name: ru.Purchase.signIn })).toBeVisible();
});

test("a late payment bootstrap cannot mount after cross-tab logout", async ({ page }) => {
  const state = await syntheticBilling(page);
  state.owned = savedPurchase;
  let finish!: () => void;
  const pending = new Promise<void>((resolve) => { finish = resolve; });
  state.beforeBootstrap = async () => pending;
  const panel = await openProduct(page);
  await panel.getByRole("button", { name: ru.Purchase.manage }).click();
  await expect.poll(() => state.bootstraps.length).toBe(1);
  await page.evaluate(() => {
    localStorage.removeItem("anytoolai_session_token_v1");
    window.dispatchEvent(new StorageEvent("storage", { key: "anytoolai_session_token_v1", storageArea: localStorage }));
  });
  const response = page.waitForResponse((result) => new URL(result.url()).pathname === "/api/billing/widget-bootstrap");
  finish();
  await response;
  await expect(panel.getByRole("link", { name: ru.Purchase.signIn })).toBeVisible();
  await expect(page.locator(`iframe[title="${ru.Billing.frameTitle}"]`)).toHaveCount(0);
});
