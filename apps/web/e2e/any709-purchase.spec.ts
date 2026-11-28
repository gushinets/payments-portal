import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import type { PurchaseIntentResponse } from "../src/generated/api-contracts/types.gen";
import ru from "../src/messages/ru.json";
import { simulatedProduct } from "../tests/fixtures/catalog";
import { emptyPaidState } from "../tests/fixtures/paid-access";
import { purchaseReview, purchaseUser, savedPurchase, widgetResponse } from "../tests/fixtures/purchase";

// Browser-only network/SDK substitutions. Every API route is intercepted; no LBX
// writes, payment, access grant or production mock switch is involved.
async function syntheticBilling(page: Page, signedIn = true) {
  const state = {
    owned: null as PurchaseIntentResponse | null,
    review: purchaseReview, nextPurchaseId: savedPurchase.purchase_intent_id, lateCaseOpen: false,
    termsChanged: false, catalogUnavailable: false, scriptFailure: false, readyFailure: false,
    confirmations: [] as { key: string; body: unknown }[], advances: 0, advanceDelayMs: 0,
    advanceState: "linked" as PurchaseIntentResponse["state"],
    beforeAdvance: async (): Promise<void> => undefined,
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
    if (path === "/api/paid-access") return route.fulfill({ json: emptyPaidState() });
    if (path === "/api/paid-usage") return route.fulfill({ json: { access_revision: 0, items: [] } });
    if (path.startsWith("/api/catalog/products")) return route.fulfill(state.catalogUnavailable
      ? { status: 503, json: { detail: { code: "catalog_unavailable" } } }
      : { json: path === "/api/catalog/products" ? { products: [simulatedProduct] } : simulatedProduct });
    if (path === "/api/purchase-intents/current") return route.fulfill({ json: { purchase: state.owned?.scope_held ? state.owned : null } });
    if (path === "/api/purchases/review") return route.fulfill({ json: state.review });
    if (path === "/api/purchase-intents" && route.request().method() === "GET") return route.fulfill({ json: { purchases: state.owned?.scope_held ? [{ ...state.owned, created_at: "2026-10-27T12:00:00Z" }] : [], next_cursor: null } });
    if (path === "/api/purchase-intents") {
      state.confirmations.push({ key: route.request().headers()["idempotency-key"], body: route.request().postDataJSON() });
      if (state.termsChanged) {
        state.termsChanged = false;
        return route.fulfill({ status: 409, json: { detail: { code: "terms_changed", request_id: "synthetic-terms-change" } } });
      }
      state.owned = { ...savedPurchase, purchase_intent_id: state.nextPurchaseId, accepted: state.review, state: "created" };
      return route.fulfill({ json: state.owned });
    }
    if (state.owned && path === `/api/purchase-intents/${state.owned.purchase_intent_id}/advance`) {
      state.advances += 1;
      if (state.lateCaseOpen) return route.fulfill({ status: 409, json: { detail: { code: "purchase_existing_subscription_review" } } });
      state.owned = { ...state.owned, state: state.advanceState, reason: null };
      await state.beforeAdvance();
      if (state.advanceDelayMs) await new Promise((resolve) => setTimeout(resolve, state.advanceDelayMs));
      return route.fulfill({ json: state.owned });
    }
    if (path === `/api/purchase-intents/${state.owned?.purchase_intent_id ?? savedPurchase.purchase_intent_id}`) return route.fulfill({ json: state.owned });
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

test("unavailable offers disable new Buy while saved purchases remain resumable", async ({ page }, testInfo) => {
  const state = await syntheticBilling(page);
  await page.route("**/api/catalog/products/proposal_ai", (route) => route.fulfill(state.catalogUnavailable
    ? { status: 503, json: { detail: { code: "catalog_unavailable" } } }
    : { json: { ...simulatedProduct, availability: "UNMAPPED", offer: null } }));
  const panel = await openProduct(page);
  await expect(panel.getByRole("button", { name: ru.Purchase.buy, exact: true })).toBeDisabled();
  await expect(page.getByText(ru.CatalogPreview.unmapped)).toBeVisible();
  expect(state.confirmations).toEqual([]);
  expect(state.bootstraps).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("unavailable-buy.png"), fullPage: true });
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations.filter(({ impact }) => impact === "critical" || impact === "serious")).toEqual([]);
  state.owned = { ...savedPurchase, state: "created" };
  state.catalogUnavailable = true;
  await page.reload();
  await panel.getByRole("button", { name: ru.Purchase.continue, exact: true }).click();
  await expect(panel.getByRole("link", { name: ru.Billing.pay })).toBeVisible();
  expect(state.advances).toBe(1);
  expect(state.confirmations).toEqual([]);
});

