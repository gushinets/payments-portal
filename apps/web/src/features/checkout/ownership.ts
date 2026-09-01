import { useEffect, useState } from "react";
import type { CatalogOwnershipState } from "@/features/catalog";
import {
  getAccountSubscriptions,
  hasCurrentProductEntitlement,
  type AccountSubscription,
  type AccountSubscriptionsResponse
} from "@/shared/api/subscriptions";
import type { AuthProductState } from "@/shared/api/auth";
import type { CatalogProduct } from "@/features/catalog";

type SubscriptionState =
  | { token: string; subscriptions: AccountSubscriptionsResponse["subscriptions"] }
  | { token: string; message: string }
  | null;

export type SelectedProductAccessState =
  | { status: "available" }
  | { status: "checking" }
  | { status: "error"; message: string }
  | { status: "owned"; subscription?: AccountSubscription };

export function resolveSelectedProductAccess(
  product: CatalogProduct | undefined,
  productState: AuthProductState | null,
  ownershipState: CatalogOwnershipState,
  now = new Date()
): SelectedProductAccessState {
  if (productState?.status === "active") {
    return { status: "owned" };
  }

  if (!product || ownershipState.status === "guest") {
    return { status: "available" };
  }

  if (
    ownershipState.status === "checking" ||
    ownershipState.status === "loading"
  ) {
    return { status: "checking" };
  }

  if (ownershipState.status === "error") {
    return { status: "error", message: ownershipState.message };
  }

  const subscription = ownershipState.subscriptions.find((candidate) =>
    hasCurrentProductEntitlement(candidate, product.product_id, now)
  );
  return subscription
    ? { status: "owned", subscription }
    : { status: "available" };
}

export function useCheckoutOwnership(
  sessionResolved: boolean,
  sessionToken: string
): CatalogOwnershipState {
  const [subscriptionState, setSubscriptionState] = useState<SubscriptionState>(null);

  useEffect(() => {
    if (!sessionResolved || !sessionToken) {
      return;
    }

    let cancelled = false;
    const token = sessionToken;

    async function loadSubscriptions() {
      try {
        const response = await getAccountSubscriptions(token);
        if (!cancelled) {
          setSubscriptionState({ token, subscriptions: response.subscriptions });
        }
      } catch {
        if (!cancelled) {
          setSubscriptionState({
            token,
            message: "Не удалось проверить текущие подписки. Оформление временно недоступно."
          });
        }
      }
    }

    void loadSubscriptions();
    return () => {
      cancelled = true;
    };
  }, [sessionResolved, sessionToken]);

  if (!sessionResolved) {
    return { status: "checking" };
  }
  if (!sessionToken) {
    return { status: "guest" };
  }
  if (subscriptionState?.token !== sessionToken) {
    return { status: "loading" };
  }
  if ("subscriptions" in subscriptionState) {
    return { status: "loaded", subscriptions: subscriptionState.subscriptions };
  }
  return { status: "error", message: subscriptionState.message };
}
