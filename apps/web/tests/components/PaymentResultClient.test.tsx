import { HttpResponse, http } from "msw";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { setRouteSearchParams } from "../helpers/navigation";
import { server } from "../setup/msw-server";
import { PaymentResultClient } from "@/features/payment-result";

const apiBase = "http://localhost:8000";

function paymentStatusPayload(status: "pending" | "active" | "failed") {
  return {
    tenant_id: "anytoolai",
    region: "ru",
    user_id: "11111111-1111-4111-8111-111111111111",
    email: "buyer@example.com",
    product_state: {
      product_code: "document-summary",
      plan_code: "document-summary-pro",
      plan_name: "Document Summary Pro",
      invoice_id: "invoice-result",
      transaction_id: status === "pending" ? null : "tx-result",
      status,
      starts_at: null,
      expires_at: null
    },
    order:
      status === "pending"
        ? {
            order_id: "22222222-2222-4222-8222-222222222222",
            order_number: "RU-PENDING",
            status: "pending_payment",
            amount_minor: 99000,
            currency: "RUB",
            paid_at: null,
            failed_at: null
          }
        : {
            order_id: "22222222-2222-4222-8222-222222222222",
            order_number: "RU-FINAL",
            status: status === "active" ? "paid" : "payment_failed",
            amount_minor: 99000,
            currency: "RUB",
            paid_at: status === "active" ? "2026-07-30T10:00:00Z" : null,
            failed_at: status === "failed" ? "2026-07-30T10:00:00Z" : null
          },
    payment:
      status === "pending"
        ? null
        : {
            payment_id: "33333333-3333-4333-8333-333333333333",
            status: status === "active" ? "succeeded" : "failed",
            provider_payment_id: "tx-result",
            amount_minor: 99000,
            currency: "RUB",
            captured_at: status === "active" ? "2026-07-30T10:00:00Z" : null,
            failed_at: status === "failed" ? "2026-07-30T10:00:00Z" : null,
            refunded_amount_minor: 0
          }
  };
}

async function renderPollingResult(finalStatus: "active" | "failed") {
  let attempt = 0;
  const realSetInterval = window.setInterval.bind(window);
  vi.spyOn(window, "setInterval").mockImplementation(
    (handler: TimerHandler, _timeout?: number, ...args: unknown[]) =>
      realSetInterval(handler, 10, ...args) as unknown as ReturnType<
        typeof window.setInterval
      >
  );
  server.use(
    http.get(`${apiBase}/api/auth/payment-status`, () => {
      attempt += 1;
      return HttpResponse.json(
        paymentStatusPayload(attempt === 1 ? "pending" : finalStatus)
      );
    })
  );
  setRouteSearchParams(
    "status=pending&product=document-summary&email=buyer%40example.com&invoice=invoice-result"
  );
  render(<PaymentResultClient />);

  expect(await screen.findByRole("heading", { name: "Платёж обрабатывается" })).toBeVisible();
}

describe("PaymentResultClient authoritative status characterization", () => {
  it("keeps a spoofed success return URL pending without backend state", () => {
    setRouteSearchParams(
      "status=success&product=document-summary&email=buyer%40example.com"
    );

    render(<PaymentResultClient />);

    expect(
      screen.getByRole("heading", { name: "Платёж обрабатывается" })
    ).toBeVisible();
    expect(screen.getByText("Ожидаем подтверждение")).toBeVisible();
    expect(screen.queryByText("Оплата подтверждена")).not.toBeInTheDocument();
  });

  it("polls pending to paid from backend state", async () => {
    await renderPollingResult("active");

    expect(
      await screen.findByRole("heading", { name: "Оплата подтверждена" })
    ).toBeVisible();
    expect(
      screen.getByText(/Доступ по выбранному тарифу обновлён/)
    ).toBeVisible();
  });

  it("polls pending to failed from backend state", async () => {
    await renderPollingResult("failed");

    expect(
      await screen.findByRole("heading", { name: "Не удалось завершить оплату" })
    ).toBeVisible();
    expect(screen.getByText(/Платёж не был подтверждён/)).toBeVisible();
  });
});
