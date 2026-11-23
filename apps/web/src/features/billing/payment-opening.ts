import { sessionStorageKey } from "@/shared/api/auth";
import { subscribeToSessionChanges } from "@/shared/session/use-session-operation";

type PaymentOpening = {
  purchaseId: string;
  userId: string;
  visit?: symbol;
  sameSession: () => boolean;
  clear: () => void;
};

let pending: PaymentOpening | undefined;

export function requestPaymentOpening(purchaseId: string, userId: string) {
  pending?.clear();
  const token = window.localStorage.getItem(sessionStorageKey);
  if (!token) return;
  const unsubscribe = subscribeToSessionChanges(clear);
  const expiry = window.setTimeout(clear, 30_000);
  window.addEventListener("popstate", clear);
  window.addEventListener("pagehide", clear);
  pending = { purchaseId, userId, sameSession: () => window.localStorage.getItem(sessionStorageKey) === token, clear };

  function clear() {
    unsubscribe();
    window.clearTimeout(expiry);
    window.removeEventListener("popstate", clear);
    window.removeEventListener("pagehide", clear);
    pending = undefined;
  }
}

export function claimPaymentOpening(purchaseId: string, userId: string, visit: symbol): (() => boolean) | undefined {
  const opening = pending;
  if (opening?.purchaseId !== purchaseId || opening.userId !== userId || (opening.visit !== undefined && opening.visit !== visit)) return;

  // Bind before the status read. A later cabinet mount cannot use this click.
  opening.visit = visit;
  return () => {
    if (pending !== opening) return false;
    const sameSession = opening.sameSession();
    opening.clear();
    return sameSession;
  };
}
