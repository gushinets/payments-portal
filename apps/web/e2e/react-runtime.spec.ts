import { expect, test } from "@playwright/test";

const sessionTokenStorageKey = "anytoolai_session_token_v1";
const sessionChangedEvent = "anytoolai_session_changed";

const email = "react-runtime@example.com";
const invoice = "react-runtime-invoice";

function paymentStatusResponse(status: "pending" | "active") {
  const active = status === "active";

  return {
    tenant_id: "anytoolai",
    region: "ru",
    user_id: "11111111-1111-4111-8111-111111111111",
    email,
    product_state: {
      product_code: "document-summary",
      plan_code: "document-summary-pro",
      plan_name: "Document Summary Pro",
      invoice_id: invoice,
      transaction_id: active ? "tx-react-runtime" : null,
      status,
      starts_at: active ? "2026-08-19T10:00:00Z" : null,
      expires_at: active ? "2026-09-19T10:00:00Z" : null
    },
    order: {
      order_id: "22222222-2222-4222-8222-222222222222",
      order_number: "RU-REACT-RUNTIME",
      status: active ? "paid" : "pending_payment",
      amount_minor: 99000,
      currency: "RUB",
      paid_at: active ? "2026-08-19T10:00:00Z" : null,
      failed_at: null
    },
    payment: active
      ? {
          payment_id: "33333333-3333-4333-8333-333333333333",
          status: "succeeded",
          provider_payment_id: "tx-react-runtime",
          amount_minor: 99000,
          currency: "RUB",
          captured_at: "2026-08-19T10:00:00Z",
          failed_at: null,
          refunded_amount_minor: 0
        }
      : null
  };
}

test("critical client components run without React or hydration warnings", async ({
  page
}) => {
  const runtimeIssues: string[] = [];
  let paymentStatusRequests = 0;

  page.on("console", (message) => {
    if (message.type() === "warning" || message.type() === "error") {
      runtimeIssues.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => {
    runtimeIssues.push(`pageerror: ${error.message}`);
  });

  await page.route("**/api/auth/session**", async (route) => {
    const productCode = new URL(route.request().url()).searchParams.get("product");
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        authenticated: true,
        user: {
          tenant_id: "anytoolai",
          region: "ru",
          user_id: "11111111-1111-4111-8111-111111111111",
          email
        },
        product_state: productCode
          ? {
              product_code: productCode,
              plan_code: `${productCode}-pro`,
              plan_name: "React Runtime Plan",
              invoice_id: null,
              transaction_id: null,
              status: "inactive",
              starts_at: null,
              expires_at: null
            }
          : null
      })
    });
  });

  await page.route("**/api/catalog/products", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        products: [
          {
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
          }
        ]
      })
    });
  });

  await page.route("**/api/account/subscriptions", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ subscriptions: [] })
    });
  });

  await page.route("**/api/auth/payment-status?**", async (route) => {
    paymentStatusRequests += 1;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(
        paymentStatusResponse(
          paymentStatusRequests === 1 ? "pending" : "active"
        )
      )
    });
  });

  await page.goto("/ru");
  await expect(page.getByRole("button", { name: "Войти" })).toBeVisible();
  const purchaseLink = page.getByRole("link", { name: "Оформить", exact: true });
  await expect(purchaseLink).toBeVisible();
  let purchaseLinkReachedByKeyboard = false;
  for (let index = 0; index < 20; index += 1) {
    await page.keyboard.press("Tab");
    if (await purchaseLink.evaluate((element) => element === document.activeElement)) {
      purchaseLinkReachedByKeyboard = true;
      break;
    }
  }
  expect(purchaseLinkReachedByKeyboard).toBe(true);

  await page.evaluate(
    ({ eventName, storageKey, token }) => {
      window.localStorage.setItem(storageKey, token);
      window.dispatchEvent(new Event(eventName));
    },
    {
      eventName: sessionChangedEvent,
      storageKey: sessionTokenStorageKey,
      token: "react-runtime-session"
    }
  );
  await expect(page.getByText(email)).toBeVisible();

  await page.goto("/ru/auth-checkout?product=document-summary");
  await expect(page.locator("#checkout-form").getByText(email)).toBeVisible();

  await page.goto("/ru/account");
  const accountMain = page.getByRole("main");
  await expect(
    accountMain.getByRole("heading", { name: "Личный кабинет", exact: true })
  ).toBeVisible();
  await expect(accountMain.getByText(email)).toBeVisible();

  await page.evaluate(
    ({ paymentEmail, paymentInvoice }) => {
      window.sessionStorage.setItem(
        "anytoolai_last_payment_result",
        JSON.stringify({
          status: "pending",
          productCode: "document-summary",
          productName: "Document Summary",
          planName: "Document Summary Pro",
          amount: 990,
          currency: "RUB",
          email: paymentEmail,
          invoiceId: paymentInvoice
        })
      );
    },
    { paymentEmail: email, paymentInvoice: invoice }
  );
  await page.goto(
    "/ru/payment-result?status=pending&product=document-summary"
  );
  await expect(
    page.getByRole("heading", { name: "Платёж обрабатывается" })
  ).toBeVisible();
  await expect
    .poll(() => paymentStatusRequests, {
      message: "PaymentResultClient should issue its interval poll",
      timeout: 10_000
    })
    .toBe(2);
  await expect(
    page.getByRole("heading", { name: "Оплата подтверждена" })
  ).toBeVisible();
  expect(paymentStatusRequests).toBe(2);

  expect(runtimeIssues).toEqual([]);
});

