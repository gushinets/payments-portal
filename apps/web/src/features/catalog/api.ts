import { resolveApiBase, requestTimeoutMs } from "@/shared/api/auth";
import {
  isBillingPeriod,
  isSubscriptionRenewalMode,
  type BillingPeriod,
  type SubscriptionRenewalMode
} from "@/shared/api/billing";

export type CatalogPlan = {
  plan_id: string;
  code: string;
  name: string;
  price_amount_minor: number;
  currency: "RUB";
  billing_period: BillingPeriod;
  renewal_mode: SubscriptionRenewalMode;
  trial_days: number;
};

export type CatalogProduct = {
  product_id: string;
  code: string;
  name: string;
  description: string | null;
  plan: CatalogPlan;
};

export type CatalogProductsResponse = {
  products: CatalogProduct[];
};

export function decodeCatalogProductsResponse(
  payload: unknown
): CatalogProductsResponse {
  if (!isRecord(payload) || !Array.isArray(payload.products)) {
    throw new Error("invalid_catalog_products_response");
  }

  return {
    products: payload.products.map(decodeCatalogProduct)
  };
}

export async function getCatalogProducts(): Promise<CatalogProductsResponse> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(
    () => controller.abort(),
    requestTimeoutMs
  );

  const response = await fetch(`${resolveApiBase()}/api/catalog/products`, {
    signal: controller.signal
  }).finally(() => window.clearTimeout(timeoutId));

  if (!response.ok) {
    throw new Error(`catalog_request_failed:${response.status}`);
  }

  const payload: unknown = await response.json();
  return decodeCatalogProductsResponse(payload);
}

function decodeCatalogProduct(value: unknown): CatalogProduct {
  if (!isRecord(value)) {
    throw new Error("invalid_catalog_product");
  }

  if (
    typeof value.product_id !== "string" ||
    typeof value.code !== "string" ||
    typeof value.name !== "string" ||
    (value.description !== null && typeof value.description !== "string") ||
    !isRecord(value.plan)
  ) {
    throw new Error("invalid_catalog_product");
  }

  return {
    product_id: value.product_id,
    code: value.code,
    name: value.name,
    description: value.description,
    plan: decodeCatalogPlan(value.plan)
  };
}

function decodeCatalogPlan(value: Record<string, unknown>): CatalogPlan {
  if (
    typeof value.plan_id !== "string" ||
    typeof value.code !== "string" ||
    typeof value.name !== "string" ||
    !isNonNegativeInteger(value.price_amount_minor) ||
    !isSupportedCatalogCurrency(value.currency) ||
    !isBillingPeriod(value.billing_period) ||
    !isSubscriptionRenewalMode(value.renewal_mode) ||
    !isNonNegativeInteger(value.trial_days)
  ) {
    throw new Error("invalid_catalog_plan");
  }

  return {
    plan_id: value.plan_id,
    code: value.code,
    name: value.name,
    price_amount_minor: value.price_amount_minor,
    currency: value.currency,
    billing_period: value.billing_period,
    renewal_mode: value.renewal_mode,
    trial_days: value.trial_days
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonNegativeInteger(value: unknown): value is number {
  return (
    typeof value === "number" &&
    Number.isFinite(value) &&
    Number.isInteger(value) &&
    value >= 0
  );
}

function isSupportedCatalogCurrency(value: unknown): value is "RUB" {
  return value === "RUB";
}
