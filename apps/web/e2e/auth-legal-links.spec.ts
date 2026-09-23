import { expect, test, type Locator } from "@playwright/test";

const legalPaths = [
  "/ru/consent-personal-data",
  "/ru/privacy",
  "/ru/offer"
];

async function expectLegalLinksOpenInNewTab(
  scope: Locator,
  paths = legalPaths
) {
  for (const path of paths) {
    const link = scope.locator(`a[href="${path}"]`).first();
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", /noopener/);
    await expect(link).toHaveAttribute("rel", /noreferrer/);
  }
}

test("auth-shell registration asks to repeat password and opens legal docs in new tabs", async ({ page }) => {
  let authRequests = 0;
  page.on("request", (request) => {
    if (/\/api\/auth\/(login|register)$/.test(new URL(request.url()).pathname)) {
      authRequests += 1;
    }
  });

  await page.goto("/ru/auth-checkout");

  const authShell = page.getByRole("main");
  await authShell.getByRole("button", { name: "Регистрация" }).click();
  await expect(authShell.getByLabel("Повторите пароль")).toBeVisible();
  await expectLegalLinksOpenInNewTab(authShell);

  await authShell.getByLabel("Email").fill("audit-user@example.com");
  await authShell.getByLabel("Пароль", { exact: true }).fill("synthetic-password-123");
  await authShell.getByLabel("Повторите пароль").fill("synthetic-password-456");
  await authShell.getByRole("button", { name: /Создать аккаунт/ }).click();

  await expect(authShell.getByText("Пароли не совпадают.")).toBeVisible();
  expect(authRequests).toBe(0);
});

test("header registration legal docs open in new tabs", async ({ page }) => {
  await page.goto("/ru");
  await page.getByRole("button", { name: /Войти/ }).click();

  const dialog = page.getByRole("dialog", { name: "Вход в аккаунт" });
  await dialog.getByRole("button", { name: "Регистрация" }).click();

  await expect(dialog.getByLabel("Повторите пароль")).toBeVisible();
  await expectLegalLinksOpenInNewTab(dialog);
});

test("auth-shell registration validation rejects invalid inputs before submitting", async ({ page }) => {
  let authRequests = 0;
  page.on("request", (request) => {
    if (/\/api\/auth\/(login|register)$/.test(new URL(request.url()).pathname)) {
      authRequests += 1;
    }
  });

  await page.goto("/ru/auth-checkout");

  const authShell = page.getByRole("main");
  await authShell.getByRole("button", { name: "Регистрация" }).click();

  await authShell.getByLabel("Email").fill("audit-user");
  await authShell.getByRole("button", { name: /Создать аккаунт/ }).click();
  await expect(authShell.getByText("Укажите корректный email.")).toBeVisible();
  expect(authRequests).toBe(0);

  await authShell.getByLabel("Email").fill("audit-user@example.com");
  await authShell.getByLabel("Пароль", { exact: true }).fill("synthetic-password-123");
  await authShell.getByLabel("Повторите пароль").fill("synthetic-password-123");
  await authShell.getByRole("button", { name: /Создать аккаунт/ }).click();
  await expect(
    authShell.getByText("Нужно дать согласие на обработку персональных данных.")
  ).toBeVisible();
  expect(authRequests).toBe(0);

  await authShell.getByLabel(/Я даю согласие/).check();
  await authShell.getByRole("button", { name: /Создать аккаунт/ }).click();
  await expect(authShell.getByText("Нужно принять условия оферты.")).toBeVisible();
  expect(authRequests).toBe(0);
});
