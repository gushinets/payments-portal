import { getJson } from "./auth";
import {
  isBillingPeriod,
  isSubscriptionRenewalMode,
  type BillingPeriod,
  type SubscriptionRenewalMode
} from "./billing";

export type SubscriptionStatus =
  | "trialing"
  | "active"
  | "past_due"
  | "canceled"
  | "expired"
  | "refunded"
  | "paused";

export type SubscriptionScopeType = "product" | "bundle" | "all_access";

export type EntitlementStatus =
  | "active"
  | "expired"
  | "revoked"
  | "superseded";

export type AccountSubscription = {
  subscription_id: string;
  plan: {
    plan_id: string;
    code: string;
    name: string;
    billing_period: BillingPeriod;
  };
  scope: {
    scope_type: SubscriptionScopeType;
    product_id: string | null;
    bundle_id: string | null;
  };
  status: SubscriptionStatus;
  renewal_mode: SubscriptionRenewalMode;
  current_period: {
    starts_at: string;
    ends_at: string;
  };
  cancellation: {
    cancel_requested_at: string | null;
    canceled_at: string | null;
  };
  entitlement_validity: {
    status: EntitlementStatus | null;
    valid_from: string | null;
    valid_until: string | null;
  };
};

export type AccountSubscriptionsResponse = {
  subscriptions: AccountSubscription[];
};

export function decodeAccountSubscriptionsResponse(
  payload: unknown
): AccountSubscriptionsResponse {
  if (!isRecord(payload) || !Array.isArray(payload.subscriptions)) {
    throw new Error("invalid_subscriptions_response");
  }

  return {
    subscriptions: payload.subscriptions.map(decodeAccountSubscription)
  };
}

export function getAccountSubscriptions(
  token: string
): Promise<AccountSubscriptionsResponse> {
  return getJson(
    "/api/account/subscriptions",
    token,
    decodeAccountSubscriptionsResponse
  );
}

export function hasCurrentProductEntitlement(
  subscription: AccountSubscription,
  productId: string,
  now = new Date()
): boolean {
  if (
    subscription.scope.scope_type !== "product" ||
    subscription.scope.product_id !== productId ||
    subscription.entitlement_validity.status !== "active" ||
    subscription.entitlement_validity.valid_from === null ||
    subscription.entitlement_validity.valid_until === null
  ) {
    return false;
  }

  const nowMs = now.getTime();
  const validFromMs = Date.parse(subscription.entitlement_validity.valid_from);
  const validUntilMs = Date.parse(subscription.entitlement_validity.valid_until);

  return (
    Number.isFinite(nowMs) &&
    Number.isFinite(validFromMs) &&
    Number.isFinite(validUntilMs) &&
    validFromMs <= nowMs &&
    validUntilMs > nowMs
  );
}

function decodeAccountSubscription(value: unknown): AccountSubscription {
  if (!isRecord(value)) {
    throw new Error("invalid_subscription");
  }

  if (
    typeof value.subscription_id !== "string" ||
    !isRecord(value.plan) ||
    !isRecord(value.scope) ||
    !isSubscriptionStatus(value.status) ||
    !isSubscriptionRenewalMode(value.renewal_mode) ||
    !isRecord(value.current_period) ||
    !isRecord(value.cancellation) ||
    !isRecord(value.entitlement_validity)
  ) {
    throw new Error("invalid_subscription");
  }

  const plan = decodePlan(value.plan);
  const scope = decodeScope(value.scope);
  const currentPeriod = decodeCurrentPeriod(value.current_period);
  const cancellation = decodeCancellation(value.cancellation);
  const entitlementValidity = decodeEntitlementValidity(
    value.entitlement_validity
  );

  return {
    subscription_id: value.subscription_id,
    plan,
    scope,
    status: value.status,
    renewal_mode: value.renewal_mode,
    current_period: currentPeriod,
    cancellation,
    entitlement_validity: entitlementValidity
  };
}

function decodePlan(value: Record<string, unknown>): AccountSubscription["plan"] {
  if (
    typeof value.plan_id !== "string" ||
    typeof value.code !== "string" ||
    typeof value.name !== "string" ||
    !isBillingPeriod(value.billing_period)
  ) {
    throw new Error("invalid_subscription_plan");
  }

  return {
    plan_id: value.plan_id,
    code: value.code,
    name: value.name,
    billing_period: value.billing_period
  };
}

function decodeScope(
  value: Record<string, unknown>
): AccountSubscription["scope"] {
  if (
    !isScopeType(value.scope_type) ||
    !isNullableString(value.product_id) ||
    !isNullableString(value.bundle_id)
  ) {
    throw new Error("invalid_subscription_scope");
  }

  return {
    scope_type: value.scope_type,
    product_id: value.product_id,
    bundle_id: value.bundle_id
  };
}

function decodeCurrentPeriod(
  value: Record<string, unknown>
): AccountSubscription["current_period"] {
  if (typeof value.starts_at !== "string" || typeof value.ends_at !== "string") {
    throw new Error("invalid_subscription_current_period");
  }

  return { starts_at: value.starts_at, ends_at: value.ends_at };
}

function decodeCancellation(
  value: Record<string, unknown>
): AccountSubscription["cancellation"] {
  if (
    !isNullableString(value.cancel_requested_at) ||
    !isNullableString(value.canceled_at)
  ) {
    throw new Error("invalid_subscription_cancellation");
  }

  return {
    cancel_requested_at: value.cancel_requested_at,
    canceled_at: value.canceled_at
  };
}

function decodeEntitlementValidity(
  value: Record<string, unknown>
): AccountSubscription["entitlement_validity"] {
  if (
    !isNullableEntitlementStatus(value.status) ||
    !isNullableString(value.valid_from) ||
    !isNullableString(value.valid_until)
  ) {
    throw new Error("invalid_entitlement_validity");
  }

  return {
    status: value.status,
    valid_from: value.valid_from,
    valid_until: value.valid_until
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isSubscriptionStatus(value: unknown): value is SubscriptionStatus {
  return (
    value === "trialing" ||
    value === "active" ||
    value === "past_due" ||
    value === "canceled" ||
    value === "expired" ||
    value === "refunded" ||
    value === "paused"
  );
}

function isScopeType(value: unknown): value is SubscriptionScopeType {
  return value === "product" || value === "bundle" || value === "all_access";
}

function isNullableEntitlementStatus(
  value: unknown
): value is EntitlementStatus | null {
  return (
    value === null ||
    value === "active" ||
    value === "expired" ||
    value === "revoked" ||
    value === "superseded"
  );
}
