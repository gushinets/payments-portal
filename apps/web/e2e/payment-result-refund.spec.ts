import { expect, test } from "@playwright/test";

type RefundScenario = {
  name: string;
  queryStatus: string;
  orderStatus: "refunded" | "partially_refunded";
  paymentStatus: "refunded" | "partially_refunded";
  refundedAmountMinor: number;
  expectedTitle: string;
  expectedBadge: string;
  expectedCopy: string;
};

const scenarios: RefundScenario[] = [
  {
    name: "full refund beats spoofed success query",
    queryStatus: "success",
    orderStatus: "refunded",
    paymentStatus: "refunded",
    refundedAmountMinor: 99000,
    expectedTitle: "Платёж возвращён",
    expectedBadge: "Возврат выполнен",
    expectedCopy: "Платёж полностью возвращён"
  },
  {
    name: "partial refund has distinct final state",
    queryStatus: "pending",
    orderStatus: "partially_refunded",
    paymentStatus: "partially_refunded",
    refundedAmountMinor: 40000,
    expectedTitle: "Платёж частично возвращён",
    expectedBadge: "Частичный возврат",
    expectedCopy: "Сумма возврата: 400 ₽"
  }
];

for (const scenario of scenarios) {
  test(`/ru/payment-result shows ${scenario.name}`, async ({ page }, testInfo) => {
    const invoice = `invoice-${testInfo.workerIndex}-${Date.now()}`;
    const email = `refund-${testInfo.workerIndex}@example.com`;

    await page.route("**/payment-status?**", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          tenant_id: "anytoolai",
          region: "ru",
          user_id: "11111111-1111-4111-8111-111111111111",
          email,
          product_state: {
            product_code: "document-summary",
            plan_code: "document-summary-pro",
            plan_name: "Document Summary Pro",
            invoice_id: invoice,
            transaction_id: "tx-refund-e2e",
            status: "pending",
            starts_at: null,
            expires_at: null
          },
          order: {
            order_id: "22222222-2222-4222-8222-222222222222",
            order_number: "RU-REFUND-E2E",
            status: scenario.orderStatus,
            amount_minor: 99000,
            currency: "RUB",
            paid_at: "2026-07-11T09:00:00Z",
            failed_at: null
          },
          payment: {
            payment_id: "33333333-3333-4333-8333-333333333333",
            status: scenario.paymentStatus,
            provider_payment_id: "tx-refund-e2e",
            amount_minor: 99000,
            currency: "RUB",
            captured_at: "2026-07-11T09:00:00Z",
            failed_at: null,
            refunded_amount_minor: scenario.refundedAmountMinor
          }
        })
      });
    });

    await page.goto(
      `/ru/payment-result?status=${scenario.queryStatus}&product=document-summary&plan=document-summary-pro&email=${encodeURIComponent(email)}&invoice=${invoice}`
    );

    await expect(page.getByRole("heading", { name: scenario.expectedTitle })).toBeVisible();
    await expect(page.getByText(scenario.expectedBadge)).toBeVisible();
    await expect(page.getByText(scenario.expectedCopy)).toBeVisible();
    await expect(page.getByText("Ожидаем подтверждение")).toHaveCount(0);

    await testInfo.attach("payment-result-refund-evidence", {
      body: JSON.stringify(
        {
          scenario,
          invariant: "Refund UI is derived from mocked backend payment-status, not return URL status"
        },
        null,
        2
      ),
      contentType: "application/json"
    });
  });
}

test("/ru/payment-result formats stored checkout amount with its currency", async ({
  page
}) => {
  await page.goto("/ru");
  await page.evaluate(() => {
    window.sessionStorage.setItem(
      "anytoolai_last_payment_result",
      JSON.stringify({
        status: "pending",
        productCode: "document-summary",
        productName: "Document Summary",
        planName: "Document Summary Pro",
        amount: 12,
        currency: "USD",
        email: "currency@example.com",
        invoiceId: ""
      })
    );
  });

  await page.goto("/ru/payment-result?status=pending&product=document-summary");

  await expect(
    page.getByText(/Document Summary Pro · 12,00\s*\$ \/ месяц/)
  ).toBeVisible();
  await expect(page.getByText("990 ₽ / месяц")).toHaveCount(0);
});
