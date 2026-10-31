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
    termsChanged: false, catalogUnavailable: false, scriptFailure: false, readyFailure: false,
    confirmations: [] as { key: string; body: unknown }[], advances: 0, advanceDelayMs: 0,
    bootstraps: [] as unknown[], beforeBootstrap: async (): Promise<void> => undefined
  };
  if (signedIn) await page.addInitScript(() => localStorage.setItem("anytoolai_session_token_v1", "synthetic-portal-session"));
  await page.route("https://billing.test/lbxwidget.js", (route) => state.scriptFailure ? route.abort("failed") : route.fulfill({
    contentType: "application/javascript", body: `window.lbxwidget = function(options) {
      return { render: function(id) {
        const node = document.getElementById(id);
        const frame = document.createElement("iframe");
        frame.title = "Synthetic LBX";
        frame.src = "https://billing.test/widget/index.html";
        window.addEventListener("message", function ready(event) {
          if (event.source !== frame.contentWindow || event.origin !== "https://billing.test" || event.data?.type !== "READY") return;
          window.removeEventListener("message", ready);
          frame.contentWindow.postMessage({type:"INIT", payment:!options.disablePayments}, "https://billing.test");
        });
        node.replaceChildren(frame);
        // Neither a host message nor a sibling at the correct provider origin
        // may satisfy readiness for the selected nested Widget window.
        window.postMessage({source:"lbx-widget", type:"READY"}, "*");
        const sibling = document.createElement("iframe");
        sibling.hidden = true;
        sibling.src = "https://billing.test/widget/spoof.html";
        document.body.append(sibling);
      } };
    };`
  }));
  await page.route("https://billing.test/widget/*.html", (route) => route.fulfill({
    contentType: "text/html", body: `<!doctype html><html><body><script>
      window.addEventListener("message", (event) => {
        if (event.source === parent && event.data?.type === "INIT") document.body.textContent = event.data.payment ? "Synthetic payment view" : "Synthetic account view";
      });
      ${!state.readyFailure || route.request().url().endsWith("spoof.html") ? 'parent.postMessage({source:"lbx-widget", type:"READY"}, "*");' : ""}
    </script></body></html>`
  }));
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/session") return route.fulfill({ json: { authenticated: true, user: purchaseUser } });
    if (path.startsWith("/api/catalog/products")) return route.fulfill(state.catalogUnavailable
      ? { status: 503, json: { detail: { code: "catalog_unavailable" } } }
      : { json: path === "/api/catalog/products" ? { products: [simulatedProduct] } : simulatedProduct });
    if (path === "/api/purchase-intents/current") return route.fulfill({ json: { purchase: state.owned } });
    if (path === "/api/purchases/review") return route.fulfill({ json: purchaseReview });
    if (path === "/api/purchase-intents" && route.request().method() === "GET") return route.fulfill({ json: { purchases: state.owned ? [{ ...state.owned, created_at: "2026-10-27T12:00:00Z" }] : [], next_cursor: null } });
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

