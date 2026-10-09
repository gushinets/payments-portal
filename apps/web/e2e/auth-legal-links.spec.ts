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

test("account registration asks to repeat password and opens legal docs in new tabs", async ({ page }) => {
  let authRequests = 0;
  page.on("request", (request) => {
    if (/\/api\/auth\/(login|register)$/.test(new URL(request.url()).pathname)) {
      authRequests += 1;
    }
  });

  await page.goto("/ru/account");

  const accountMain = page.getByRole("main");
  await accountMain.getByRole("button", { name: "Регистрация" }).click();
  await expect(accountMain.getByLabel("Повторите пароль")).toBeVisible();
  await expect(accountMain.locator("label span[lang=ru]")).toHaveCount(2);
  await expectLegalLinksOpenInNewTab(accountMain);

  await accountMain.getByLabel("Email").fill("audit-user@example.com");
  await accountMain.getByLabel("Пароль", { exact: true }).fill("Synthetic-password-123!");
  await accountMain.getByLabel("Повторите пароль").fill("Synthetic-password-456!");
  await accountMain.getByRole("button", { name: /Создать аккаунт/ }).click();

  await expect(accountMain.getByText("Пароли не совпадают.")).toBeVisible();
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

test("account registration validation rejects invalid inputs before submitting", async ({ page }) => {
  let authRequests = 0;
  page.on("request", (request) => {
    if (/\/api\/auth\/(login|register)$/.test(new URL(request.url()).pathname)) {
      authRequests += 1;
    }
  });

  await page.goto("/ru/account");

  const accountMain = page.getByRole("main");
  await accountMain.getByRole("button", { name: "Регистрация" }).click();

  await accountMain.getByLabel("Email").fill("audit-user");
  await accountMain.getByLabel("Email").press("Enter");
  await expect(accountMain.getByText("Укажите корректный email.")).toBeVisible();
  expect(authRequests).toBe(0);

  await accountMain.getByLabel("Email").fill("audit-user@example.com");
  await accountMain.getByLabel("Пароль", { exact: true }).fill("Synthetic-password-123!");
  await accountMain.getByLabel("Повторите пароль").fill("Synthetic-password-456!");
  await accountMain.getByLabel("Повторите пароль").press("Enter");
  await expect(accountMain.getByText("Пароли не совпадают.")).toBeVisible();
  expect(authRequests).toBe(0);

  await accountMain.getByLabel("Повторите пароль").fill("Synthetic-password-123!");
  await accountMain.getByLabel("Повторите пароль").press("Enter");
  await expect(
    accountMain.getByText("Нужно дать согласие на обработку персональных данных.")
  ).toBeVisible();
  expect(authRequests).toBe(0);

  await accountMain.getByLabel(/Я даю согласие/).check();
  await accountMain.getByLabel("Повторите пароль").press("Enter");
  await expect(accountMain.getByText("Нужно принять условия оферты.")).toBeVisible();
  expect(authRequests).toBe(0);
});