test("guest sees read-only details and a sign-in prompt", async ({ page }) => {
  const state = await syntheticBilling(page, false);
  const panel = await openProduct(page);
  await expect(panel.getByRole("link", { name: ru.Purchase.signIn })).toBeVisible();
  await expect(panel.getByRole("button", { name: ru.Purchase.buy, exact: true })).toHaveCount(0);
  expect(state.confirmations).toEqual([]);
  expect(state.bootstraps).toEqual([]);
});

test("one-click payment shows the verified target before Widget READY after session loading and scroll", async ({ page }) => {
  await page.setViewportSize({ width: 568, height: 320 });
  const state = await syntheticBilling(page);
  state.owned = savedPurchase;
  state.readyFailure = true;
  const bootstrapReply = Promise.withResolvers<void>();
  state.beforeBootstrap = () => bootstrapReply.promise;

  const panel = await openProduct(page);
  const sessionStarted = Promise.withResolvers<void>();
  const sessionReply = Promise.withResolvers<void>();
  await page.route("**/api/auth/session", async (route) => {
    sessionStarted.resolve();
    await sessionReply.promise;
    await route.fallback();
  });

  const billing = page.getByRole("region", { name: ru.Billing.title });
  try {
    await panel.getByRole("link", { name: ru.Billing.pay }).click();
    await sessionStarted.promise;
    await expect(billing).toHaveCount(0);
    sessionReply.resolve();
    await expect.poll(() => state.bootstraps.length).toBe(1);
    await page.mouse.move(540, 275);
    await page.mouse.wheel(0, 305);
    await expect.poll(() => billing.evaluate((section) => section.getBoundingClientRect().top)).toBeLessThan(-100);
  } finally {
    sessionReply.resolve();
    bootstrapReply.resolve();
  }

  const paymentTarget = billing.getByText(/synthetic-agreement/);
  await expect(paymentTarget).toContainText("synthetic-seller");
  await expect(paymentTarget).toBeInViewport({ ratio: 1 });
  await expect.poll(() => paymentTarget.evaluate((element) => {
    const header = document.querySelector(".top-nav")!;
    return element.getBoundingClientRect().top - header.getBoundingClientRect().bottom;
  })).toBeGreaterThanOrEqual(0);
  await expect(billing.getByRole("button", { name: ru.Billing.loading })).toBeDisabled();
  expect(state.bootstraps).toEqual([{ purchase_intent_id: savedPurchase.purchase_intent_id }]);
});

test("keyboard focus survives retrying the initial saved-link request", async ({ page }, testInfo) => {
  const state = await syntheticBilling(page);
  const purchaseId = savedPurchase.purchase_intent_id;
  const retryReply = Promise.withResolvers<void>();
  const statusRequests: string[] = [];
  await page.route(`**/api/purchase-intents/${purchaseId}`, async (route) => {
    statusRequests.push(route.request().method());
    if (statusRequests.length === 1) return route.fulfill({
      status: 503, json: { detail: { code: "unavailable", request_id: "synthetic-initial-status" } }
    });
    await retryReply.promise;
    return route.fulfill({ json: { ...savedPurchase, state: "resolved_external_terminal", scope_held: false } });
  });

  await page.goto(`/ru/account?purchase=${purchaseId}#billing`);
  await page.getByRole("button", { name: ru.CookieBanner.acceptAction, exact: true }).click();
  const billing = page.getByRole("region", { name: ru.Billing.title });
  const refresh = billing.getByRole("button", { name: ru.Purchase.refresh });
  const selector = billing.getByRole("combobox");
  try {
    await expect(billing.getByRole("alert")).toContainText("synthetic-initial-status");
    await refresh.focus();
    await page.keyboard.press("Enter");
    await expect(refresh).toBeFocused();
    await expect(refresh).toHaveAttribute("aria-disabled", "true");
    await expect(refresh).toHaveCSS("outline-style", "solid");
    await expect(selector).toBeDisabled();
    await expect(billing.getByRole("status")).toHaveText(ru.Purchase.loading);
    await expect.poll(() => statusRequests).toEqual(["GET", "GET"]);
    await page.keyboard.press("Enter");
    await page.evaluate(() => document.fonts.ready);
    expect((await new AxeBuilder({ page }).include("#billing").analyze()).violations).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath("saved-link-retry-focus.png"), fullPage: true });
  } finally {
    retryReply.resolve();
  }

  await expect(billing.getByText(ru.Purchase.states.resolved_external_terminal)).toBeVisible();
  await expect(selector).toHaveValue(purchaseId);
  await expect(selector).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(billing.getByRole("link", { name: ru.Purchase.buy, exact: true })).toBeFocused();
  expect(statusRequests).toEqual(["GET", "GET"]);
  expect(state.bootstraps).toEqual([]);
});

