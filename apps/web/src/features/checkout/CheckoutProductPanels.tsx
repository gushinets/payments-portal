"use client";

import { Sparkles } from "lucide-react";
import {
  formatBillingPeriod,
  formatCatalogPrice,
  productPresentation,
  type CatalogProduct
} from "@/features/catalog";
import type { AuthProductState } from "@/shared/api/auth";
import type { SelectedProductAccessState } from "./ownership";

export function SelectedProductCard({
  product,
  accessState
}: {
  product: CatalogProduct;
  accessState: SelectedProductAccessState;
}) {
  const presentation = productPresentation[product.code];
  const Icon = presentation?.Icon ?? Sparkles;
  const productDescription = presentation?.description ?? product.description;

  function scrollToForm() {
    document
      .getElementById("checkout-form")
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <article className="tool-card checkout-equal-panel active">
      <div className="tool-icon-wrap">
        <Icon size={22} aria-hidden="true" />
      </div>
      {presentation?.type ? (
        <span className="tool-tag">{presentation.type}</span>
      ) : null}
      <h2>{product.name}</h2>
      <p className="muted" style={{ margin: "0 0 8px" }}>
        {presentation?.tagline}
      </p>
      {productDescription ? <p className="card-copy">{productDescription}</p> : null}
      {presentation?.valuePoints ? (
        <ul className="check-list">
          {presentation.valuePoints.map((point) => (
            <li key={point}>{point}</li>
          ))}
        </ul>
      ) : null}
      <div className="price-line">
        <strong>
          {formatCatalogPrice(
            product.plan.price_amount_minor,
            product.plan.currency
          )}
        </strong>
        <span>/ {formatBillingPeriod(product.plan.billing_period)}</span>
      </div>
      <div className="button-row" style={{ marginTop: 0 }}>
        <span className="badge badge-live">
          Пробный период {product.plan.trial_days} дней
        </span>
        {presentation?.freeLimit ? (
          <span className="badge badge-running">{presentation.freeLimit}</span>
        ) : null}
      </div>
      {accessState.status === "owned" ? (
        <div className="notice">
          Доступ уже активен. Управление доступно в аккаунте.
        </div>
      ) : accessState.status === "checking" ? (
        <div className="notice" role="status">
          Проверяем текущую подписку...
        </div>
      ) : accessState.status === "error" ? (
        <div className="notice error" role="alert">
          {accessState.message}
        </div>
      ) : (
        <div className="button-row">
          <button className="btn-primary" type="button" onClick={scrollToForm}>
            Оформить
          </button>
        </div>
      )}
    </article>
  );
}

export function SubscriptionState({
  product,
  state,
  accessState
}: {
  product?: CatalogProduct;
  state: AuthProductState | null;
  accessState: SelectedProductAccessState;
}) {
  if (!product) {
    return (
      <div className="notice">
        Выберите продукт, чтобы увидеть статус подписки и перейти к оплате.
      </div>
    );
  }

  const presentation = productPresentation[product.code];
  const status =
    accessState.status === "owned" ? "active" : state?.status ?? "inactive";
  const entitlementPlan =
    accessState.status === "owned" ? accessState.subscription?.plan : undefined;
  const entitlementValidUntil =
    accessState.status === "owned"
      ? accessState.subscription?.entitlement_validity.valid_until
      : null;
  const planName =
    (state?.status === "active" || state?.status === "pending") &&
    state.plan_name
      ? state.plan_name
      : entitlementPlan?.name ?? product.plan.name;
  const statusText =
    status === "active"
      ? "Подписка активна"
      : status === "pending"
        ? "Платёж ожидает подтверждения"
        : "Подписка не активна";
  const expiresAt = state?.expires_at ?? entitlementValidUntil;

  return (
    <div className="notice">
      <strong style={{ color: "var(--txt)" }}>{planName}</strong>
      <br />
      Статус: {statusText}
      <br />
      Стоимость: {formatCatalogPrice(
        product.plan.price_amount_minor,
        product.plan.currency
      )} / {formatBillingPeriod(product.plan.billing_period)}
      <br />
      Бесплатный лимит: {presentation?.freeLimit ?? "—"}
      {expiresAt ? (
        <>
          <br />
          Действует до: {new Date(expiresAt).toLocaleDateString("ru-RU")}
        </>
      ) : null}
      {status === "active" ? (
        <>
          <br />
          Доступ уже активен. Управление доступно в аккаунте.
        </>
      ) : null}
    </div>
  );
}
