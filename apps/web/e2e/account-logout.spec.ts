import { expect, request as playwrightRequest, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import ruMessages from "../src/messages/ru.json";

const apiBaseURL = process.env.PLAYWRIGHT_API_BASE_URL ?? "http://127.0.0.1:8000";
const sessionBootstrapKey = "anytoolai_test_session_bootstrapped";
const sessionStorageKey = "anytoolai_session_token_v1";

for (const failure of ["503", "network failure", "timeout"] as const) {
  test(`session ${failure} preserves the bearer and permits local sign-out without a revoke`, async ({ page }, testInfo) => {
    let logoutRequests = 0;
    let sessionRequests = 0;
    page.on("request", (request) => {
      if (new URL(request.url()).pathname === "/api/auth/logout") logoutRequests += 1;
    });
    await page.route("**/api/auth/session", async (route) => {
      sessionRequests += 1;
      if (failure === "503") {
        await route.fulfill({ status: 503, json: { detail: "unavailable" } });
      } else if (failure === "network failure") {
        await route.abort("failed");
      }
      // A paused timeout route settles only when the transport aborts it.
    });
    await page.addInitScript((key) => {
      window.localStorage.setItem(key, "failed-session");
      window.sessionStorage.setItem("local-sign-out-events", "0");
      window.addEventListener("anytoolai_session_changed", () => {
        const count = Number(window.sessionStorage.getItem("local-sign-out-events"));
        window.sessionStorage.setItem("local-sign-out-events", String(count + 1));
        window.sessionStorage.setItem("local-sign-out-event-token", window.localStorage.getItem(key) ?? "removed");
      });
    }, sessionStorageKey);
    await page.goto("/ru/account");
    const account = page.getByRole("main");
    await expect(account.getByRole("alert")).toHaveText(ruMessages.Account.sessionError.notice, { timeout: 10_000 });
    await expect(account.getByRole("button", { name: ruMessages.Account.sessionError.retryAction })).toBeVisible();
    const signOut = account.getByRole("button", { name: "Выйти на этом устройстве" });
    await expect(signOut).toBeVisible();
    expect(await page.evaluate((key) => localStorage.getItem(key), sessionStorageKey)).toBe("failed-session");
    expect(await page.evaluate(() => sessionStorage.getItem("local-sign-out-events"))).toBe("0");
    if (failure === "503") {
      const accessibility = await new AxeBuilder({ page }).include("main").analyze();
      expect(accessibility.violations.filter(({ impact }) => impact === "serious" || impact === "critical")).toEqual([]);
      await page.getByRole("button", { name: ruMessages.CookieBanner.acceptAction, exact: true }).click();
      await page.evaluate(async () => { await document.fonts.ready; });
      await page.screenshot({ path: testInfo.outputPath("account-session-error-local-sign-out.png"), fullPage: true });
      expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
    }
    await signOut.click();

    await expect(account.getByRole("heading", { name: ruMessages.Auth.dialogTitle })).toBeVisible();
    await expect(account.getByLabel("Email")).toBeVisible();
    await expect(page.getByRole("banner").getByRole("button", { name: "Войти", exact: true })).toBeEnabled();
    expect(await page.evaluate((key) => localStorage.getItem(key), sessionStorageKey)).toBeNull();
    expect(await page.evaluate(() => sessionStorage.getItem("local-sign-out-events"))).toBe("1");
    expect(await page.evaluate(() => sessionStorage.getItem("local-sign-out-event-token"))).toBe("removed");
    expect(logoutRequests).toBe(0);
    expect(sessionRequests).toBe(2);
  });
}

test("local sign-out from an older error reloads a replacement bearer", async ({ page }) => {
  const reads: string[] = [];
  let logoutRequests = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/auth/logout") logoutRequests += 1;
  });
  await page.route("**/api/auth/session", async (route) => {
    const bearer = route.request().headers().authorization;
    reads.push(bearer);
    if (bearer === "Bearer old-token") {
      await route.fulfill({ status: 503, json: { detail: "unavailable" } });
    } else {
      await route.fulfill({ json: {
        authenticated: true,
        user: {
          tenant_id: "anytoolai", region: "ru",
          user_id: "11111111-1111-4111-8111-111111111111",
          email: "replacement@example.com", email_verified: true
        }
      } });
    }
  });
  await page.addInitScript((key) => localStorage.setItem(key, "old-token"), sessionStorageKey);
  await page.goto("/ru/account");
  const account = page.getByRole("main");
  const signOut = account.getByRole("button", { name: "Выйти на этом устройстве" });
  await expect(signOut).toBeVisible();
  await page.evaluate((key) => localStorage.setItem(key, "new-token"), sessionStorageKey);
  await signOut.click();

  await expect(account.getByText("replacement@example.com", { exact: true })).toBeVisible();
  await expect(account.getByRole("heading", { name: ruMessages.Auth.dialogTitle })).toHaveCount(0);
  expect(await page.evaluate((key) => localStorage.getItem(key), sessionStorageKey)).toBe("new-token");
  expect(reads).toContain("Bearer new-token");
  expect(logoutRequests).toBe(0);
});

