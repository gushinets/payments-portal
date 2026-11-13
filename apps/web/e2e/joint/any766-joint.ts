import fs from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, type TestInfo } from "@playwright/test";
import ru from "../../src/messages/ru.json";

export function jointEnvironment() {
  const identityPath = process.env.ANY766_JOINT_IDENTITY;
  const portal = process.env.PLAYWRIGHT_BASE_URL;
  const kernel = process.env.ANY766_KERNEL_WEB_ORIGIN;
  if (!identityPath || !portal || !kernel) throw new Error("Run these cases through tools/joint_paid_runtime/runtime.py --browser");
  const identity = JSON.parse(fs.readFileSync(identityPath, "utf8")) as { token: string; user_id: string };
  return { portal, kernel, identity };
}

export async function accessibility(page: Page, info: TestInfo, name: string) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.filter(({ impact }) => impact === "critical" || impact === "serious")).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath(`${name}.png`), fullPage: true });
}

export async function launch(page: Page, info: TestInfo, productId = "brief_decoder") {
  const { portal, kernel, identity } = jointEnvironment();
  await page.addInitScript(({ portal, token }) => {
    if (location.origin === portal) localStorage.setItem("anytoolai_session_token_v1", token);
  }, { portal, token: identity.token });
  await page.goto(`${portal}/ru/account`);
  const cookie = page.getByRole("button", { name: ru.CookieBanner.acceptAction, exact: true });
  if (await cookie.isVisible()) await cookie.click();
  const product = page.getByRole("article").filter({ has: page.getByRole("heading", { name: productId, exact: true }) });
  await expect(product.getByText(ru.Account.products.paid.confirmed, { exact: true })).toBeVisible();
  await accessibility(page, info, "paid-cabinet");
  const open = product.getByRole("link", { name: ru.Account.products.paid.openProduct, exact: true });
  expect(new URL((await open.getAttribute("href"))!).origin).toBe(kernel);
  await open.click();
  await page.waitForURL(`${portal}/ru/backend/authorize?**`);
  await expect(page.getByRole("heading", { name: ru.BackendSession.title })).toBeVisible();
  await accessibility(page, info, "backend-authorization");
  await page.getByRole("button", { name: ru.BackendSession.continue, exact: true }).click();
  const ready = await Promise.race([
    page.waitForURL(`${kernel}/products/${productId}`, { timeout: 60_000 }).then(() => true),
    page.getByRole("alert").filter({ hasText: "Could not authorize this tab" }).waitFor().then(() => false),
  ]);
  if (!ready) {
    const diagnostic = await page.evaluate(() => ({
      hasCustody: sessionStorage.getItem("anytoolai.portal_mode.v1") !== null,
      hasAuthorization: sessionStorage.getItem("anytoolai.portal_authorization.v1") !== null,
      hasSession: sessionStorage.getItem("anytoolai.portal_session.v1") !== null,
    }));
    throw new Error(`Kernel callback refused: ${JSON.stringify(diagnostic)}`);
  }
  expect(new URL(page.url()).hash).toBe("");
  expect(await page.evaluate(() => localStorage.getItem("anytoolai_session_token_v1"))).toBeNull();
  const session = await page.evaluate(() => JSON.parse(sessionStorage.getItem("anytoolai.portal_session.v1") ?? "null") as { version: number; consumerId: string; owner: { userId: string } });
  expect(session).not.toBeNull();
  expect(session.consumerId).toBe(process.env.ANYTOOLAI_PORTAL_CONSUMER_ID ?? "platform-kernel");
  expect(session.owner.userId).toBe(identity.user_id);
  return { portal, kernel, identity };
}
