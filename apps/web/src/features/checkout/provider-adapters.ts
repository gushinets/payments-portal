"use client";

export type CheckoutAction = {
  provider: string;
  experience: "widget" | "redirect" | "embedded";
  mode: string;
  public_identifier?: string | null;
  amount_minor: number;
  amount: number | string;
  currency: string;
  merchant_order_id: string;
  provider_invoice_id: string;
  account_id: string;
  description?: string | null;
  metadata?: Record<string, unknown>;
};

export type CheckoutAdapterStatus = "disabled" | "loading" | "ready" | "failed";
type CloudPaymentsWidgetMode = "charge" | "auth";

export type CheckoutAdapterResultContext = {
  productCode: string;
  planCode: string;
  email: string;
  invoiceId: string;
};

export type CheckoutAdapter = {
  provider: string;
  scriptSrc?: string;
  isRequired(): boolean;
  isReady(): boolean;
  start(
    action: CheckoutAction,
    context: CheckoutAdapterResultContext
  ): void;
};

function paymentResultUrl(
  status: "pending" | "failed",
  context: CheckoutAdapterResultContext
) {
  const params = new URLSearchParams({
    status,
    product: context.productCode,
    plan: context.planCode,
    email: context.email,
    invoice: context.invoiceId
  });
  return `/ru/payment-result?${params.toString()}`;
}

function cloudPaymentsWidgetMode(mode: string): CloudPaymentsWidgetMode {
  if (mode === "charge" || mode === "auth") {
    return mode;
  }
  throw new Error("unsupported_cloudpayments_widget_mode");
}

function requireNonEmptyString(value: unknown, code: string): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error(code);
  }
  return value;
}

function amountFromMinorUnits(amountMinor: number): number {
  return amountMinor / 100;
}

function validateCloudPaymentsAction(action: CheckoutAction) {
  if (action.experience !== "widget") {
    throw new Error("unsupported_checkout_experience");
  }
  const publicId = requireNonEmptyString(
    action.public_identifier,
    "checkout_provider_public_identifier_missing"
  );
  const invoiceId = requireNonEmptyString(
    action.provider_invoice_id,
    "checkout_provider_invoice_missing"
  );
  const accountId = requireNonEmptyString(
    action.account_id,
    "checkout_provider_account_missing"
  );
  const currency = requireNonEmptyString(
    action.currency,
    "checkout_provider_currency_missing"
  );
  if (!Number.isInteger(action.amount_minor) || action.amount_minor <= 0) {
    throw new Error("checkout_provider_amount_minor_invalid");
  }
  const amount = amountFromMinorUnits(action.amount_minor);
  if (!Number.isFinite(amount) || amount <= 0) {
    throw new Error("checkout_provider_amount_invalid");
  }
  return { publicId, invoiceId, accountId, currency, amount };
}

export const cloudPaymentsCheckoutAdapter: CheckoutAdapter = {
  provider: "cloudpayments",
  scriptSrc: "https://widget.cloudpayments.ru/bundles/cloudpayments",
  isRequired() {
    return true;
  },
  isReady() {
    return !!window.cp?.CloudPayments;
  },
  start(action, context) {
    const Widget = window.cp?.CloudPayments;
    if (!Widget) {
      throw new Error("checkout_provider_widget_unavailable");
    }
    const validated = validateCloudPaymentsAction(action);
    const widget = new Widget({ language: "ru-RU" });
    widget.pay(
      cloudPaymentsWidgetMode(action.mode),
      {
        publicId: validated.publicId,
        description: action.description ?? "",
        amount: validated.amount,
        currency: validated.currency,
        invoiceId: validated.invoiceId,
        accountId: validated.accountId,
        email: context.email,
        data: action.metadata
      },
      {
        onSuccess: () => {
          window.location.assign(paymentResultUrl("pending", context));
        },
        onFail: () => {
          window.location.assign(paymentResultUrl("failed", context));
        }
      }
    );
  }
};

const checkoutAdapters = new Map<string, CheckoutAdapter>([
  [cloudPaymentsCheckoutAdapter.provider, cloudPaymentsCheckoutAdapter]
]);

export function getCheckoutAdapter(provider: string): CheckoutAdapter | null {
  return checkoutAdapters.get(provider) ?? null;
}

export function registeredCheckoutAdapters(): CheckoutAdapter[] {
  return Array.from(checkoutAdapters.values());
}
