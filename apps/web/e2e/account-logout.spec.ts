import { expect, request as playwrightRequest, test } from "@playwright/test";

const apiBaseURL = process.env.PLAYWRIGHT_API_BASE_URL ?? "http://127.0.0.1:8000";
const documentLoadCountKey = "anytoolai_test_document_load_count";
const sessionBootstrapKey = "anytoolai_test_session_bootstrapped";

test("account logout performs a full document navigation", async ({ page }, testInfo) => {
  const api = await playwrightRequest.newContext({ baseURL: apiBaseURL });
  try {
    const email = `logout-${Date.now()}-${testInfo.workerIndex}@example.com`;
    const registration = await api.post("/api/auth/register", {
      data: {
        email,
        password: "synthetic-password-123",
        personal_consent: true,
        offer_consent: true
      }
    });
    expect(registration.ok()).toBeTruthy();
    const { token } = (await registration.json()) as { token: string };

    await page.addInitScript((storageKey) => {
      const count = Number(window.sessionStorage.getItem(storageKey) ?? "0");
      window.sessionStorage.setItem(storageKey, String(count + 1));
    }, documentLoadCountKey);
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
    await expect(accountMain.locator(".account-summary-email")).toHaveText(email);
    const loadCountBeforeLogout = await page.evaluate(
      (storageKey) => Number(window.sessionStorage.getItem(storageKey)),
      documentLoadCountKey
    );

    await accountMain.getByRole("button", { name: /Выйти/ }).click();
    await expect(page).toHaveURL(/\/ru$/);
    await expect
      .poll(() =>
        page.evaluate(
          (storageKey) => Number(window.sessionStorage.getItem(storageKey)),
          documentLoadCountKey
        )
      )
      .toBe(loadCountBeforeLogout + 1);
  } finally {
    await api.dispose();
  }
});
