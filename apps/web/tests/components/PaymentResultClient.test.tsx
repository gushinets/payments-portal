import { HttpResponse, http } from "msw";
import { render, screen, waitFor } from "@testing-library/react";
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

function canceledPaymentStatusPayload() {
  return {
    ...paymentStatusPayload("pending"),
    order: {
      order_id: "22222222-2222-4222-8222-222222222222",
      order_number: "RU-CANCELED",
      status: "canceled",
      amount_minor: 99000,
      currency: "RUB",
      paid_at: null,
      failed_at: null
    },
    payment: {
      payment_id: "33333333-3333-4333-8333-333333333333",
      status: "canceled",
      provider_payment_id: "tx-canceled",
      amount_minor: 99000,
      currency: "RUB",
      captured_at: null,
      failed_at: null,
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

  it.each(["active", "paid", "refunded", "partially_refunded"])(
    "keeps a spoofed %s return URL pending without backend state",
    (spoofedStatus) => {
      setRouteSearchParams(
        `status=${spoofedStatus}&product=document-summary&email=buyer%40example.com`
      );

      render(<PaymentResultClient />);

      expect(
        screen.getByRole("heading", { name: "Платёж обрабатывается" })
      ).toBeVisible();
      expect(screen.getByText("Ожидаем подтверждение")).toBeVisible();
      expect(screen.queryByText("Оплата подтверждена")).not.toBeInTheDocument();
      expect(screen.queryByText("Платёж подтверждён")).not.toBeInTheDocument();
      expect(screen.queryByText("Платёж возвращён")).not.toBeInTheDocument();
      expect(screen.queryByText("Платёж частично возвращён")).not.toBeInTheDocument();
    }
  );

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

  it("shows canceled backend state instead of polling forever", async () => {
    server.use(
      http.get(`${apiBase}/api/auth/payment-status`, () =>
        HttpResponse.json(canceledPaymentStatusPayload())
      )
    );
    setRouteSearchParams(
      "status=pending&product=document-summary&email=buyer%40example.com&invoice=invoice-result"
    );

    render(<PaymentResultClient />);

    expect(
      await screen.findByRole("heading", { name: "Платёж отменён" })
    ).toBeVisible();
    expect(screen.getByText(/Списание не подтверждено/)).toBeVisible();
    expect(screen.queryByText("Ожидаем подтверждение")).not.toBeInTheDocument();
  });

  it("shows canceled URL fallback when backend payload is unavailable", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    setRouteSearchParams("status=canceled&product=document-summary");

    try {
      render(<PaymentResultClient />);

      expect(
        screen.getByRole("heading", { name: "Платёж отменён" })
      ).toBeVisible();
      expect(screen.getByText(/Списание не подтверждено/)).toBeVisible();
      expect(screen.queryByText("Ожидаем подтверждение")).not.toBeInTheDocument();
      expect(fetchSpy).not.toHaveBeenCalled();
    } finally {
      fetchSpy.mockRestore();
    }
  });

  it("keeps pending state when payment-status polling aborts", async () => {
    const originalFetch = globalThis.fetch.bind(globalThis);
    const unhandledRejections: unknown[] = [];
    const abortError = new DOMException("The operation was aborted.", "AbortError");
    const onUnhandledRejection = (event: PromiseRejectionEvent) => {
      unhandledRejections.push(event.reason);
    };

    window.addEventListener("unhandledrejection", onUnhandledRejection);
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.includes("/api/auth/payment-status")) {
        expect(init?.signal).toBeInstanceOf(AbortSignal);
        return Promise.reject(abortError);
      }

      return originalFetch(input, init);
    });
    setRouteSearchParams(
      "status=pending&product=document-summary&email=buyer%40example.com&invoice=invoice-result"
    );

    try {
      render(<PaymentResultClient />);

      expect(
        await screen.findByRole("heading", { name: "Платёж обрабатывается" })
      ).toBeVisible();
      await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
      await new Promise((resolve) => window.setTimeout(resolve, 0));
      expect(unhandledRejections).toEqual([]);
      expect(
        screen.getByRole("heading", { name: "Платёж обрабатывается" })
      ).toBeVisible();
    } finally {
      window.removeEventListener("unhandledrejection", onUnhandledRejection);
    }
  });
});
