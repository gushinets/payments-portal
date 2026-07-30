import { expect, vi } from "vitest";

type ProviderOutcome = "success" | "fail";

type ProviderCallbacks = {
  onSuccess?: () => void;
  onFail?: () => void;
};

type ProviderPaymentRequest = {
  publicId?: string;
  description?: string;
  amount?: number;
  currency?: string;
  invoiceId?: string;
  accountId?: string;
  email?: string;
  data?: Record<string, unknown>;
};

export type ProviderUiStub = {
  payments: ProviderPaymentRequest[];
  complete: (outcome: ProviderOutcome) => void;
};

export function installProviderUiStub(): ProviderUiStub {
  const payments: ProviderPaymentRequest[] = [];
  let callbacks: ProviderCallbacks | undefined;

  class ProviderNeutralCheckoutWidget {
    pay(
      _mode: "charge",
      request: ProviderPaymentRequest,
      nextCallbacks?: ProviderCallbacks
    ) {
      payments.push(request);
      callbacks = nextCallbacks;
    }
  }

  window.cp = {
    CloudPayments: vi.fn(() => new ProviderNeutralCheckoutWidget()) as unknown as NonNullable<
      Window["cp"]
    >["CloudPayments"]
  };

  return {
    payments,
    complete: (outcome: ProviderOutcome) => {
      if (outcome === "success") {
        callbacks?.onSuccess?.();
      } else {
        callbacks?.onFail?.();
      }
    }
  };
}

export function expectNoCardData(request: ProviderPaymentRequest) {
  const serialized = JSON.stringify(request).toLowerCase();
  expect(serialized).not.toContain("card");
  expect(serialized).not.toContain("pan");
  expect(serialized).not.toContain("cvv");
  expect(serialized).not.toContain("cvc");
}
