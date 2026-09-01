"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ArrowRight, LogOut, UserRound } from "lucide-react";
import {
  formatBillingPeriod,
  formatCatalogPrice,
  getCatalogProducts,
  productPresentation,
  type CatalogProduct
} from "@/features/catalog";
import {
  decodeAuthSessionResponse,
  getJson,
  type AuthProductState,
  type AuthSessionResponse
} from "@/shared/api/auth";
import {
  getAccountSubscriptions,
  hasCurrentProductEntitlement,
  type AccountSubscription
} from "@/shared/api/subscriptions";
import {
  AccountSubscriptionSummary,
  formatRussianDate
} from "./AccountSubscriptionSummary";

const sessionStorageKey = "anytoolai_session_token_v1";
const sessionChangedEvent = "anytoolai_session_changed";

function statusLabel(
  status: AuthProductState["status"] | undefined,
  failedToLoad: boolean,
  loading: boolean,
  currentAccess: boolean,
  subscriptionsLoaded: boolean
): string {
  if (currentAccess) {
    return "Подписка активна";
  }
  if (status === "pending") {
    return "Платёж ожидает подтверждения";
  }
  if (status === "failed") {
    return "Платёж не подтверждён";
  }
  if (loading) {
    return "Статус загружается";
  }
  if (failedToLoad) {
    return "Статус подписки не загружен";
  }
  if (!subscriptionsLoaded) {
    return "Проверяем текущую подписку";
  }
  return "Подписка не активна";
}

function sessionPath(productCode?: string): string {
  const query = productCode
    ? `?product=${encodeURIComponent(productCode)}`
    : "";
  return `/api/auth/session${query}`;
}

function accountKey(session: AuthSessionResponse): string {
  return `${session.user.tenant_id}:${session.user.region}:${session.user.user_id}`;
}

function requireAuthenticatedSession(
  session: AuthSessionResponse
): AuthSessionResponse {
  if (!session.authenticated) {
    throw new Error("invalid_session");
  }

  return session;
}