test("purchase prepares once, then one wide cabinet Widget verifies the selected purchase", async ({ page }, testInfo) => {
  const state = await syntheticBilling(page);
  state.termsChanged = true;
  const panel = await openProduct(page);
  await panel.getByRole("button", { name: ru.Purchase.buy, exact: true }).click();
  await expect(panel.getByRole("button", { name: ru.Purchase.confirm })).toBeDisabled();
  await panel.getByRole("checkbox").check();
  await panel.getByRole("button", { name: ru.Purchase.confirm }).click();
  await expect(panel.getByRole("alert")).toContainText(ru.Billing.errors.termsChanged);
  await panel.getByRole("button", { name: ru.Purchase.buy, exact: true }).click();
  await expect(panel.getByRole("checkbox")).not.toBeChecked();
  await panel.getByRole("checkbox").check();
  await panel.getByRole("button", { name: ru.Purchase.confirm }).click();
  await expect(panel.getByRole("heading", { name: ru.Purchase.states.linked })).toBeVisible();
  await expect(page.locator("iframe")).toHaveCount(0);
  expect(state.bootstraps).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("purchase-prepared.png"), fullPage: true });
  await panel.getByRole("link", { name: ru.Purchase.manage }).click();
  await expect(page).toHaveURL(`${new URL(page.url()).origin}/ru/account?purchase=${savedPurchase.purchase_intent_id}#billing`, { timeout: 20000 });
  const billing = page.getByRole("region", { name: ru.Billing.title });
  await expect(billing.getByRole("combobox")).toHaveValue(savedPurchase.purchase_intent_id);
  expect(state.bootstraps).toEqual([]);
  await billing.getByRole("button", { name: ru.Billing.open, exact: true }).click();
  const frame = page.frameLocator(`iframe[title="${ru.Billing.frameTitle}"]`).frameLocator('iframe[title="Synthetic LBX"]');
  await expect(frame.getByText("Synthetic payment view")).toBeVisible();
  await expect(page.locator("iframe")).toHaveCount(1);
  await expect(billing.getByText(/synthetic-agreement/)).toContainText("synthetic-seller");
  await expect(billing.getByText("Выбранный продукт: proposal_ai")).toBeVisible();
  const products = page.getByRole("region", { name: ru.Account.products.title });
  await expect(products.getByRole("article")).toHaveCount(1);
  await expect(products.getByRole("link", { name: ru.Account.products.allProducts })).toHaveAttribute("href", "/ru/products");
  await expect(products.getByRole("link", { name: ru.Account.products.detailAction })).toHaveAttribute("href", "/ru/products/proposal_ai");
  expect(state.confirmations).toHaveLength(2);
  expect(state.advances).toBe(1);
  expect(state.bootstraps).toEqual([{ purchase_intent_id: savedPurchase.purchase_intent_id }]);
  await page.screenshot({ path: testInfo.outputPath("cabinet-payment.png"), fullPage: true });
  await expect(billing.getByRole("button", { name: ru.Billing.refresh, exact: true })).toHaveAccessibleDescription(ru.Billing.refreshHint);
  await billing.getByRole("button", { name: ru.Billing.refresh, exact: true }).click();
  await expect(frame.getByText("Synthetic payment view")).toBeVisible();
  await expect(page.locator("iframe")).toHaveCount(1);
  await expect(billing.getByRole("combobox")).toHaveValue(savedPurchase.purchase_intent_id);
  expect(state.bootstraps).toEqual(Array(2).fill({ purchase_intent_id: savedPurchase.purchase_intent_id }));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const openAccessibility = await new AxeBuilder({ page }).analyze();
  expect(openAccessibility.violations.filter(({ impact }) => impact === "critical" || impact === "serious")).toEqual([]);
  await billing.getByRole("button", { name: ru.Billing.close }).click();
  await products.getByRole("button", { name: ru.Purchase.manage }).click();
  await expect(frame.getByText("Synthetic payment view")).toBeVisible();
  expect(state.bootstraps).toEqual(Array(3).fill({ purchase_intent_id: savedPurchase.purchase_intent_id }));
  await page.reload();
  await expect(billing.getByRole("combobox")).toHaveValue(savedPurchase.purchase_intent_id);
  await expect(page.locator("iframe")).toHaveCount(0);
  expect(state.bootstraps).toHaveLength(3);
  const storage = await page.evaluate(() => ({ local: { ...localStorage }, session: { ...sessionStorage }, url: location.href }));
  expect(JSON.stringify(storage)).not.toContain("synthetic-widget-token");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations.filter(({ impact }) => impact === "critical" || impact === "serious")).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("cabinet-reload.png"), fullPage: true });
});

test("preparation beyond five seconds produces the compact state without opening billing", async ({ page }) => {
  const state = await syntheticBilling(page);
  state.advanceDelayMs = 5556;
  const panel = await openProduct(page);
  await panel.getByRole("button", { name: ru.Purchase.buy, exact: true }).click();
  await panel.getByRole("checkbox").check();
  await panel.getByRole("button", { name: ru.Purchase.confirm }).click();
  await expect(panel.getByRole("link", { name: ru.Purchase.manage })).toBeVisible({ timeout: 15000 });
  await expect(panel.getByRole("alert")).toHaveCount(0);
  expect(state.confirmations).toHaveLength(1);
  expect(state.advances).toBe(1);
  expect(state.bootstraps).toEqual([]);
});

test("UNKNOWN recovery remains available without catalog and billing can retry the same purchase", async ({ page }, testInfo) => {
  const state = await syntheticBilling(page);
  state.owned = { ...savedPurchase, state: "awaiting_external_result", reason: "purchase_pending" };
  state.catalogUnavailable = true;
  state.scriptFailure = true;
  const panel = await openProduct(page);
  await expect(panel.getByRole("button", { name: ru.Purchase.buy, exact: true })).toHaveCount(0);
  await panel.getByRole("button", { name: ru.Purchase.recover }).click();
  await panel.getByRole("link", { name: ru.Purchase.manage }).click();
  const billing = page.getByRole("region", { name: ru.Billing.title });
  await expect(billing.getByRole("combobox")).toHaveValue(savedPurchase.purchase_intent_id);
  await billing.getByRole("button", { name: ru.Billing.open, exact: true }).click();
  await expect(billing.getByRole("alert")).toContainText(ru.Billing.errors.sdk);
  await expect(billing.getByRole("alert")).toContainText("synthetic-request");
  await page.screenshot({ path: testInfo.outputPath("cabinet-sdk-failure.png"), fullPage: true });
  state.scriptFailure = false;
  await billing.getByRole("button", { name: ru.Billing.open, exact: true }).click();
  await expect(page.frameLocator(`iframe[title="${ru.Billing.frameTitle}"]`).frameLocator('iframe[title="Synthetic LBX"]').getByText("Synthetic payment view")).toBeVisible();
  expect(state.confirmations).toEqual([]);
  expect(state.advances).toBe(1);
  await page.evaluate(() => {
    localStorage.removeItem("anytoolai_session_token_v1");
    window.dispatchEvent(new Event("anytoolai_session_changed"));
  });
  await expect(page.locator("iframe")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: ru.Auth.dialogTitle })).toBeVisible();
});

