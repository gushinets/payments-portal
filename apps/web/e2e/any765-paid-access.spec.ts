import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import ru from "../src/messages/ru.json";
import { paidState } from "../tests/fixtures/paid-access";
import { purchaseUser, savedPurchase } from "../tests/fixtures/purchase";

async function syntheticPaidCabinet(page: Page) {
  const state = { paid: paidState(), deadlinePending: false, reads: 0, sourceRequests: 0 };
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
