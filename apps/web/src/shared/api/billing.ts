export type BillingPeriod =
  | "day"
  | "days"
  | "week"
  | "weeks"
  | "month"
  | "months"
  | "year"
  | "years"
  | "annual"
  | "yearly";

export type SubscriptionRenewalMode = "manual" | "automatic";

export function isBillingPeriod(value: unknown): value is BillingPeriod {
  return (
    value === "day" ||
    value === "days" ||
    value === "week" ||
    value === "weeks" ||
    value === "month" ||
    value === "months" ||
    value === "year" ||
    value === "years" ||
    value === "annual" ||
    value === "yearly"
  );
}

export function isSubscriptionRenewalMode(
  value: unknown
): value is SubscriptionRenewalMode {
  return value === "manual" || value === "automatic";
}
