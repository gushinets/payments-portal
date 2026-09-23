import { expect, request as playwrightRequest, test } from "@playwright/test";

const apiBaseURL = process.env.PLAYWRIGHT_API_BASE_URL ?? "http://127.0.0.1:8000";
const sessionBootstrapKey = "anytoolai_test_session_bootstrapped";

test("account logout revokes the session and returns to the signed-out account state", async ({ page }, testInfo) => {
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

    await accountMain.getByRole("button", { name: /Выйти/ }).click();
    await expect(
      accountMain.getByRole("link", { name: "Войти или зарегистрироваться" })
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
