export const sessionTokenStorageKey = "anytoolai_session_token_v1";

export function storeSessionToken(token: string) {
  window.localStorage.setItem(sessionTokenStorageKey, token);
}