for (const scenario of ["manual retry", "automatic recovery after another 503", "manual retry after scrolling"] as const) {
  test(`keyboard focus survives a saved-link status recheck with ${scenario}`, async ({ page }, testInfo) => {
    const automaticRecovery = scenario === "automatic recovery after another 503";
    const scrolled = scenario === "manual retry after scrolling";
    if (scrolled) await page.setViewportSize({ width: 393, height: 350 });

    const state = await syntheticBilling(page);
    state.owned = savedPurchase;
    const purchaseId = savedPurchase.purchase_intent_id;
    const listReply = Promise.withResolvers<void>();
    const retryReply = Promise.withResolvers<void>();
    let firstStatus = true;
    let retryStarted = false;
    let repeatedFailure = false;
    let terminalReadStarted = false;
    await page.route("**/api/purchase-intents", async (route) => {
      await listReply.promise;
      return route.fulfill({ json: { purchases: [], next_cursor: null } });
    });
    await page.route(`**/api/purchase-intents/${purchaseId}`, async (route) => {
      if (firstStatus) {
        firstStatus = false;
        return route.fulfill({ json: savedPurchase });
      }
      if (!retryStarted) return route.fulfill({
        status: 503, json: { detail: { code: "unavailable", request_id: "synthetic-status-recheck" } }
      });
      if (automaticRecovery && !repeatedFailure) {
        repeatedFailure = true;
        return route.fulfill({
          status: 503, json: { detail: { code: "unavailable", request_id: "synthetic-status-recheck-repeat" } }
        });
      }
      terminalReadStarted = true;
      await retryReply.promise;
      return route.fulfill({ json: { ...savedPurchase, state: "resolved_external_terminal", scope_held: false } });
    });

    const billing = page.getByRole("region", { name: ru.Billing.title });
    const selector = billing.getByRole("combobox");
    const widget = billing.getByTitle(ru.Billing.frameTitle);
    const alert = billing.getByRole("alert");
    const retry = alert.getByRole("button", { name: ru.Purchase.refresh });
    const navigation = page.getByRole("banner");
    const selectorPosition = () => selector.evaluate(element => {
      const { top, bottom } = element.getBoundingClientRect();
      return { top, bottom, viewportBottom: window.innerHeight };
    });
    try {
      await page.goto(`/ru/account?purchase=${purchaseId}#billing`);
      await page.getByRole("button", { name: ru.CookieBanner.acceptAction, exact: true }).click();
      await billing.getByRole("button", { name: ru.Billing.pay, exact: true }).click();
      await expect(billing.frameLocator(`iframe[title="${ru.Billing.frameTitle}"]`)
        .frameLocator('iframe[title="Synthetic LBX"]').getByText("Synthetic payment view")).toBeVisible();
      listReply.resolve();
      await expect(alert).toContainText("synthetic-status-recheck");
      await expect(widget).toBeHidden();

      await retry.focus();
      if (scrolled) {
        await page.evaluate(() => document.fonts.ready);
        const navigationBottom = await navigation.evaluate(element => element.getBoundingClientRect().bottom);
        await retry.evaluate((button, bottom) => {
          window.scrollBy({ top: button.getBoundingClientRect().top - bottom - 12, behavior: "instant" });
        }, navigationBottom);
        expect((await selectorPosition()).bottom).toBeLessThan(navigationBottom);
        expect(await retry.evaluate(button => button.getBoundingClientRect().top)).toBeGreaterThan(navigationBottom);
        await expect(retry).toBeInViewport();
      }
      await expect(retry).toBeFocused();
      retryStarted = true;
      await page.keyboard.press("Enter");
      await expect(selector).toBeFocused();
      await expect(widget).toBeHidden();
      if (scrolled) {
        const navigationBottom = await navigation.evaluate(element => element.getBoundingClientRect().bottom);
        const { top, bottom, viewportBottom } = await selectorPosition();
        expect(top).toBeGreaterThanOrEqual(navigationBottom);
        expect(bottom).toBeLessThanOrEqual(viewportBottom);
        expect(await selector.evaluate(element => element.matches(":focus-visible"))).toBe(true);
      }
      if (automaticRecovery) {
        await expect(alert).toContainText("synthetic-status-recheck-repeat");
        await page.keyboard.press("Tab");
        await expect(retry).toBeFocused();
        await expect.poll(() => terminalReadStarted).toBe(true);
        await expect(retry).toBeFocused();
      }
      await page.evaluate(() => document.fonts.ready);
      expect((await new AxeBuilder({ page }).include("#billing").analyze()).violations).toEqual([]);
      await page.screenshot({ path: testInfo.outputPath("saved-link-recheck-focus.png"), fullPage: true });
    } finally {
      listReply.resolve();
      retryReply.resolve();
    }

    await expect(billing.getByText(ru.Purchase.states.resolved_external_terminal)).toBeVisible();
    await expect(selector).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(billing.getByRole("link", { name: ru.Purchase.buy, exact: true })).toBeFocused();
    await expect(widget).toHaveCount(0);
    expect(state.bootstraps).toEqual([{ purchase_intent_id: purchaseId }]);
  });
}

