"use client";

import { useEffect, useState } from "react";
import {
  sessionChangedEvent,
  sessionStorageKey
} from "@/shared/api/auth";
import {
  getAccountSubscriptions,
  type AccountSubscriptionsResponse
} from "@/shared/api/subscriptions";
import { getCatalogProducts, type CatalogProduct } from "./api";
import { ProductCards, type CatalogOwnershipState } from "./ProductCards";

type CatalogState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "empty" }
  | { status: "success"; products: CatalogProduct[] };

type SubscriptionState =
  | { status: "idle" }
  | {
      status: "loaded";
      subscriptions: AccountSubscriptionsResponse["subscriptions"];
    }
  | { status: "error"; message: string };

export function CatalogProductsClient() {
  const [catalogState, setCatalogState] = useState<CatalogState>({
    status: "loading"
  });
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [sessionResolved, setSessionResolved] = useState(false);
  const [subscriptionState, setSubscriptionState] = useState<SubscriptionState>(
    { status: "idle" }
  );

  useEffect(() => {
    let cancelled = false;

    async function loadCatalog() {
      setCatalogState({ status: "loading" });

      try {
        const response = await getCatalogProducts();
        if (cancelled) {
          return;
        }

        setCatalogState(
          response.products.length > 0
            ? { status: "success", products: response.products }
            : { status: "empty" }
        );
      } catch {
        if (!cancelled) {
          setCatalogState({ status: "error" });
        }
      }
    }

    void loadCatalog();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    function syncStoredToken() {
      const nextToken = window.localStorage.getItem(sessionStorageKey);
      setSessionToken(nextToken);
      setSessionResolved(true);
      setSubscriptionState({ status: "idle" });
    }

    const timerId = window.setTimeout(syncStoredToken, 0);
    window.addEventListener(sessionChangedEvent, syncStoredToken);

    return () => {
      window.clearTimeout(timerId);
      window.removeEventListener(sessionChangedEvent, syncStoredToken);
    };
  }, []);

  useEffect(() => {
    if (!sessionResolved) {
      return;
    }

    if (!sessionToken) {
      return;
    }

    let cancelled = false;
    const token = sessionToken;

    async function loadSubscriptions() {
      try {
        const response = await getAccountSubscriptions(token);
        if (!cancelled) {
          setSubscriptionState({
            status: "loaded",
            subscriptions: response.subscriptions
          });
        }
      } catch {
        if (!cancelled) {
          setSubscriptionState({
            status: "error",
            message:
              "Не удалось проверить текущие подписки. Оформление временно недоступно."
          });
        }
      }
    }

    void loadSubscriptions();
    return () => {
      cancelled = true;
    };
  }, [sessionResolved, sessionToken]);

  const ownershipState: CatalogOwnershipState = !sessionResolved
    ? { status: "checking" }
    : !sessionToken
      ? { status: "guest" }
      : subscriptionState.status === "loaded"
        ? {
            status: "loaded",
            subscriptions: subscriptionState.subscriptions
          }
        : subscriptionState.status === "error"
          ? subscriptionState
          : { status: "loading" };

  if (catalogState.status === "loading") {
    return (
      <div className="form-panel" role="status">
        Загрузка каталога...
      </div>
    );
  }

  if (catalogState.status === "error") {
    return (
      <div className="form-panel notice error" role="alert">
        Не удалось загрузить каталог. Обновите страницу и попробуйте ещё раз.
      </div>
    );
  }

  if (catalogState.status === "empty") {
    return (
      <div className="form-panel" role="status">
        Сейчас в каталоге нет доступных продуктов.
      </div>
    );
  }

  return (
    <ProductCards
      products={catalogState.products}
      ownershipState={ownershipState}
    />
  );
}
