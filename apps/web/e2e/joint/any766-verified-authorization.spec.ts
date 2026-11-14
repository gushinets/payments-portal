import fs from "node:fs";
import path from "node:path";
import { createHash, randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import ru from "../../src/messages/ru.json";
import { accessibility, jointEnvironment } from "./any766-joint";

test("email confirmation in another tab preserves authorization and its PKCE request", async ({ page, context, request }, info) => {
  test.setTimeout(150_000);
  const { portal, kernel } = jointEnvironment();
  const email = `browser-${randomUUID()}@example.com`;
  const registered = await request.post(`${process.env.PLAYWRIGHT_API_BASE_URL}/api/auth/register`, { headers: { "Accept-Language": "ru" }, data: {
    tenant_id: "anytoolai", region: "ru", email, password: "Synthetic-local-pass123!", personal_consent: true, offer_consent: true,
  } });
  expect(registered.status()).toBe(200);
  const identity = await registered.json() as { token: string; user: { user_id: string } };
  await context.addInitScript(({ portal, token }) => {
    if (location.origin === portal) localStorage.setItem("anytoolai_session_token_v1", token);
  }, { portal, token: identity.token });
  await page.goto(`${kernel}/portal-session/launch?return_to=${encodeURIComponent("/products/brief_decoder")}`);
  await page.waitForURL(`${portal}/ru/backend/authorize?**`);
  const originalRequest = page.url();
  await expect(page.getByRole("button", { name: ru.Account.authenticated.checkVerificationAction })).toBeVisible();
  await expect(page.getByRole("button", { name: ru.BackendSession.continue, exact: true })).toHaveCount(0);
  const cookie = page.getByRole("button", { name: ru.CookieBanner.acceptAction, exact: true });
  if (await cookie.isVisible()) await cookie.click();
  await accessibility(page, info, "email-verification-gate");
  const mailbox = path.join(path.dirname(process.env.ANY766_JOINT_IDENTITY!), `mail-${createHash("sha256").update(email).digest("hex")}.json`);
  await expect.poll(() => fs.existsSync(mailbox)).toBe(true);
  const { body } = JSON.parse(fs.readFileSync(mailbox, "utf8")) as { body: string };
  const link = /http:\/\/\S+/.exec(body)![0];
  const confirmation = await context.newPage();
  await confirmation.goto(link);
  await confirmation.getByRole("button", { name: ru.EmailVerification.verify.action, exact: true }).click();
  await expect(confirmation.getByText(ru.EmailVerification.verify.successTitle, { exact: true })).toBeVisible();
  await confirmation.close();
  const recheck = page.getByRole("button", { name: ru.Account.authenticated.checkVerificationAction });
  if (await recheck.isVisible()) await recheck.click();
  await expect(page.getByRole("button", { name: ru.BackendSession.continue, exact: true })).toBeVisible();
  expect(page.url()).toBe(originalRequest);
  await page.getByRole("button", { name: ru.BackendSession.continue, exact: true }).click();
  await page.waitForURL(`${kernel}/products/brief_decoder`);
  const authorized = await page.evaluate(() => JSON.parse(sessionStorage.getItem("anytoolai.portal_session.v1") ?? "null") as { owner: { userId: string } });
  expect(authorized.owner.userId).toBe(identity.user.user_id);
});
