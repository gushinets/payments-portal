import { sessionStorageKey } from "@/shared/api/auth";
import { subscribeToSessionChanges } from "@/shared/session/use-session-operation";

let pending: { purchaseId: string; userId: string; sameSession: () => boolean; clear: () => void } | undefined;

export function requestPaymentOpening(purchaseId: string, userId: string) {
  pending?.clear();
  const token = window.localStorage.getItem(sessionStorageKey);
  if (!token) return;
  const unsubscribe = subscribeToSessionChanges(clear);
  const expiry = window.setTimeout(clear, 30_000);
  pending = { purchaseId, userId, sameSession: () => window.localStorage.getItem(sessionStorageKey) === token, clear };

  function clear() {
    unsubscribe();
    window.clearTimeout(expiry);
    pending = undefined;
  }
}

export function takePaymentOpening(purchaseId: string, userId: string): boolean {
  if (pending?.purchaseId !== purchaseId || pending.userId !== userId) return false;
  const sameSession = pending.sameSession();
  pending.clear();
  return sameSession;
}
