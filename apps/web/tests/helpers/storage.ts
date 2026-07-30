export const sessionTokenStorageKey = "anytoolai_session_token_v1";
export const paymentResultStorageKey = "anytoolai_last_payment_result";

export function storeSessionToken(token: string) {
  window.localStorage.setItem(sessionTokenStorageKey, token);
}

export function readStoredPaymentResult() {
  const raw = window.sessionStorage.getItem(paymentResultStorageKey);
  return raw ? (JSON.parse(raw) as Record<string, unknown>) : null;
}
