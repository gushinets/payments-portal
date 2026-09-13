import { expect, test } from "@playwright/test";

const sessionTokenStorageKey = "anytoolai_session_token_v1";

const checkoutProduct = {
  product_id: "11111111-1111-4111-8111-111111111111",
  code: "document-summary",
  name: "Document Summary",
  description: "Backend document summary description",
  plan: {
    plan_id: "33333333-3333-4333-8333-333333333333",
    code: "document-summary-pro",
    name: "Document Summary Pro",
    price_amount_minor: 99000,
    currency: "RUB",
    billing_period: "month",
    renewal_mode: "manual",
    trial_days: 7
  }
};

test("checkout is deliberately unavailable without provider runtime", async ({
  page
}) => {
  let checkoutIntentRequests = 0;
  const requestedUrls: string[] = [];

  page.on("request", (request) => {
    requestedUrls.push(request.url());
  });

  await page.route("**/api/auth/session**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        authenticated: true,
        user: {
          tenant_id: "anytoolai",
          region: "ru",
          user_id: "11111111-1111-4111-8111-111111111111",
          email: "checkout-unavailable@example.com"
        },
        product_state: {
          product_code: checkoutProduct.code,
          plan_code: checkoutProduct.plan.code,
          plan_name: checkoutProduct.plan.name,
          invoice_id: null,
          transaction_id: null,
          status: "inactive",
          starts_at: null,
          expires_at: null
        }
      })
    });
  });

  await page.route("**/api/catalog/products", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ products: [checkoutProduct] })
    });
  });

  await page.route("**/api/account/subscriptions", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ subscriptions: [] })
    });
  });

  await page.route("**/api/auth/checkout-intent", async (route) => {
    checkoutIntentRequests += 1;
    await route.fulfill({
      status: 500,
      contentType: "application/json",
      body: JSON.stringify({ detail: "checkout_intent_should_not_be_called" })
    });
  });

  await page.addInitScript((storageKey) => {
    window.localStorage.setItem(storageKey, "checkout-unavailable-session");
  }, sessionTokenStorageKey);

  await page.goto("/ru/auth-checkout?product=document-summary");
  await expect(
    page.locator("#checkout-form").getByText("checkout-unavailable@example.com")
  ).toBeVisible();
  await expect(
    page.getByText("Оплата временно недоступна. Попробуйте позже.")
  ).toBeVisible();

  const paymentButton = page.getByRole("button", {
    name: "Оплата недоступна",
    exact: true
  });
  await expect(paymentButton).toBeDisabled();
  await paymentButton.click({ force: true });

  expect(checkoutIntentRequests).toBe(0);
  expect(
    requestedUrls.some((url) =>
      url.startsWith("https://widget.cloudpayments.ru/")
    )
  ).toBe(false);
  await expect(
    page.locator('script[src*="widget.cloudpayments.ru"]')
  ).toHaveCount(0);
});