test("account logout revokes the session and returns to the signed-out account state", async ({ page }, testInfo) => {
  const api = await playwrightRequest.newContext({ baseURL: apiBaseURL });
  try {
    const email = `logout-${Date.now()}-${testInfo.workerIndex}@example.com`;
    const registration = await api.post("/api/auth/register", {
      data: {
        email,
        password: "Synthetic-password-123!",
        personal_consent: true,
        offer_consent: true
      }
    });
    expect(registration.ok()).toBeTruthy();
    const { token } = (await registration.json()) as { token: string };

    await page.addInitScript(
      ({ bootstrapKey, sessionToken }) => {
        if (window.sessionStorage.getItem(bootstrapKey) === "true") {
          return;
        }
        window.localStorage.setItem("anytoolai_session_token_v1", sessionToken);
        window.sessionStorage.setItem(bootstrapKey, "true");
      },
      { bootstrapKey: sessionBootstrapKey, sessionToken: token }
    );

    await page.goto("/ru/account");
    const accountMain = page.getByRole("main");
    await expect(accountMain.getByText(email, { exact: true })).toBeVisible();
    await expect(
      accountMain.getByRole("heading", { name: "Подтвердите email", exact: true })
    ).toBeVisible();
    const products = accountMain.getByRole("region", { name: "Продукты" });
    await expect(products.getByRole("link")).toHaveCount(2);
    await expect(products.getByRole("article")).toHaveCount(2);
    for (const product of [
      { name: "Document Summary", slug: "document-summary" },
      { name: "Prompt Optimizer", slug: "prompt-optimizer" }
    ]) {
      const card = products.getByRole("article", { name: product.name, exact: true });
      await expect(card).toBeVisible();
      await expect(card.getByRole("definition")).toHaveText([
        "Коммерческая информация по этому продукту пока не готова.",
        "Достоверный статус доступа к этому продукту пока неизвестен.",
        "Данные об использовании и квоте для этого продукта пока недоступны."
      ]);
      await expect(card.getByRole("link", {
        name: `Подробнее о продукте ${product.name}`,
        exact: true
      })).toHaveAttribute("href", `/ru/products/${product.slug}`);
    }

    await accountMain.getByRole("button", { name: /Выйти/ }).click();
    await expect(
      accountMain.getByRole("heading", { name: "Вход или регистрация" })
    ).toBeVisible();
    await expect(accountMain.getByLabel("Email")).toBeVisible();
    await expect(products).toHaveCount(0);
    await expect(accountMain.getByRole("article")).toHaveCount(0);
    await expect(
      accountMain.getByRole("button", { name: "Регистрация", exact: true })
    ).toBeVisible();
    await expect
      .poll(() =>
        page.evaluate(() =>
          window.localStorage.getItem("anytoolai_session_token_v1")
        )
      )
      .toBeNull();
  } finally {
    await api.dispose();
  }
});
