import { expect, test } from "@playwright/test";

const sessionBootstrapKey = "anytoolai_test_session_bootstrapped";

test("account logout revokes the session and returns to the signed-out account state", async ({ page }) => {
  const email = "logout-user@example.com";
  let logoutRequests = 0;
  await page.route("**/api/auth/session", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        authenticated: true,
        user: {
          tenant_id: "anytoolai",
          region: "ru",
          user_id: "00000000-0000-0000-0000-000000000001",
          email
        }
      })
    });
  });
  await page.route("**/api/auth/logout", async (route) => {
    logoutRequests += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "logged_out" })
    });
  });

  await page.addInitScript(
    ({ bootstrapKey, sessionToken }) => {
      if (window.sessionStorage.getItem(bootstrapKey) === "true") {
        return;
      }
      window.localStorage.setItem("anytoolai_session_token_v1", sessionToken);
      window.sessionStorage.setItem(bootstrapKey, "true");
    },
    { bootstrapKey: sessionBootstrapKey, sessionToken: "test-session-token" }
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
  expect(logoutRequests).toBe(1);
});
