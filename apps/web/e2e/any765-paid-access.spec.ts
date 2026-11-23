import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import ru from "../src/messages/ru.json";
import { paidState } from "../tests/fixtures/paid-access";
import { purchaseUser, savedPurchase, widgetResponse } from "../tests/fixtures/purchase";

async function syntheticPaidCabinet(page: Page) {
  const state = {
    paid: paidState(), deadlinePending: false, reads: 0, usageReads: 0, sourceRequests: 0,
    bootstraps: [] as unknown[], widgetScripts: 0,
  };
  await page.addInitScript(() => localStorage.setItem("anytoolai_session_token_v1", "synthetic-paid-session"));
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/session") return route.fulfill({ json: { authenticated: true, user: purchaseUser } });
    if (path === "/api/purchase-intents") return route.fulfill({ json: {
      purchases: [savedPurchase, { ...savedPurchase, purchase_intent_id: "55555555-5555-4555-8555-555555555555", product_id: "brief_decoder" }].map((item) => ({ ...item, created_at: "2026-10-27T12:00:00Z" })), next_cursor: null
    } });
    if (path === "/api/paid-access") {
      state.reads += 1;
      return route.fulfill(state.deadlinePending
        ? { status: 503, json: { detail: { code: "paid_access_deadline_pending", request_id: "synthetic-browser-paid" } } }
        : { headers: { "Cache-Control": "no-store" }, json: state.paid });
    }
    if (path === "/api/paid-usage") {
      state.usageReads += 1;
      return route.fulfill({ status: 503, json: { detail: { code: "paid_usage_unavailable" } } });
    }
    if (path === "/api/billing/widget-bootstrap") {
      state.bootstraps.push(route.request().postDataJSON());
      return route.fulfill({ json: widgetResponse(true) });
    }
    state.sourceRequests += 1;
    return route.fulfill({ status: 503, json: { detail: { code: "synthetic_unexpected_source" } } });
  });
  return state;
}

const a = ru.Account.products.paid;
test("authenticated cabinet shows committed access independently per product with honest usage and accessible layout", async ({ page }, testInfo) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.name));
  const state = await syntheticPaidCabinet(page);
  state.paid.products.push({ product_id: "brief_decoder", status: "unavailable", observed_at: null, effective_until: null });
  await page.goto("/ru/account");
  await page.getByRole("button", { name: ru.CookieBanner.acceptAction, exact: true }).click();
  const products = page.getByRole("region", { name: ru.Account.products.title });
  const cards = products.getByRole("article");
  await expect(cards).toHaveCount(2);
  await expect(cards.filter({ hasText: "proposal_ai" }).getByText(a.confirmed)).toBeVisible();
  await expect(cards.filter({ hasText: "proposal_ai" }).getByText("Приобретённый лимит: 100 generation", { exact: true })).toBeVisible();
  await expect(cards.filter({ hasText: "brief_decoder" }).getByText(a.unavailable)).toBeVisible();
  await expect(page.getByText(a.usageUnavailable)).toHaveCount(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations.filter(({ impact }) => impact === "critical" || impact === "serious")).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("paid-cabinet.png"), fullPage: true });

  state.deadlinePending = true;
  await page.getByRole("button", { name: a.refresh }).click();
  await expect(products.getByRole("alert")).toContainText(a.deadlinePending);
  await expect(page.getByText(a.confirmed)).toHaveCount(0);
  state.deadlinePending = false;
  state.paid = paidState({ access_revision: 2, grants: [], allowances: [], products: [
    { product_id: "proposal_ai", status: "no_paid_access", observed_at: null, effective_until: null },
    { product_id: "brief_decoder", status: "unavailable", observed_at: null, effective_until: null }
  ], effective_until: null });
  await page.getByRole("button", { name: a.refresh }).click();
  await expect(cards.filter({ hasText: "proposal_ai" }).getByText(a.no_paid_access)).toBeVisible();
  await expect(cards.filter({ hasText: "brief_decoder" }).getByText(a.unavailable)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("paid-cabinet-empty.png"), fullPage: true });
  expect(state.reads).toBeGreaterThanOrEqual(3);
  expect(state.sourceRequests).toBe(0);
  expect(pageErrors).toEqual([]);
});

