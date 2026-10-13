import { expect, test } from "@playwright/test";

import ruMessages from "../src/messages/ru.json";

const sessionStorageKey = "anytoolai_session_token_v1";
const sessionUser = {
  tenant_id: "anytoolai",
  region: "ru",
  user_id: "11111111-1111-4111-8111-111111111111",
  email: "keyboard@example.com",
  email_verified: true
};

for (const entry of ["account", "header"] as const) {
  test(`${entry} login submits once with Enter and ignores repeated input while pending`, async ({ page }, testInfo) => {
    let loginRequests = 0;
    let finishLogin: () => void = () => undefined;
    const pendingLogin = new Promise<void>((resolve) => { finishLogin = resolve; });
    await page.route("**/api/auth/login", async (route) => {
      loginRequests += 1;
      expect(route.request().method()).toBe("POST");
      expect(route.request().postDataJSON()).toEqual({
        email: sessionUser.email,
        password: "Synthetic-password-123!"
      });
      await pendingLogin;
      await route.fulfill({
        json: { status: "authenticated", token: "keyboard-session", user: sessionUser }
      });
    });
    await page.route("**/api/auth/session", async (route) => {
      await route.fulfill({ json: { authenticated: true, user: sessionUser } });
    });

    try {
      await page.goto(entry === "account" ? "/ru/account" : "/ru");
      await page.getByRole("button", { name: ruMessages.CookieBanner.acceptAction, exact: true }).click();
      if (entry === "header") {
        await page.getByRole("banner").getByRole("button", { name: "Войти", exact: true }).click();
      }
      const scope = entry === "account"
        ? page.getByRole("main")
        : page.getByRole("dialog", { name: ruMessages.Auth.header.dialogAriaLabel });
      const email = scope.getByLabel("Email");
      const password = scope.getByLabel("Пароль", { exact: true });
      const submit = scope.getByRole("button", { name: "Войти", exact: true });
      await expect(scope.locator("form form")).toHaveCount(0);
      await expect(scope.locator("form")).toHaveCount(1);
      await email.fill(sessionUser.email);
      await email.press("Tab");
      await expect(password).toBeFocused();
      await password.press("Shift+Tab");
      await expect(email).toBeFocused();
      await password.fill("Synthetic-password-123!");
      await page.evaluate(async () => { await document.fonts.ready; });
      await page.screenshot({ path: testInfo.outputPath(`${entry}-native-auth-form.png`), fullPage: true });
      await password.press("Enter");
      await expect.poll(() => loginRequests).toBe(1);
      await expect(submit).toBeDisabled();
      await password.press("Enter");
      await password.press("Enter");
      await submit.evaluate((element) => {
        if (element instanceof HTMLButtonElement) element.click();
      });
      expect(loginRequests).toBe(1);
      finishLogin();

      if (entry === "account") {
        await expect(page.getByRole("main").getByText(sessionUser.email, { exact: true })).toBeVisible();
      } else {
        await expect(page.getByRole("dialog")).toHaveCount(0);
        await expect(page.getByRole("banner").getByText(sessionUser.email, { exact: true })).toBeVisible();
      }
      await expect.poll(() => page.evaluate((key) => localStorage.getItem(key), sessionStorageKey)).toBe("keyboard-session");
      expect(loginRequests).toBe(1);
    } finally {
      finishLogin();
    }
  });
}