export function AccountClient() {
  const [email, setEmail] = useState("");
  const [catalogProducts, setCatalogProducts] = useState<CatalogProduct[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState("");
  const [subscriptions, setSubscriptions] = useState<AccountSubscription[]>([]);
  const [subscriptionStatus, setSubscriptionStatus] = useState<
    "loading" | "loaded" | "error"
  >("loading");
  const [subscriptionError, setSubscriptionError] = useState("");
  const [states, setStates] = useState<Record<string, AuthProductState>>({});
  const [loadingProductCodes, setLoadingProductCodes] = useState<Set<string>>(
    () => new Set()
  );
  const [failedProductCodes, setFailedProductCodes] = useState<Set<string>>(
    () => new Set()
  );
  const [productLoadError, setProductLoadError] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const loadIdRef = useRef(0);
  const accountKeyRef = useRef("");

  useEffect(() => {
    let cancelled = false;

    async function loadAccount() {
      const loadId = loadIdRef.current + 1;
      loadIdRef.current = loadId;
      const isCurrentLoad = () => !cancelled && loadIdRef.current === loadId;
      const token = window.localStorage.getItem(sessionStorageKey);

      if (!token) {
        setEmail("");
        setCatalogProducts([]);
        setCatalogLoading(false);
        setCatalogError("");
        setSubscriptions([]);
        setSubscriptionStatus("loading");
        setSubscriptionError("");
        setStates({});
        setLoadingProductCodes(new Set());
        setFailedProductCodes(new Set());
        setProductLoadError("");
        accountKeyRef.current = "";
        setLoading(false);
        setError("Войдите в аккаунт, чтобы увидеть статус подписок.");
        return;
      }

      setLoading(true);
      setError("");
      setCatalogLoading(true);
      setCatalogError("");
      setSubscriptions([]);
      setSubscriptionStatus("loading");
      setSubscriptionError("");

      try {
        const session = requireAuthenticatedSession(
          await getJson(sessionPath(), token, decodeAuthSessionResponse)
        );

        if (!isCurrentLoad()) {
          return;
        }

        const nextAccountKey = accountKey(session);
        setEmail(session.user.email);
        if (accountKeyRef.current && accountKeyRef.current !== nextAccountKey) {
          setStates({});
        }
        accountKeyRef.current = nextAccountKey;

        void getAccountSubscriptions(token)
          .then((response) => {
            if (!isCurrentLoad()) {
              return;
            }

            setSubscriptions(response.subscriptions);
            setSubscriptionStatus("loaded");
            setSubscriptionError("");
          })
          .catch(() => {
            if (!isCurrentLoad()) {
              return;
            }

            setSubscriptions([]);
            setSubscriptionStatus("error");
            setSubscriptionError(
              "Не удалось проверить текущие подписки. Статус доступа временно недоступен."
            );
          });

        const [catalogResult] = await Promise.allSettled([getCatalogProducts()]);

        if (!isCurrentLoad()) {
          return;
        }

        const nextCatalogProducts =
          catalogResult.status === "fulfilled"
            ? catalogResult.value.products
            : [];
        setCatalogProducts(nextCatalogProducts);
        setCatalogLoading(false);
        setCatalogError(
          catalogResult.status === "rejected"
            ? "Не удалось загрузить каталог. Обновите страницу и попробуйте ещё раз."
            : ""
        );

        if (catalogResult.status === "rejected") {
          setStates({});
          setLoadingProductCodes(new Set());
          setFailedProductCodes(new Set());
          setProductLoadError("");
          setLoading(false);
          return;
        }

        setLoadingProductCodes(
          new Set(nextCatalogProducts.map((product) => product.code))
        );
        setLoading(false);

        const payloads = await Promise.allSettled(
          nextCatalogProducts.map((product) =>
            getJson(
              sessionPath(product.code),
              token,
              decodeAuthSessionResponse
            ).then(requireAuthenticatedSession)
          )
        );

        if (!isCurrentLoad()) {
          return;
        }

        const rejectedCodes = new Set(
          nextCatalogProducts
            .filter((_, index) => payloads[index]?.status === "rejected")
            .map((product) => product.code)
        );
        setStates((currentStates) => {
          const nextStates = { ...currentStates };

          payloads.forEach((payload, index) => {
            const productCode = nextCatalogProducts[index]?.code;
            if (!productCode) {
              return;
            }

            if (payload.status === "rejected") {
              return;
            }

            const productState = payload.value.product_state;
            if (productState) {
              nextStates[productCode] = productState;
            } else {
              delete nextStates[productCode];
            }
          });

          return nextStates;
        });
        setFailedProductCodes(rejectedCodes);
        setLoadingProductCodes(new Set());
        setProductLoadError(
          rejectedCodes.size > 0
            ? "Не удалось загрузить статусы части подписок. Обновите страницу."
            : ""
        );
      } catch {
        const shouldShowFatalError = isCurrentLoad();
        window.localStorage.removeItem(sessionStorageKey);
        window.dispatchEvent(new Event(sessionChangedEvent));
        if (shouldShowFatalError && !cancelled) {
          setEmail("");
          setCatalogProducts([]);
          setCatalogLoading(false);
          setCatalogError("");
          setSubscriptions([]);
          setSubscriptionStatus("loading");
          setSubscriptionError("");
          setStates({});
          setLoadingProductCodes(new Set());
          setFailedProductCodes(new Set());
          setProductLoadError("");
          accountKeyRef.current = "";
          setLoading(false);
          setError("Не удалось загрузить аккаунт. Войдите ещё раз.");
        }
      } finally {
        if (isCurrentLoad()) {
          setLoading(false);
        }
      }
    }

    const timerId = window.setTimeout(() => {
      void loadAccount();
    }, 0);
    window.addEventListener(sessionChangedEvent, loadAccount);

    return () => {
      cancelled = true;
      window.clearTimeout(timerId);
      window.removeEventListener(sessionChangedEvent, loadAccount);
    };
  }, []);

  function logout() {
    window.localStorage.removeItem(sessionStorageKey);
    window.dispatchEvent(new Event(sessionChangedEvent));
    // Full navigation discards root-layout session state and in-flight session requests.
    window.location.assign(new URL("/ru", window.location.href));
  }

  if (loading) {
    return (
      <section className="page-section compact">
        <div className="form-panel">Загрузка аккаунта...</div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="page-section compact">
        <div className="form-panel">
          <span className="badge badge-running">
            <UserRound size={12} aria-hidden="true" />
            Аккаунт
          </span>
          <h1 className="legal-title" style={{ marginTop: 14 }}>
            Личный кабинет
          </h1>
          <div className="notice" style={{ marginTop: 20 }}>
            {error}
          </div>
          <div className="hero-actions">
            <Link className="btn-primary" href="/ru">
              На главную
            </Link>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="page-section compact">
      <div className="eyebrow">
        <span className="eyebrow-dot" />
        Аккаунт
      </div>
      <h1 className="legal-title">Личный кабинет</h1>
      <p className="hero-copy">
        Здесь отображается текущий аккаунт и статусы подписок по продуктам.
      </p>

      {productLoadError ? (
        <div className="notice" role="status">
          {productLoadError}
        </div>
      ) : null}
      {subscriptionError ? (
        <div className="notice" role="status">
          {subscriptionError}
        </div>
      ) : null}

      <div className="account-layout">
        <article className="form-panel account-summary-panel">
          <span className="badge badge-live">
            <UserRound size={12} aria-hidden="true" />
            Вход выполнен
          </span>
          <h2 style={{ marginTop: 14 }}>Аккаунт</h2>
          <p className="card-copy account-summary-email">{email}</p>
          <div className="account-summary-actions">
            <button className="btn-secondary" type="button" onClick={logout}>
              <LogOut size={15} aria-hidden="true" />
              Выйти
            </button>
          </div>
        </article>

        <div className="account-products-grid">
          {catalogLoading ? (
            <div className="form-panel" role="status">
              Загрузка каталога...
            </div>
          ) : catalogError ? (
            <div className="form-panel notice error" role="alert">
              {catalogError}
            </div>
          ) : catalogProducts.length === 0 ? (
            <div className="form-panel" role="status">
              Сейчас в каталоге нет доступных продуктов.
            </div>
          ) : (
            catalogProducts.map((product) => {
              const state = states[product.code];
              const presentation = productPresentation[product.code];
              const currentSubscription =
                subscriptionStatus === "loaded"
                  ? subscriptions.find((subscription) =>
                      hasCurrentProductEntitlement(
                        subscription,
                        product.product_id,
                        new Date()
                      )
                    )
                  : undefined;
              const isActive =
                Boolean(currentSubscription) || state?.status === "active";
              const isPending = state?.status === "pending";
              const failedToLoad = failedProductCodes.has(product.code);
              const productLoading = loadingProductCodes.has(product.code);
              const canOfferPurchase =
                subscriptionStatus === "loaded" && !isActive;

              return (
                <article className="tool-card" key={product.code}>
                  <span
                    className={`badge ${
                      isActive
                        ? "badge-live"
                        : isPending
                          ? "badge-running"
                          : "badge-demo"
                    }`}
                  >
                    {statusLabel(
                      state?.status,
                      failedToLoad,
                      productLoading,
                      isActive,
                      subscriptionStatus === "loaded"
                    )}
                  </span>
                  <h2 style={{ marginTop: 14 }}>{product.name}</h2>
                  {presentation?.tagline || product.description ? (
                    <p className="card-copy">
                      {presentation?.tagline ?? product.description}
                    </p>
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
                    {currentSubscription ? (
                      <AccountSubscriptionSummary
                        subscription={currentSubscription}
                      />
                    ) : state?.expires_at ? (
                      <p className="muted" style={{ margin: "0 0 14px" }}>
                        Действует до{" "}
                        {formatRussianDate(state.expires_at) ?? state.expires_at}
                      </p>
                    ) : null}
                    {isActive ? (
                      <Link
                        className="btn-secondary"
                        href={`/ru/auth-checkout?product=${product.code}`}
                      >
                        Управлять <ArrowRight size={15} aria-hidden="true" />
                      </Link>
                    ) : canOfferPurchase ? (
                      <Link
                        className="btn-primary"
                        href={`/ru/auth-checkout?product=${product.code}`}
                      >
                        Оформить <ArrowRight size={15} aria-hidden="true" />
                      </Link>
                    ) : (
                      <div className="notice" role="status">
                        {subscriptionStatus === "error"
                          ? "Статус подписки недоступен. Обновите страницу."
                          : "Проверяем текущую подписку..."}
                      </div>
                    )}
                  </div>
                </article>
              );
            })
          )}
        </div>
      </div>
    </section>
  );
}
