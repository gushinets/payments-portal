import { expect, test } from "@playwright/test";


test("password reset request submits email and shows generic success", async ({ page }) => {
  const requests: unknown[] = [];
  await page.route("**/api/auth/password-reset/request", async (route) => {
    requests.push(route.request().postDataJSON());
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "accepted" })
    });
  });

  await page.goto("/ru/forgot-password");
  await page.getByLabel("Email").fill("reset-user@example.com");
  await page.getByLabel("Email").press("Enter");

  await expect(
    page.getByText("Если аккаунт с таким email существует, мы отправили ссылку для смены пароля.")
  ).toBeVisible();
  expect(requests).toEqual([{ email: "reset-user@example.com" }]);
});

for (const { routeLocale, languageTag } of [
  { routeLocale: "de", languageTag: "de" },
  { routeLocale: "pt", languageTag: "pt-BR" }
]) {
  test(`${routeLocale} password reset request sends canonical language metadata`, async ({
    page
  }) => {
    const requests: Array<{ body: unknown; languageTag: string | null }> = [];
    await page.route("**/api/auth/password-reset/request", async (route) => {
      requests.push({
        body: route.request().postDataJSON(),
        languageTag: await route.request().headerValue("accept-language")
      });
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ status: "accepted" })
      });
    });

    await page.goto(`/${routeLocale}/forgot-password`);
    await page.locator('input[type="email"]').fill("reset-user@example.com");
    await page.locator('input[type="email"]').press("Enter");

    await expect(page.locator('[aria-live="polite"] .notice')).toBeVisible();
    expect(requests).toEqual([
      {
        body: { email: "reset-user@example.com" },
        languageTag
      }
    ]);
  });
}


test("password reset confirmation submits token and new password", async ({ page }) => {
  const requests: unknown[] = [];
  const documentRequests: string[] = [];
  page.on("request", (request) => {
    if (request.resourceType() === "document") {
      documentRequests.push(request.url());
    }
  });
  await page.route("**/api/auth/password-reset/confirm", async (route) => {
    requests.push(route.request().postDataJSON());
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "password_reset" })
    });
  });

  await page.goto("/ru/reset-password#token=test-only-reset-token");
  await expect(page).toHaveURL(/\/ru\/reset-password$/);
  expect(documentRequests).toHaveLength(1);
  expect(documentRequests[0]).not.toContain("test-only-reset-token");
  await expect(page.locator(".locale-switcher")).toHaveCount(0);
  await page.getByLabel("Новый пароль").fill("New-password-123!");
  await page.getByLabel("Повторите пароль").fill("New-password-123!");
  await page.getByLabel("Повторите пароль").press("Enter");

  await expect(page.getByText("Пароль изменён. Теперь можно войти с новым паролем.")).toBeVisible();
  expect(requests).toEqual([
    { token: "test-only-reset-token", password: "New-password-123!" }
  ]);
});

test("password reset confirmation relies on backend new-password policy", async ({ page }) => {
  const requests: unknown[] = [];
  await page.route("**/api/auth/password-reset/confirm", async (route) => {
    const payload = route.request().postDataJSON();
    requests.push(payload);
    if (payload.password === "Aa1!aaaaaaa") {
      await route.fulfill({
        status: 400,
        contentType: "application/json",
        body: JSON.stringify({ detail: { code: "password_policy_not_met" } })
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "password_reset" })
    });
  });

  await page.goto("/ru/reset-password#token=shared-policy-token");
  await page.getByLabel("Новый пароль").fill("Aa1!aaaaaaa");
  await page.getByLabel("Повторите пароль").fill("Aa1!aaaaaaa");
  await page.getByRole("button", { name: "Сменить пароль" }).click();

  await expect(
    page.getByText("Пароль не соответствует всем требованиям.")
  ).toBeVisible();
  expect(requests).toEqual([
    { token: "shared-policy-token", password: "Aa1!aaaaaaa" }
  ]);

  await page.getByLabel("Новый пароль").fill("Valid-reset-123!");
  await page.getByLabel("Повторите пароль").fill("Valid-reset-123!");
  await page.getByRole("button", { name: "Сменить пароль" }).click();

  await expect(
    page.getByText("Пароль изменён. Теперь можно войти с новым паролем.")
  ).toBeVisible();
  expect(requests).toEqual([
    { token: "shared-policy-token", password: "Aa1!aaaaaaa" },
    { token: "shared-policy-token", password: "Valid-reset-123!" }
  ]);
});


test("header forgot-password link closes the login dialog", async ({ page }) => {
  await page.goto("/ru");
  await page.getByRole("button", { name: /Войти/ }).click();

  const dialog = page.getByRole("dialog", { name: "Вход в аккаунт" });
  await expect(dialog).toBeVisible();

  await dialog.getByRole("link", { name: "Забыли пароль?" }).click();

  await expect(page).toHaveURL(/\/ru\/forgot-password$/);
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("heading", { name: "Сброс пароля" })).toBeVisible();
});
