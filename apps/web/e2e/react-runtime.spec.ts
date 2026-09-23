import { expect, test, type Page, type TestInfo } from "@playwright/test";

const sessionTokenStorageKey = "anytoolai_session_token_v1";
const email = "react-runtime@example.com";

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

test("retained auth and neutral commerce pages render without runtime warnings", async ({
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
          email
        }
      })
    });
  });
  await page.addInitScript((storageKey) => {
    window.localStorage.setItem(storageKey, "react-runtime-session");
  }, sessionTokenStorageKey);

  await page.goto("/ru");
  await expect(page.getByText("Каталог тарифов и оформление покупок временно недоступны.")).toBeVisible();
  await captureVisualEvidence(page, testInfo, "landing");

  await page.goto("/ru/auth-checkout");
  await expect(page.getByText(email)).toBeVisible();
  await expect(page.getByText("Оплата временно недоступна")).toBeVisible();
  await captureVisualEvidence(page, testInfo, "auth-shell");

  await page.goto("/ru/account");
  await expect(page.getByRole("heading", { name: "Личный кабинет" })).toBeVisible();
  await expect(page.getByText(email)).toBeVisible();
  await expect(page.getByText("Биллинг обновляется")).toBeVisible();
  await captureVisualEvidence(page, testInfo, "account");

  await page.goto("/ru/payment-result");
  await expect(
    page.getByRole("heading", { name: "Здесь пока нет результата платежа" })
  ).toBeVisible();
  await captureVisualEvidence(page, testInfo, "payment-result");

  expect(runtimeIssues).toEqual([]);
});
