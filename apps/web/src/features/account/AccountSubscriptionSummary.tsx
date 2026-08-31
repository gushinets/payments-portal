import type { AccountSubscription } from "@/shared/api/subscriptions";

export function AccountSubscriptionSummary({
  subscription
}: {
  subscription: AccountSubscription;
}) {
  const validUntil = formatRussianDate(
    subscription.entitlement_validity.valid_until
  );
  const periodEnds = formatRussianDate(subscription.current_period.ends_at);
  const renewalLabel =
    subscription.renewal_mode === "automatic" ? "автоматически" : "вручную";

  return (
    <div className="notice" style={{ marginBottom: 14 }}>
      <strong style={{ color: "var(--txt)" }}>Доступ уже активен</strong>
      <br />
      Тариф: {subscription.plan.name}
      {periodEnds ? (
        <>
          <br />
          Текущий период до: {periodEnds}
        </>
      ) : null}
      {validUntil ? (
        <>
          <br />
          Доступ до: {validUntil}
        </>
      ) : null}
      <br />
      Продление: {renewalLabel}
    </div>
  );
}

export function formatRussianDate(value: string | null): string | null {
  if (!value) {
    return null;
  }

  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp)
    ? new Date(timestamp).toLocaleDateString("ru-RU")
    : null;
}
