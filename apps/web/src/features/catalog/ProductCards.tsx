import Link from "next/link";
import { ArrowRight, CheckCircle2, Sparkles } from "lucide-react";
import type { CatalogProduct } from "./api";
import {
  formatBillingPeriod,
  formatCatalogPrice,
  productPresentation
} from "./catalog";
import {
  hasCurrentProductEntitlement,
  type AccountSubscription
} from "@/shared/api/subscriptions";

export type CatalogOwnershipState =
  | { status: "checking" }
  | { status: "guest" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "loaded"; subscriptions: AccountSubscription[] };

export function ProductCards({
  products = [],
  selectedCode,
  ownershipState = { status: "guest" }
}: {
  products?: CatalogProduct[];
  selectedCode?: string;
  ownershipState?: CatalogOwnershipState;
}) {
  return (
    <>
      {ownershipState.status === "error" ? (
        <div className="notice error" role="status" style={{ marginBottom: 16 }}>
          {ownershipState.message}
        </div>
      ) : null}
      <div className="tools-grid">
        {products.map((product) => {
          const presentation = productPresentation[product.code];
          const Icon = presentation?.Icon ?? Sparkles;
          const selected = selectedCode === product.code;
          const currentSubscription =
            ownershipState.status === "loaded"
              ? ownershipState.subscriptions.find((subscription) =>
                  hasCurrentProductEntitlement(
                    subscription,
                    product.product_id,
                    new Date()
                  )
                )
              : undefined;
          const productDescription =
            presentation?.description ?? product.description;

          return (
            <article
              className={`tool-card${selected ? " active" : ""}`}
              key={product.code}
            >
              <div className="tool-icon-wrap">
                <Icon size={22} aria-hidden="true" />
              </div>
              {presentation?.type ? (
                <span className="tool-tag">{presentation.type}</span>
              ) : null}
              <h3>{product.name}</h3>
              <p className="muted" style={{ margin: "0 0 8px" }}>
                Тариф: {product.plan.name}
              </p>
              {presentation?.tagline ? (
                <p className="muted" style={{ margin: "0 0 8px" }}>
                  {presentation.tagline}
                </p>
              ) : null}
              {productDescription ? (
                <p className="card-copy">{productDescription}</p>
              ) : null}
              {presentation?.valuePoints ? (
                <ul className="check-list">
                  {presentation.valuePoints.map((point) => (
                    <li key={point}>{point}</li>
                  ))}
                </ul>
              ) : null}
              <div className="tool-card-bottom">
                <div className="price-line">
                  <strong>
                    {formatCatalogPrice(
                      product.plan.price_amount_minor,
                      product.plan.currency
                    )}
                  </strong>
                  <span>
                    / {formatBillingPeriod(product.plan.billing_period)}
                  </span>
                </div>
                <div className="muted" style={{ marginTop: 4 }}>
                  Продление:{" "}
                  {product.plan.renewal_mode === "automatic"
                    ? "автоматически"
                    : "вручную"}
                </div>
                <div className="button-row" style={{ marginTop: 0 }}>
                  <span className="badge badge-live">
                    <CheckCircle2 size={12} aria-hidden="true" />
                    {product.plan.trial_days} дней бесплатно
                  </span>
                  {presentation?.freeLimit ? (
                    <span className="badge badge-running">
                      {presentation.freeLimit}
                    </span>
                  ) : null}
                </div>
                {currentSubscription ? (
                  <CurrentSubscriptionSummary
                    subscription={currentSubscription}
                  />
                ) : ownershipState.status === "checking" ||
                  ownershipState.status === "loading" ? (
                  <div className="notice" role="status">
                    Проверяем текущую подписку...
                  </div>
                ) : ownershipState.status === "error" ? (
                  <div className="notice">Статус подписки пока недоступен.</div>
                ) : (
                  <div className="button-row">
                    <Link
                      className="btn-primary"
                      href={`/ru/auth-checkout?product=${product.code}`}
                    >
                      Оформить <ArrowRight size={15} aria-hidden="true" />
                    </Link>
                  </div>
                )}
              </div>
            </article>
          );
        })}
      </div>
    </>
  );
}

function CurrentSubscriptionSummary({
  subscription
}: {
  subscription: AccountSubscription;
}) {
  const validUntil = formatRussianDate(
    subscription.entitlement_validity.valid_until
  );
  const periodStarts = formatRussianDate(
    subscription.current_period.starts_at
  );
  const periodEnds = formatRussianDate(subscription.current_period.ends_at);
  const renewalLabel =
    subscription.renewal_mode === "automatic" ? "автоматически" : "вручную";

  return (
    <div className="notice">
      <strong style={{ color: "var(--txt)" }}>Доступ уже активен</strong>
      <br />
      Тариф: {subscription.plan.name}
      {validUntil ? (
        <>
          <br />
          Действует до: {validUntil}
        </>
      ) : null}
      {periodStarts && periodEnds ? (
        <>
          <br />
          Текущий период: {periodStarts} — {periodEnds}
        </>
      ) : null}
      <br />
      <span>Продление: {renewalLabel}</span>
      <div className="button-row">
        <Link className="btn-secondary" href="/ru/account">
          Личный кабинет <ArrowRight size={15} aria-hidden="true" />
        </Link>
      </div>
    </div>
  );
}

function formatRussianDate(value: string | null): string | null {
  if (!value) {
    return null;
  }

  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp)
    ? new Date(timestamp).toLocaleDateString("ru-RU")
    : null;
}