test("a saved purchase link leads through operator completion to a fresh replacement", async ({ page }, testInfo) => {
  const state = await syntheticBilling(page);
  const originalId = savedPurchase.purchase_intent_id;
  const replacementId = "55555555-5555-4555-8555-555555555555";
  state.advanceState = "manual_review";
  const panel = await openProduct(page);
  await panel.getByRole("button", { name: ru.Purchase.buy, exact: true }).click();
  await panel.getByRole("checkbox").check();
  await panel.getByRole("button", { name: ru.Purchase.confirm }).click();
  const statusLink = panel.getByRole("link", { name: ru.Purchase.statusLink });
  await expect(statusLink).toHaveAttribute("href", `/ru/account?purchase=${originalId}#billing`);
  expect(state.confirmations).toHaveLength(1);
  const originalKey = state.confirmations[0].key;
  expect(originalKey).toEqual(expect.any(String));
  await statusLink.click();
  const billing = page.getByRole("region", { name: ru.Billing.title });
  await expect(billing.getByRole("combobox")).toHaveValue(originalId);
  await expect(billing.getByText(ru.Purchase.states.manual_review)).toBeVisible();

  state.owned = { ...savedPurchase, state: "resolved_external_terminal", scope_held: false };
  await billing.getByRole("button", { name: ru.Purchase.refresh }).click();
  await expect(billing.getByText(ru.Purchase.states.resolved_external_terminal)).toBeVisible();
  await page.reload();
  await expect(billing.getByRole("combobox")).toHaveValue(originalId);
  await expect(billing.getByText(ru.Purchase.states.resolved_external_terminal)).toBeVisible();
  await expect(billing.getByRole("button", { name: ru.Billing.open, exact: true })).toBeDisabled();
  await expect(page.locator("iframe")).toHaveCount(0);
  expect(state.bootstraps).toEqual([]);
  await page.evaluate(() => document.fonts.ready);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect((await new AxeBuilder({ page }).include("#billing").analyze()).violations).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("terminal-purchase.png"), fullPage: true });

  const newDocument = {
    ...purchaseReview.documents[0],
    document_version_id: "66666666-6666-4666-8666-666666666666",
    acceptance_text_hash: "f".repeat(64),
    version: "synthetic-v2",
    acceptance_text: "Я принимаю обновлённые тестовые условия оферты."
  };
  state.review = {
    ...purchaseReview,
    terms: { ...purchaseReview.terms, recurring_amount: "150" },
    expected_fingerprint: "sha256:" + "d".repeat(64),
    documents: [newDocument]
  };
  state.nextPurchaseId = replacementId;
  state.advanceState = "linked";
  state.lateCaseOpen = true;
  await billing.getByRole("link", { name: ru.Purchase.buy, exact: true }).click();
  await panel.getByRole("button", { name: ru.Purchase.buy, exact: true }).click();
  const freshConsent = panel.getByRole("checkbox", { name: newDocument.acceptance_text });
  await expect(freshConsent).not.toBeChecked();
  await expect(panel.getByText("150 RUB", { exact: true })).toBeVisible();
  await expect(panel.getByRole("button", { name: ru.Purchase.confirm })).toBeDisabled();
  expect(state.confirmations).toHaveLength(1);
  expect(state.advances).toBe(1);
  await page.evaluate(() => document.fonts.ready);
  expect((await new AxeBuilder({ page }).include(".purchase-panel").analyze()).violations).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("replacement-consent.png"), fullPage: true });

  await freshConsent.check();
  const firstAdvance = page.waitForResponse(response => new URL(response.url()).pathname.endsWith(`/${replacementId}/advance`));
  await panel.getByRole("button", { name: ru.Purchase.confirm }).click();
  expect((await firstAdvance).status()).toBe(409);
  await expect(panel.getByRole("alert")).toContainText(ru.Billing.errors.purchaseConflict);
  await expect(panel.getByText(ru.Purchase.reference.replace("{id}", replacementId))).toBeVisible();
  await expect(panel.getByRole("button", { name: ru.Purchase.buy, exact: true })).toHaveCount(0);
  expect(state.confirmations).toHaveLength(2);
  expect(state.confirmations[1]).toEqual(expect.objectContaining({
    key: expect.any(String), body: expect.objectContaining({
      expected_fingerprint: state.review.expected_fingerprint,
      documents: state.review.documents.map(({ document_version_id, acceptance_text_hash }) => ({ document_version_id, acceptance_text_hash })),
    }),
  }));
  expect(state.confirmations[1].key).not.toBe(originalKey);
  expect(state.advances).toBe(2);

  state.lateCaseOpen = false;
  await panel.getByRole("button", { name: ru.Purchase.continue, exact: true }).click();
  await expect(panel.getByRole("link", { name: ru.Billing.pay })).toHaveAttribute("href", `/ru/account?purchase=${replacementId}#billing`);
  expect(state.confirmations).toHaveLength(2);
  expect(state.advances).toBe(3);
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
  const acceptedAt = performance.now();
  const confirmation = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/purchase-intents" && response.request().method() === "POST")
    .then(() => performance.now());
  const advanced = page.waitForResponse((response) => new URL(response.url()).pathname.endsWith("/advance"))
    .then(() => performance.now());
  await panel.getByRole("button", { name: ru.Purchase.confirm }).click();
  await expect(panel.getByRole("heading", { name: ru.Purchase.states.linked })).toBeVisible();
  const preparedAt = performance.now();
  await expect(page.locator("iframe")).toHaveCount(0);
  expect(state.bootstraps).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("purchase-prepared.png"), fullPage: true });
  const bootstrapPath = "/api/billing/widget-bootstrap";
  const bootstrapStart = page.waitForRequest((request) => new URL(request.url()).pathname === bootstrapPath)
    .then(() => performance.now());
  const bootstrapEnd = page.waitForResponse((response) => new URL(response.url()).pathname === bootstrapPath)
    .then(() => performance.now());
  const paymentClickAt = performance.now();
  await panel.getByRole("link", { name: ru.Billing.pay }).click();
  await expect(page).toHaveURL(`${new URL(page.url()).origin}/ru/account?purchase=${savedPurchase.purchase_intent_id}#billing`, { timeout: 20000 });
  const billing = page.getByRole("region", { name: ru.Billing.title });
  await expect(billing.getByRole("combobox")).toHaveValue(savedPurchase.purchase_intent_id);
  const frame = page.frameLocator(`iframe[title="${ru.Billing.frameTitle}"]`).frameLocator('iframe[title="Synthetic LBX"]');
  await expect(frame.getByText("Synthetic payment view")).toBeVisible();
  const readyAt = performance.now();
  const viewportHeight = await page.evaluate(() => window.innerHeight);
  await expect.poll(() => frame.locator("html").evaluate((element) => element.clientHeight))
    .toBeGreaterThanOrEqual(Math.max(800, viewportHeight));
  const bootstrapStartedAt = await bootstrapStart;
  const bootstrapFinishedAt = await bootstrapEnd;
  const confirmedAt = await confirmation;
  await testInfo.attach("synthetic-purchase-timings", {
    contentType: "application/json",
    body: JSON.stringify({
      confirmationMs: Math.round(confirmedAt - acceptedAt),
      advanceMs: Math.round(await advanced - confirmedAt),
      preparationVisibleMs: Math.round(preparedAt - acceptedAt),
      waitBeforePaymentClickMs: Math.round(paymentClickAt - preparedAt),
      navigationToBootstrapMs: Math.round(bootstrapStartedAt - paymentClickAt),
      bootstrapMs: Math.round(bootstrapFinishedAt - bootstrapStartedAt),
      widgetReadyMs: Math.round(readyAt - bootstrapFinishedAt),
      acceptanceToWidgetReadyMs: Math.round(readyAt - acceptedAt)
    })
  });
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
  await expect(panel.getByRole("link", { name: ru.Billing.pay })).toBeVisible({ timeout: 15000 });
  await expect(panel.getByRole("alert")).toHaveCount(0);
  expect(state.confirmations).toHaveLength(1);
  expect(state.advances).toBe(1);
  expect(state.bootstraps).toEqual([]);
});

