import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import ru from "../src/messages/ru.json";
import { purchaseUser } from "../tests/fixtures/purchase";

// Synthetic Portal API responses only. The authorization page and browser are real.
// CI supplies the web-only synthetic callback through PLAYWRIGHT_BACKEND_CALLBACKS.
test("consumer authorization preserves Bundle 3 and refuses callback tampering", async ({ page }, testInfo) => {
  await page.addInitScript(() => localStorage.setItem("anytoolai_session_token_v1", "synthetic-primary-bearer"));
  let issued = 0;
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/session") return route.fulfill({ json: { authenticated: true, user: purchaseUser } });
    if (path === "/api/backend-session-codes") {
      issued += 1;
      expect(route.request().postDataJSON()).toEqual({ consumer_id: "synthetic-summary", code_challenge: "c".repeat(43), code_challenge_method: "S256" });
      return route.fulfill({ json: { code: "k".repeat(43), expires_at: "2099-01-01T00:00:00Z" } });
    }
    return route.fulfill({ status: 503, json: { detail: { code: "unexpected_synthetic_request" } } });
  });
  const query = new URLSearchParams({ consumer_id: "synthetic-summary", state: "s".repeat(43), code_challenge: "c".repeat(43), code_challenge_method: "S256" });
  await page.goto(`/ru/backend/authorize?${query}`);
  await expect(page.getByRole("heading", { name: ru.BackendSession.title })).toBeVisible();
  await page.getByRole("button", { name: ru.CookieBanner.acceptAction, exact: true }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations.filter(({ impact }) => impact === "critical" || impact === "serious")).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("backend-authorization.png"), fullPage: true });
  await page.goto(`/ru/backend/authorize?${query}&callback=https://evil.invalid`);
  await page.getByRole("button", { name: ru.BackendSession.continue, exact: true }).click();
  await expect(page.getByRole("region", { name: ru.BackendSession.title }).getByRole("alert")).toHaveText(ru.BackendSession.failed);
  expect(issued).toBe(0);
  await page.route("https://summary.invalid/**", (route) => route.fulfill({ contentType: "text/html", body: "<title>Synthetic callback</title>" }));
  await page.goto(`/ru/backend/authorize?${query}`);
  await page.getByRole("button", { name: ru.BackendSession.continue, exact: true }).click();
  await page.waitForURL("https://summary.invalid/callback#**");
  const callback = new URL(page.url());
  expect(callback.search).toBe("");
  expect(new URLSearchParams(callback.hash.slice(1)).get("code")).toBe("k".repeat(43));
  expect(new URLSearchParams(callback.hash.slice(1)).get("state")).toBe("s".repeat(43));
  expect(callback.href).not.toContain("synthetic-primary-bearer");
  expect(issued).toBe(1);
  expect(pageErrors).toEqual([]);
});
