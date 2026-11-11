export type BackendCallback = { consumerId: string; callbackUrl: string };

/** Parse a consumed public projection of deployment configuration, never credentials. */
export function parseBackendCallbacks(raw: string | undefined): BackendCallback[] {
  if (!raw) return [];
  const value: unknown = JSON.parse(raw);
  if (!Array.isArray(value)) throw new Error("backend_configuration_invalid");
  const callbacks: BackendCallback[] = [];
  for (const item of value) {
    if (typeof item !== "object" || item === null || !("consumer_id" in item) || !("callback_url" in item) ||
      typeof item.consumer_id !== "string" || !/^[a-z][a-z0-9-]{0,63}$/.test(item.consumer_id) ||
      typeof item.callback_url !== "string") throw new Error("backend_configuration_invalid");
    const url = new URL(item.callback_url);
    if ((url.protocol !== "https:" && !(url.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname))) ||
      url.username || url.password || url.search || url.hash || callbacks.some((entry) => entry.consumerId === item.consumer_id)) throw new Error("backend_configuration_invalid");
    callbacks.push({ consumerId: item.consumer_id, callbackUrl: url.href });
  }
  return callbacks;
}

export function parseBackendAuthorizationQuery(query: URLSearchParams): { consumerId: string; state: string; challenge: string } | null {
  const keys = ["consumer_id", "state", "code_challenge", "code_challenge_method"];
  if (Array.from(query.keys()).some((key) => !keys.includes(key)) || keys.some((key) => query.getAll(key).length !== 1) ||
    query.get("code_challenge_method") !== "S256" || !/^[a-z][a-z0-9-]{0,63}$/.test(query.get("consumer_id") ?? "") ||
    !/^[A-Za-z0-9_-]{43}$/.test(query.get("state") ?? "") || !/^[A-Za-z0-9_-]{43}$/.test(query.get("code_challenge") ?? "")) return null;
  return { consumerId: query.get("consumer_id")!, state: query.get("state")!, challenge: query.get("code_challenge")! };
}
