import { expect, test, type Page, type TestInfo } from "@playwright/test";

import ruMessages from "../src/messages/ru.json";

const sessionTokenStorageKey = "anytoolai_session_token_v1";
const email = "react-runtime@example.com";

test("account and header native auth forms render without runtime warnings", async ({ page }) => {
  const runtimeIssues: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "warning" || message.type() === "error") {
      runtimeIssues.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => runtimeIssues.push(`pageerror: ${error.message}`));
  const user = {
    tenant_id: "anytoolai", region: "ru",
    user_id: "11111111-1111-4111-8111-111111111111",
    email, email_verified: false
  };
  await page.route("**/api/auth/login", async (route) => {
    await route.fulfill({ json: { status: "authenticated", token: "runtime-session", user } });
  });
  await page.route("**/api/auth/session", async (route) => {
    await route.fulfill({ json: { authenticated: true, user } });
  });
  await page.goto("/ru/account");
  const account = page.getByRole("main");
  await expect(account.locator("form")).toHaveCount(1);
  await expect(page.locator("form form")).toHaveCount(0);
  await account.getByLabel("Email").fill(email);
  await account.getByLabel("Пароль", { exact: true }).fill("Synthetic-password-123!");
  await account.getByLabel("Пароль", { exact: true }).press("Enter");
  await expect(account.getByRole("heading", { name: ruMessages.EmailVerification.pending.title })).toBeVisible();
  await expect(account.locator("form")).toHaveCount(0);

  await page.evaluate((key) => {
    localStorage.removeItem(key);
    window.dispatchEvent(new Event("anytoolai_session_changed"));
  }, sessionTokenStorageKey);
  await page.getByRole("banner").getByRole("button", { name: "Войти", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.locator("form")).toHaveCount(1);
  await expect(page.locator("form form")).toHaveCount(0);
  await dialog.getByLabel("Email").fill(email);
  await dialog.getByLabel("Пароль", { exact: true }).fill("Synthetic-password-123!");
  await dialog.getByLabel("Пароль", { exact: true }).press("Enter");
  await expect(dialog.getByRole("heading", { name: ruMessages.EmailVerification.pending.title })).toBeVisible();
  await expect(dialog.locator("form")).toHaveCount(0);
  expect(runtimeIssues).toEqual([]);
});

async function captureVisualEvidence(
  page: Page,
  testInfo: TestInfo,
  name: string
) {
  await page.locator("nextjs-portal").evaluateAll((portals) => {
    for (const portal of portals) {
      portal.remove();
    }
  });
  await page.screenshot({
    animations: "disabled",
    caret: "hide",
    fullPage: true,
    path: testInfo.outputPath(`${name}.png`),
    scale: "css"
  });
}

test("public portal and account cabinet render without runtime warnings", async ({
  page
}, testInfo) => {
  const runtimeIssues: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "warning" || message.type() === "error") {
      runtimeIssues.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => {
    runtimeIssues.push(`pageerror: ${error.message}`);
  });

  await page.route("**/api/auth/session", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        authenticated: true,
        user: {
          tenant_id: "anytoolai",
          region: "ru",
          user_id: "11111111-1111-4111-8111-111111111111",
          email,
          email_verified: true
        }
      })
    });
  });
  await page.addInitScript((storageKey) => {
    window.localStorage.setItem(storageKey, "react-runtime-session");
  }, sessionTokenStorageKey);

  await page.goto("/ru");
  await expect(
    page.getByRole("heading", {
      name: "AI-инструменты для повседневной работы",
      exact: true
    })
  ).toBeVisible();
  await captureVisualEvidence(page, testInfo, "landing");

  await page.goto("/ru/account");
  await expect(
    page.getByRole("heading", { name: "Личный кабинет" })
  ).toBeVisible();
  await expect(
    page.getByRole("main").getByText(email, { exact: true })
  ).toBeVisible();
  const products = page.getByRole("main").getByRole("region", { name: ruMessages.Account.products.title });
  await expect(products.getByRole("article")).toHaveCount(2);
  for (const product of [
    ruMessages.Catalog.products.documentSummary,
    ruMessages.Catalog.products.promptOptimizer
  ]) {
    const card = products.getByRole("article", { name: product.name, exact: true });
    await expect(card).toBeVisible();
    await expect(card.getByRole("definition")).toHaveText([
      ruMessages.Account.products.state.commercial.description,
      ruMessages.Account.products.state.access.description,
      ruMessages.Account.products.state.usage.description
    ]);
  }
  await captureVisualEvidence(page, testInfo, "account");

  expect(runtimeIssues).toEqual([]);
});
