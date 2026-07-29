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


test("password reset confirmation submits token and new password", async ({ page }) => {
  const requests: unknown[] = [];
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
  await page.getByLabel("Новый пароль").fill("new-password-123");
  await page.getByLabel("Повторите пароль").fill("new-password-123");
  await page.getByLabel("Повторите пароль").press("Enter");

  await expect(page.getByText("Пароль изменён. Теперь можно войти с новым паролем.")).toBeVisible();
  expect(requests).toEqual([
    { token: "test-only-reset-token", password: "new-password-123" }
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