test("keyboard recovery keeps focus until polling offers payment", async ({ page }) => {
  const state = await syntheticBilling(page);
  state.owned = { ...savedPurchase, state: "awaiting_external_result" };
  state.advanceState = "awaiting_external_result";
  state.advanceDelayMs = 12_000;
  const panel = await openProduct(page);
  const continuation = panel.getByRole("button", { name: ru.Purchase.continue, exact: true });
  await continuation.focus();
  await page.keyboard.press("Enter");
  await expect.poll(() => state.advances).toBe(1);
  await expect(continuation).toBeDisabled();
  await expect(continuation).toBeFocused();
  await page.keyboard.press("Enter");

  state.owned = savedPurchase;
  await expect(panel.getByRole("link", { name: ru.Billing.pay })).toBeFocused({ timeout: 9000 });
  expect(state.confirmations).toEqual([]);
  expect(state.advances).toBe(1);
  expect(state.bootstraps).toEqual([]);
});

for (const outcome of ["payment", "session refusal"] as const) {
  test(`keyboard confirmation keeps focus through ${outcome}`, async ({ page }) => {
    const state = await syntheticBilling(page);
    const confirmationReply = Promise.withResolvers<void>();
    const advanceReply = Promise.withResolvers<void>();
    let confirmationRequests = 0;
    state.beforeAdvance = () => advanceReply.promise;
    await page.route("**/api/purchase-intents", async (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      confirmationRequests += 1;
      await confirmationReply.promise;
      return outcome === "payment" ? route.fallback() : route.abort("failed");
    });
    if (outcome !== "payment") {
      await page.route("**/api/purchase-intents/current?*", (route) => confirmationRequests
        ? route.fulfill({ status: 401, json: { detail: { code: "billing_session_required" } } })
        : route.fallback());
    }

    const panel = await openProduct(page);
    try {
      await panel.getByRole("button", { name: ru.Purchase.buy, exact: true }).click();
      await panel.getByRole("checkbox").check();
      await panel.getByRole("button", { name: ru.Purchase.confirm, exact: true }).focus();
      await page.keyboard.press("Enter");
      const retry = panel.getByRole("button", { name: ru.Purchase.retryConfirm });
      await expect.poll(() => confirmationRequests).toBe(1);
      await expect(retry).toBeDisabled();
      await expect(retry).toBeFocused();
      await page.keyboard.press("Enter");

      confirmationReply.resolve();

      if (outcome === "payment") {
        await expect(panel.getByRole("button", { name: ru.Purchase.continue, exact: true })).toBeFocused();
        await expect(panel.getByRole("link", { name: ru.Billing.pay })).toBeFocused({ timeout: 9000 });
        expect(state.advances).toBe(1);
      } else {
        await expect(panel.getByRole("alert")).toContainText(ru.Billing.errors.session);
        await expect(retry).toBeDisabled();
        await expect(panel.getByRole("button", { name: ru.Purchase.refresh })).toBeFocused();
        expect(state.advances).toBe(0);
      }
      expect(confirmationRequests).toBe(1);
      expect(state.bootstraps).toEqual([]);
    } finally {
      confirmationReply.resolve();
      advanceReply.resolve();
    }
  });
}

