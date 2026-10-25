import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import ru from "../src/messages/ru.json";

// Human opt-in, already-linked test account only. This never purchases or
// continues a purchase. Disable traces/video/screenshots that could retain JWTs.
test.use({ trace: "off", video: "off", screenshot: "off" });
test("official 043 Widget opens, closes, reopens and clears on cross-tab logout", async ({ page, context, request }) => {
  test.skip(process.env.LBX043_WIDGET_SMOKE !== "1", "Requires the authorized human Portal purchase walkthrough first");
  const token = process.env.LBX043_PORTAL_SESSION_TOKEN;
  const api = process.env.PLAYWRIGHT_API_BASE_URL;
  if (!token || !api) throw new Error("Missing local stand smoke configuration");
  const initial = await request.get(`${api}/api/billing/products/proposal_ai/status`, { headers: { Authorization: `Bearer ${token}` } });
  expect(initial.status()).toBe(200);
  const status: unknown = await initial.json();
  expect(status).toMatchObject({ state: "manage" });
  const sessionKey = "anytoolai_session_token_v1";
  await page.goto("/ru/products/proposal_ai");
  await page.evaluate(({ key, value }) => localStorage.setItem(key, value), { key: sessionKey, value: token });
  await page.reload();
  const journey = page.getByRole("region", { name: ru.Purchase.title });
  const manage = journey.getByRole("button", { name: ru.Purchase.manage });
  await expect(manage).toBeEnabled();
  await manage.click();
  const host = journey.locator("iframe");
  await expect(host).toHaveCount(1);
  // Assert actual vendor rendering, not merely our host frame's existence.
  await expect.poll(() => page.frames().filter(frame => frame.url().startsWith("https://043.lbxbilling.ru/")).length).toBeGreaterThan(0);
  await expect.poll(async () => {
    for (const frame of page.frames()) {
      if (!frame.url().startsWith("https://043.lbxbilling.ru/")) continue;
      if ((await frame.locator("body").innerText()).trim().length > 20) return true;
    }
    return false;
  }).toBe(true);
  const stored = await page.evaluate(() => JSON.stringify({ local: Object.entries(localStorage), session: Object.entries(sessionStorage), url: location.href }));
  expect(stored).not.toMatch(/eyJ[a-zA-Z0-9_-]+\./);
  // Portal accessibility; provider UI is separately observed by the operator.
  const a11y = await new AxeBuilder({ page }).include(".purchase-journey").disableRules(["frame-tested"]).analyze();
  expect(a11y.violations).toEqual([]);
  await journey.getByRole("button", { name: ru.Purchase.close }).click();
  await expect(host).toHaveCount(0);
  await expect(manage).toBeFocused();
  await manage.click();
  await expect(host).toHaveCount(1);
  const otherTab = await context.newPage();
  await otherTab.goto("/ru/products/proposal_ai");
  await otherTab.evaluate(key => localStorage.removeItem(key), sessionKey);
  await expect(host).toHaveCount(0);
  await expect(journey.getByRole("link", { name: ru.Purchase.signIn })).toBeVisible();
  await otherTab.close();
});