test("payment popup return refreshes visible cabinet before the next poll", async ({ page }, testInfo) => {
  const state = await syntheticPaidCabinet(page);
  await page.addInitScript(() => localStorage.setItem("anytoolai_cookie_notice_v1", "accepted"));
  await page.context().route("https://billing.test/checkout", (route) => route.fulfill({
    contentType: "text/html", body: '<button onclick="window.close()">Return to cabinet</button>',
  }));
  await page.route("https://billing.test/lbxwidget.js", (route) => {
    state.widgetScripts += 1;
    return route.fulfill({
      contentType: "application/javascript", body: `window.lbxwidget = () => ({ render(id) {
        const frame = document.createElement("iframe");
        frame.title = "Synthetic LBX";
        frame.src = "https://billing.test/widget/index.html";
        document.getElementById(id).replaceChildren(frame);
      } });`,
    });
  });
  await page.route("https://billing.test/widget/index.html", (route) => route.fulfill({
    contentType: "text/html", body: `<button onclick="window.open('https://billing.test/checkout', '_blank', 'popup,width=420,height=600')">Pay in separate window</button>
      <script>parent.postMessage({source:"lbx-widget", type:"READY"}, "*");</script>`,
  }));
  const start = new Date("2026-11-23T12:00:00Z");
  await page.clock.install({ time: start });
  state.paid = paidState({ access_revision: 0, grants: [], allowances: [], products: [
    { product_id: "proposal_ai", activation_check: "checking", status: "no_paid_access", observed_at: null, effective_until: null },
    { product_id: "brief_decoder", status: "unavailable", observed_at: null, effective_until: null },
  ], committed_at: null, effective_until: null });
  await page.goto("/ru/account");
  const cards = page.getByRole("region", { name: ru.Account.products.title }).getByRole("article");
  const proposal = cards.filter({ hasText: "proposal_ai" });
  const brief = cards.filter({ hasText: "brief_decoder" });
  await expect(proposal.getByRole("status").filter({ hasText: a.checking })).toBeVisible();
  await expect(brief.getByText(a.unavailable)).toBeVisible();
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations.filter(({ impact }) => impact === "critical" || impact === "serious")).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("paid-cabinet-checking.png"), fullPage: true });
  await page.evaluate(() => {
    // Playwright keeps its pages focused even with another Chromium window open.
    document.hasFocus = () => document.documentElement.dataset.cabinetFocused !== "false";
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState !== "visible") document.documentElement.dataset.cabinetHidden = "true";
    });
  });
  await proposal.getByRole("button", { name: ru.Purchase.manage }).click();
  const pay = page.frameLocator(`iframe[title="${ru.Billing.frameTitle}"]`)
    .frameLocator('iframe[title="Synthetic LBX"]').getByRole("button", { name: "Pay in separate window" });
  await expect(pay).toBeVisible();
  const freezeAt = new Date(await page.evaluate(() => Date.now()) + 1000);
  await page.clock.pauseAt(freezeAt);
  const [popup] = await Promise.all([
    page.waitForEvent("popup", { timeout: 5_000 }),
    pay.press("Enter"),
  ]);
  await page.evaluate(() => { document.documentElement.dataset.cabinetFocused = "false"; });
  await page.clock.runFor(250);
  expect(await page.evaluate(() => document.visibilityState)).toBe("visible");
  const { reads, usageReads } = state;
  state.paid.products[0].activation_check = "unconfirmed";
  await Promise.all([popup.waitForEvent("close"), popup.getByRole("button", { name: "Return to cabinet" }).click()]);
  await page.evaluate(() => { document.documentElement.dataset.cabinetFocused = "true"; });
  await page.clock.runFor(250);
  await expect(proposal.getByRole("status").filter({ hasText: a.unconfirmed })).toBeVisible();
  await expect(brief.getByText(a.unavailable)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.dataset.cabinetHidden)).toBeUndefined();
  expect(await page.evaluate(() => Date.now())).toBe(freezeAt.getTime() + 500);
  expect(state.reads).toBe(reads + 1);
  expect(state.usageReads).toBe(usageReads);
  await page.screenshot({ path: testInfo.outputPath("paid-cabinet-after-return.png"), fullPage: true });

  const committed = paidState();
  committed.products.push(state.paid.products[1]);
  state.paid = committed;
  await page.clock.fastForward(30_000);
  await expect(proposal.getByRole("status").filter({ hasText: a.confirmed })).toBeVisible();
  await expect(brief.getByText(a.unavailable)).toBeVisible();
  expect(state.reads).toBe(reads + 2);
  expect(state.bootstraps).toEqual([{ purchase_intent_id: savedPurchase.purchase_intent_id }]);
  expect(state.widgetScripts).toBe(1);
  expect(state.sourceRequests).toBe(0);
  await expect(pay).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("paid-cabinet-confirmed.png"), fullPage: true });
});