test("recovered agreement allows explicit continuation of the same purchase", async ({ page }, testInfo) => {
  const state = await syntheticBilling(page);
  state.advanceState = "awaiting_external_result";
  const panel = await openProduct(page);
  await panel.getByRole("button", { name: ru.Purchase.buy, exact: true }).click();
  await panel.getByRole("checkbox").check();
  await panel.getByRole("button", { name: ru.Purchase.confirm }).click();
  await expect(panel.getByText(ru.Purchase.states.awaiting_external_result)).toBeVisible();

  state.owned = { ...savedPurchase, state: "preparing", reason: "purchase_pending" };
  const continuation = panel.getByRole("button", { name: ru.Purchase.continue, exact: true });
  await expect(continuation).toBeEnabled();
  await expect(panel.getByText(ru.Purchase.states.awaiting_external_result)).toHaveCount(0);
  expect(state.confirmations).toHaveLength(1);
  expect(state.advances).toBe(1);
  await page.screenshot({ path: testInfo.outputPath("agreement-recovered.png"), fullPage: true });
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations.filter(({ impact }) => impact === "critical" || impact === "serious")).toEqual([]);

  state.advanceState = "linked";
  await continuation.click();
  await expect(panel.getByRole("link", { name: ru.Billing.pay })).toBeVisible();
  expect(state.confirmations).toHaveLength(1);
  expect(state.advances).toBe(2);
  expect(state.bootstraps).toEqual([]);
});

