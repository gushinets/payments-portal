"use client";

export type CheckoutAction = {
  provider: string;
  experience: "widget" | "redirect" | "embedded";
  mode: string;
  public_identifier?: string | null;
  amount_minor: number;
  amount: number;
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

const cloudPaymentsPublicId =
  process.env.NEXT_PUBLIC_CLOUDPAYMENTS_PUBLIC_ID ?? "";
const cloudPaymentsEnabled =
  process.env.NEXT_PUBLIC_CLOUDPAYMENTS_ENABLED === "true";

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

export const cloudPaymentsCheckoutAdapter: CheckoutAdapter = {
  provider: "cloudpayments",
  scriptSrc: "https://widget.cloudpayments.ru/bundles/cloudpayments",
  isRequired() {
    return cloudPaymentsEnabled && !!cloudPaymentsPublicId;
  },
  isReady() {
    return !!window.cp?.CloudPayments;
  },
  start(action, context) {
    const Widget = window.cp?.CloudPayments;
    if (!Widget) {
      throw new Error("checkout_provider_widget_unavailable");
    }
    const widget = new Widget({ language: "ru-RU" });
    widget.pay(
      cloudPaymentsWidgetMode(action.mode),
      {
        publicId: action.public_identifier ?? cloudPaymentsPublicId,
        description: action.description ?? "",
        amount: action.amount,
        currency: action.currency,
        invoiceId: action.provider_invoice_id,
        accountId: action.account_id,
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
