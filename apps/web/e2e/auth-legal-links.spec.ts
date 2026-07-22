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

test("checkout registration asks to repeat password and opens legal docs in new tabs", async ({ page }) => {
  let authRequests = 0;
  page.on("request", (request) => {
    if (/\/api\/auth\/(login|register)$/.test(new URL(request.url()).pathname)) {
      authRequests += 1;
    }
  });

  await page.goto("/ru/auth-checkout?product=document-summary");

  const dialog = page.getByRole("dialog", { name: "Вход или регистрация" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("Повторите пароль")).toBeVisible();
  await expectLegalLinksOpenInNewTab(dialog, [
    ...legalPaths,
    "/ru/cancellation"
  ]);

  await dialog.getByLabel("Email").fill("audit-user@example.com");
  await dialog.getByLabel("Пароль", { exact: true }).fill("synthetic-password-123");
  await dialog.getByLabel("Повторите пароль").fill("synthetic-password-456");
  await dialog.getByRole("button", { name: /Создать аккаунт/ }).click();

  await expect(dialog.getByText("Пароли не совпадают.")).toBeVisible();
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

test("checkout registration validation rejects invalid inputs before submitting", async ({ page }) => {
  let authRequests = 0;
  page.on("request", (request) => {
    if (/\/api\/auth\/(login|register)$/.test(new URL(request.url()).pathname)) {
      authRequests += 1;
    }
  });

  await page.goto("/ru/auth-checkout?product=document-summary");

  const dialog = page.getByRole("dialog", { name: "Вход или регистрация" });
  await expect(dialog).toBeVisible();

  await dialog.getByLabel("Email").fill("audit-user");
  await dialog.getByRole("button", { name: /Создать аккаунт/ }).click();
  await expect(dialog.getByText("Укажите корректный email.")).toBeVisible();
  expect(authRequests).toBe(0);

  await dialog.getByLabel("Email").fill("audit-user@example.com");
  await dialog.getByLabel("Пароль", { exact: true }).fill("synthetic-password-123");
  await dialog.getByLabel("Повторите пароль").fill("synthetic-password-123");
  await dialog.getByRole("button", { name: /Создать аккаунт/ }).click();
  await expect(
    dialog.getByText(
      "Для регистрации нужно отдельное согласие на обработку персональных данных."
    )
  ).toBeVisible();
  expect(authRequests).toBe(0);

  await dialog.getByLabel(/Я даю согласие/).check();
  await dialog.getByRole("button", { name: /Создать аккаунт/ }).click();
  await expect(
    dialog.getByText("Для регистрации нужно принять условия оферты.")
  ).toBeVisible();
  expect(authRequests).toBe(0);
});