test("UNKNOWN recovery remains available without catalog and billing can retry the same purchase", async ({ page }, testInfo) => {
  const state = await syntheticBilling(page);
  state.owned = { ...savedPurchase, state: "awaiting_external_result", reason: "purchase_pending" };
  state.catalogUnavailable = true;
  state.scriptFailure = true;
  const panel = await openProduct(page);
  await expect(panel.getByText(ru.Purchase.states.awaiting_external_result)).toBeVisible();
  await expect(panel.getByRole("button", { name: ru.Purchase.buy, exact: true })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("purchase-saved.png"), fullPage: true });
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations.filter(({ impact }) => impact === "critical" || impact === "serious")).toEqual([]);
  await panel.getByRole("button", { name: ru.Purchase.continue, exact: true }).click();
  await panel.getByRole("link", { name: ru.Billing.pay }).click();
  const billing = page.getByRole("region", { name: ru.Billing.title });
  await expect(billing.getByRole("combobox")).toHaveValue(savedPurchase.purchase_intent_id);
  await expect(billing.getByRole("alert")).toContainText(ru.Billing.errors.sdk);
  await expect(billing.getByRole("alert")).toContainText("synthetic-request");
  await page.screenshot({ path: testInfo.outputPath("cabinet-sdk-failure.png"), fullPage: true });
  state.scriptFailure = false;
  await billing.getByRole("button", { name: ru.Billing.pay, exact: true }).click();
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
  await panel.getByRole("link", { name: ru.Billing.pay }).click();
  const billing = page.getByRole("region", { name: ru.Billing.title });
  await expect(billing.getByRole("combobox")).toHaveValue(savedPurchase.purchase_intent_id);
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
  await billing.getByRole("button", { name: ru.Billing.pay, exact: true }).click();
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
  await billing.getByRole("button", { name: ru.Billing.pay, exact: true }).click();
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

test("returning to an abandoned account visit requires a fresh payment click", async ({ page }) => {
  const state = await syntheticBilling(page);
  state.owned = savedPurchase;
  const path = "/api/purchase-intents/" + savedPurchase.purchase_intent_id;
  let unblock!: () => void;
  const blocked = new Promise<void>((resolve) => { unblock = resolve; });
  let reads = 0;
  await page.route("**" + path, async (route) => {
    reads += 1;
    if (reads === 1) await blocked;
    await route.fulfill({ json: savedPurchase });
  });

  const panel = await openProduct(page);
  const firstCheck = page.waitForRequest((request) => new URL(request.url()).pathname === path);
  await panel.getByRole("link", { name: ru.Billing.pay }).click();
  await firstCheck;
  const billing = page.getByRole("region", { name: ru.Billing.title });
  await expect(billing.getByRole("combobox")).toBeDisabled();
  await page.evaluate(() => window.history.back());
  await expect(panel.getByRole("link", { name: ru.Billing.pay })).toBeVisible();
  unblock();

  const secondCheck = page.waitForResponse((response) => new URL(response.url()).pathname === path);
  await page.evaluate(() => window.history.forward());
  await secondCheck;
  const pay = billing.getByRole("button", { name: ru.Billing.pay, exact: true });
  await expect(pay).toBeEnabled({ timeout: 4000 });
  expect(state.bootstraps).toEqual([]);

  await pay.click();
  await expect(billing.getByRole("button", { name: ru.Billing.refresh })).toBeEnabled();
  expect(state.bootstraps).toEqual([{ purchase_intent_id: savedPurchase.purchase_intent_id }]);
});

