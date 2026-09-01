import { useEffect, useState } from "react";
import type { CatalogOwnershipState } from "@/features/catalog";
import {
  getAccountSubscriptions,
  type AccountSubscriptionsResponse
} from "@/shared/api/subscriptions";

type SubscriptionState =
  | { token: string; subscriptions: AccountSubscriptionsResponse["subscriptions"] }
  | { token: string; message: string }
  | null;

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
