import { expect, test } from "@playwright/test";

const sessionTokenStorageKey = "anytoolai_session_token_v1";

test("auth shell exposes no legacy commerce or provider execution", async ({
  page
}) => {
  const requestedUrls: string[] = [];
  page.on("request", (request) => requestedUrls.push(request.url()));

  await page.route("**/api/auth/session", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        authenticated: true,
        user: {
          tenant_id: "anytoolai",
          region: "ru",
          user_id: "11111111-1111-4111-8111-111111111111",
          email: "auth-shell@example.com"
        }
      })
    });
  });
  await page.addInitScript((storageKey) => {
    window.localStorage.setItem(storageKey, "auth-shell-session");
  }, sessionTokenStorageKey);

  await page.goto("/ru/auth-checkout");

  await expect(page.getByText("auth-shell@example.com")).toBeVisible();
  await expect(page.getByText("Оплата временно недоступна")).toBeVisible();
  expect(
    requestedUrls.some((url) =>
      [
        "/api/catalog/products",
        "/api/auth/checkout-intent",
        "/api/account/subscriptions",
        "/api/auth/payment-status"
      ].some((path) => url.includes(path))
    )
  ).toBe(false);
  expect(
    requestedUrls.some((url) => url.startsWith("https://widget.cloudpayments.ru/"))
  ).toBe(false);
  await expect(page.locator('script[src*="widget.cloudpayments.ru"]')).toHaveCount(0);
});
