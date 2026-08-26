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