test("dynamic catalog exposes semantic loading and error states", async ({ page }) => {
  await page.route("**/api/catalog/products", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 100));
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ products: [] })
    });
  });

  const loadingNavigation = page.goto("/ru");
  await expect(page.getByRole("status")).toHaveText("Загрузка каталога...");
  await loadingNavigation;
  await expect(page.getByRole("status")).toHaveText(
    "Сейчас в каталоге нет доступных продуктов."
  );

  await page.unroute("**/api/catalog/products");
  await page.route("**/api/catalog/products", async (route) => {
    await route.fulfill({ status: 503, body: "unavailable" });
  });
  await page.reload();
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: "Не удалось загрузить каталог" })
  ).toHaveText("Не удалось загрузить каталог. Обновите страницу и попробуйте ещё раз.");
});

test("authenticated catalog ownership suppresses the purchase CTA", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("anytoolai_session_token_v1", "owned-session");
  });
  await page.route("**/api/catalog/products", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        products: [
          {
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
          }
        ]
      })
    });
  });
  await page.route("**/api/account/subscriptions", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        subscriptions: [
          {
            subscription_id: "44444444-4444-4444-8444-444444444444",
            plan: {
              plan_id: "33333333-3333-4333-8333-333333333333",
              code: "document-summary-pro",
              name: "Document Summary Pro",
              billing_period: "month"
            },
            scope: {
              scope_type: "product",
              product_id: "11111111-1111-4111-8111-111111111111",
              bundle_id: null,
              included_product_ids: []
            },
            status: "active",
            renewal_mode: "manual",
            current_period: {
              starts_at: "2026-08-01T00:00:00Z",
              ends_at: "2026-10-01T00:00:00Z"
            },
            cancellation: {
              cancel_requested_at: null,
              canceled_at: null
            },
            entitlement_validity: {
              status: "active",
              valid_from: "2026-08-01T00:00:00Z",
              valid_until: "2026-10-01T00:00:00Z"
            }
          }
        ]
      })
    });
  });

  await page.goto("/ru");
  await expect(page.getByRole("heading", { name: "Document Summary" })).toBeVisible();
  await expect(page.getByText("Доступ уже активен")).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Оформить", exact: true })
  ).toHaveCount(0);
});