test("a late payment bootstrap cannot mount after cross-tab logout", async ({ page }) => {
  const state = await syntheticBilling(page);
  state.owned = savedPurchase;
  let finish!: () => void;
  const pending = new Promise<void>((resolve) => { finish = resolve; });
  state.beforeBootstrap = async () => pending;
  const panel = await openProduct(page);
  await panel.getByRole("link", { name: ru.Purchase.manage }).click();
  const billing = page.getByRole("region", { name: ru.Billing.title });
  await expect(billing.getByRole("combobox")).toHaveValue(savedPurchase.purchase_intent_id);
  await billing.getByRole("button", { name: ru.Billing.open, exact: true }).click();
  await expect.poll(() => state.bootstraps.length).toBe(1);
  await page.evaluate(() => {
    localStorage.removeItem("anytoolai_session_token_v1");
    window.dispatchEvent(new StorageEvent("storage", { key: "anytoolai_session_token_v1", storageArea: localStorage }));
  });
  const response = page.waitForResponse((result) => new URL(result.url()).pathname === "/api/billing/widget-bootstrap");
  finish();
  await response;
  await expect(page.getByRole("heading", { name: ru.Auth.dialogTitle })).toBeVisible();
  await expect(page.locator("iframe")).toHaveCount(0);
});

test("an empty cabinet has no catalog cards and account viewing needs no purchase", async ({ page }, testInfo) => {
  const state = await syntheticBilling(page);
  await page.goto("/ru/account");
  await page.getByRole("button", { name: ru.CookieBanner.acceptAction, exact: true }).click();
  await expect(page.getByText(ru.Account.products.empty)).toBeVisible();
  await expect(page.getByRole("article")).toHaveCount(0);
  await page.getByRole("button", { name: ru.Billing.open, exact: true }).click();
  await expect(page.frameLocator(`iframe[title="${ru.Billing.frameTitle}"]`).frameLocator('iframe[title="Synthetic LBX"]').getByText("Synthetic account view")).toBeVisible();
  expect(state.bootstraps).toEqual([{}]);
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations.filter(({ impact }) => impact === "critical" || impact === "serious")).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("cabinet-empty.png"), fullPage: true });
});

test("nested Widget READY timeout keeps a correlated safe error and retries the same purchase", async ({ page }, testInfo) => {
  const state = await syntheticBilling(page);
  state.owned = savedPurchase;
  state.readyFailure = true;
  const diagnostics: string[] = [];
  page.on("console", (message) => { if (message.type() === "warning") diagnostics.push(message.text()); });
  await page.goto(`/ru/account?purchase=${savedPurchase.purchase_intent_id}#billing`);
  await page.getByRole("button", { name: ru.CookieBanner.acceptAction, exact: true }).click();
  const billing = page.getByRole("region", { name: ru.Billing.title });
  await billing.getByRole("button", { name: ru.Billing.open, exact: true }).click();
  await expect(billing.getByRole("alert")).toContainText(ru.Billing.errors.sdk, { timeout: 25000 });
  await expect(billing.getByRole("alert")).toContainText("synthetic-request");
  await expect(page.locator("iframe")).toHaveCount(0);
  expect(diagnostics.filter((entry) => entry.startsWith("billing_widget_load_failed"))).toHaveLength(1);
  expect(diagnostics.join("\n")).toContain("ready_timeout");
  expect(diagnostics.join("\n")).toContain("synthetic-request");
  expect(diagnostics.join("\n")).not.toContain("synthetic-widget-token");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations.filter(({ impact }) => impact === "critical" || impact === "serious")).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("cabinet-ready-timeout.png"), fullPage: true });
  state.readyFailure = false;
  await billing.getByRole("button", { name: ru.Billing.open, exact: true }).click();
  await expect(page.frameLocator(`iframe[title="${ru.Billing.frameTitle}"]`).frameLocator('iframe[title="Synthetic LBX"]').getByText("Synthetic payment view")).toBeVisible();
  // A valid READY cancels the deadline; a loaded checkout must survive it.
  await page.clock.install();
  await page.clock.fastForward(21000);
  await expect(billing.getByRole("alert")).toHaveCount(0);
  expect(state.bootstraps).toEqual(Array(2).fill({ purchase_intent_id: savedPurchase.purchase_intent_id }));
  expect(state.confirmations).toEqual([]);
  expect(state.advances).toBe(0);
  await page.screenshot({ path: testInfo.outputPath("cabinet-ready-retry.png"), fullPage: true });
});