test("an expired session closes checkout and moves focus from the Widget to Retry", async ({ page }, testInfo) => {
  const state = await syntheticBilling(page);
  state.owned = savedPurchase;
  const purchasePath = "/api/purchase-intents/" + savedPurchase.purchase_intent_id;
  let permitListRead!: () => void;
  const beforeListRead = new Promise<void>((resolve) => { permitListRead = resolve; });
  let revoked = false;
  await page.route("**/api/purchase-intents", async (route) => {
    await beforeListRead;
    return route.fulfill({ json: { purchases: [{
      purchase_intent_id: savedPurchase.purchase_intent_id,
      product_id: savedPurchase.product_id,
      state: "manual_review",
      created_at: "2026-10-27T12:00:00Z",
    }], next_cursor: null } });
  });
  await page.route("**" + purchasePath, async (route) => {
    return route.fulfill(revoked
      ? { status: 401, json: { detail: { code: "billing_session_required", request_id: "revoked-session" } } }
      : { json: savedPurchase });
  });

  await page.goto(`/ru/account?purchase=${savedPurchase.purchase_intent_id}#billing`);
  await page.getByRole("button", { name: ru.CookieBanner.acceptAction, exact: true }).click();
  const billing = page.getByRole("region", { name: ru.Billing.title });
  await expect(billing.getByRole("button", { name: ru.Billing.pay })).toBeEnabled();
  expect(state.bootstraps).toEqual([]);
  await billing.getByRole("button", { name: ru.Billing.pay }).click();
  await expect(billing.getByRole("button", { name: ru.Billing.refresh })).toBeEnabled();
  const widget = billing.locator("iframe");
  await widget.focus();
  await expect(widget).toBeFocused();

  revoked = true;
  const refusal = page.waitForResponse((response) => new URL(response.url()).pathname === purchasePath && response.status() === 401);
  permitListRead();
  await refusal;

  await expect(billing.getByRole("button", { name: ru.Billing.open })).toBeDisabled();
  await expect(billing.locator("iframe")).toHaveCount(0);
  expect(state.bootstraps).toEqual([{ purchase_intent_id: savedPurchase.purchase_intent_id }]);
  await expect(billing.getByText(ru.Purchase.loading, { exact: true })).toHaveCount(0, { timeout: 4000 });
  await expect(billing.getByRole("alert")).toContainText(ru.Billing.errors.session);
  await expect(billing.getByRole("alert")).toContainText("revoked-session");
  await expect(billing.getByRole("button", { name: ru.Purchase.retry })).toBeFocused();
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations.filter(({ impact }) => impact === "critical" || impact === "serious")).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("cabinet-expired-session-focus.png"), fullPage: true });
});

test("a paid-access refresh closes expired checkout and lets the buyer sign in again", async ({ page }) => {
  const state = await syntheticBilling(page);
  state.owned = savedPurchase;
  await page.goto("/ru/account");
  await page.getByRole("button", { name: ru.CookieBanner.acceptAction, exact: true }).click();
  const billing = page.getByRole("region", { name: ru.Billing.title });
  await billing.getByRole("button", { name: ru.Billing.pay, exact: true }).click();
  const refresh = billing.getByRole("button", { name: ru.Billing.refresh });
  await expect(refresh).toBeEnabled();

  const paidAccess = Promise.withResolvers<void>();
  await page.route("**/api/paid-access", async (route) => {
    await paidAccess.promise;
    return route.fulfill({
      status: 401, json: { detail: { code: "billing_session_required", request_id: "expired-cabinet" } }
    });
  });
  await page.route("**/api/auth/session", (route) => route.fulfill({ status: 401, json: { detail: "invalid_session" } }));
  const refusal = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/paid-access" && response.status() === 401);
  await page.getByRole("button", { name: ru.Account.products.paid.refresh }).click();
  await refresh.focus();
  await expect(refresh).toBeFocused();
  paidAccess.resolve();
  await refusal;
  await expect(billing.getByRole("alert")).toContainText(ru.Billing.errors.session);
  await expect(billing.getByRole("alert")).toContainText("expired-cabinet");
  await expect(billing.locator("iframe")).toHaveCount(0);
  await expect(billing.getByRole("button", { name: ru.Billing.open })).toBeDisabled();
  const retry = billing.getByRole("button", { name: ru.Purchase.retry });
  await expect(retry).toBeFocused();
  await retry.press("Enter");
  await expect(page.getByRole("heading", { name: ru.Auth.dialogTitle })).toBeVisible();
  expect(state.bootstraps).toEqual([{ purchase_intent_id: savedPurchase.purchase_intent_id }]);
});
