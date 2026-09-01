import { HttpResponse, http } from "msw";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
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

function lateSucceededPaymentOnCanceledOrderPayload() {
  return {
    ...canceledPaymentStatusPayload(),
    payment: {
      payment_id: "44444444-4444-4444-8444-444444444444",
      status: "succeeded",
      provider_payment_id: "tx-late-succeeded",
      amount_minor: 99000,
      currency: "RUB",
      captured_at: "2026-08-07T10:00:00Z",
      failed_at: null,
      refunded_amount_minor: 0
    }
  };
}

function catalogProductsPayload() {
  return {
    products: [
      {
        product_id: "11111111-1111-4111-8111-111111111111",
        code: "document-summary",
        name: "Backend Document Summary",
        description: "Backend description",
        plan: {
          plan_id: "33333333-3333-4333-8333-333333333333",
          code: "document-summary-pro",
          name: "Backend Document Summary Pro",
          price_amount_minor: 123456,
          currency: "RUB",
          billing_period: "month",
          renewal_mode: "manual",
          trial_days: 7
        }
      }
    ]
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
  beforeEach(() => {
    server.use(
      http.get(`${apiBase}/api/catalog/products`, () =>
        HttpResponse.json(catalogProductsPayload())
      )
    );
  });

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

  it("keeps authoritative backend pending state over a canceled return URL", async () => {
    server.use(
      http.get(`${apiBase}/api/auth/payment-status`, () =>
        HttpResponse.json(paymentStatusPayload("pending"))
      )
    );
    setRouteSearchParams(
      "status=canceled&product=document-summary&email=buyer%40example.com&invoice=invoice-result"
    );

    render(<PaymentResultClient />);

    expect(
      await screen.findByRole("heading", { name: "Платёж обрабатывается" })
    ).toBeVisible();
    expect(screen.getByText("Ожидаем подтверждение")).toBeVisible();
    expect(screen.queryByText(/Списание не подтверждено/)).not.toBeInTheDocument();
  });

  it("shows a support result for a verified late charge on a canceled order", async () => {
    server.use(
      http.get(`${apiBase}/api/auth/payment-status`, () =>
        HttpResponse.json(lateSucceededPaymentOnCanceledOrderPayload())
      )
    );
    setRouteSearchParams(
      "status=pending&product=document-summary&email=buyer%40example.com&invoice=invoice-result"
    );

    render(<PaymentResultClient />);

    expect(
      await screen.findByRole("heading", { name: "Платёж требует проверки" })
    ).toBeVisible();
    expect(screen.getByText(/заказ уже отменён/)).toBeVisible();
    expect(screen.getByText(/Напишите в поддержку/)).toBeVisible();
    expect(screen.queryByText("Платёж подтверждён")).not.toBeInTheDocument();
  });

  it("uses the backend catalog for canceled URL presentation fallback", async () => {
    setRouteSearchParams("status=canceled&product=document-summary");

    render(<PaymentResultClient />);

    expect(
      screen.getByRole("heading", { name: "Платёж отменён" })
    ).toBeVisible();
    expect(screen.getByText(/Списание не подтверждено/)).toBeVisible();
    expect(await screen.findByText("Backend Document Summary")).toBeVisible();
    const planCard = screen.getByText(/Backend Document Summary Pro/).closest(
      ".feature-card"
    );
    expect(planCard).toHaveTextContent(/1\s234,56\s₽/);
    expect(screen.queryByText("Ожидаем подтверждение")).not.toBeInTheDocument();
  });

  it("keeps payment amount authoritative over catalog price", async () => {
    server.use(
      http.get(`${apiBase}/api/auth/payment-status`, () =>
        HttpResponse.json(canceledPaymentStatusPayload())
      )
    );
    setRouteSearchParams(
      "status=pending&product=document-summary&email=buyer%40example.com&invoice=invoice-result"
    );

    render(<PaymentResultClient />);

    const planCard = (await screen.findByText(/Document Summary Pro/))
      .closest(".feature-card");
    expect(
      await screen.findByRole("heading", { name: "Платёж отменён" })
    ).toBeVisible();
    expect(planCard).toHaveTextContent(/990\s₽/);
    expect(planCard).not.toHaveTextContent(/1\s234,56\s₽/);
  });

  it("prefers the backend payment-status plan name over stored and catalog names", async () => {
    window.sessionStorage.setItem(
      "anytoolai_last_payment_result",
      JSON.stringify({
        status: "pending",
        productCode: "document-summary",
        planName: "Stale Stored Plan",
        amount: 990,
        currency: "RUB",
        email: "buyer@example.com",
        invoiceId: "invoice-result"
      })
    );
    server.use(
      http.get(`${apiBase}/api/auth/payment-status`, () =>
        HttpResponse.json({
          ...paymentStatusPayload("active"),
          product_state: {
            ...paymentStatusPayload("active").product_state,
            plan_name: "Authoritative Backend Plan"
          }
        })
      )
    );
    setRouteSearchParams(
      "status=pending&product=document-summary&email=buyer%40example.com&invoice=invoice-result"
    );

    render(<PaymentResultClient />);

    const planCard = await screen.findByText(/Authoritative Backend Plan/);
    expect(planCard).toBeVisible();
    expect(planCard).not.toHaveTextContent("Stale Stored Plan");
    expect(planCard).not.toHaveTextContent("Backend Document Summary Pro");
  });

  it("keeps the safe fallback UI when the catalog cannot be loaded", async () => {
    server.use(
      http.get(
        `${apiBase}/api/catalog/products`,
        () => new HttpResponse(null, { status: 503 })
      )
    );
    setRouteSearchParams("status=canceled&product=document-summary");

    render(<PaymentResultClient />);

    expect(
      screen.getByRole("heading", { name: "Платёж отменён" })
    ).toBeVisible();
    expect(screen.getByText(/Списание не подтверждено/)).toBeVisible();
    await waitFor(() => {
      expect(screen.getByText("не выбран")).toBeVisible();
      expect(screen.getByText("тариф не выбран")).toBeVisible();
    });
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
