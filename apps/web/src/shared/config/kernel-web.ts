const launchProducts = new Set(["proposal_ai", "client_update_writer", "brief_decoder", "acceptance_builder"]);

/** A configured web host, distinct from the server-only Kernel API/service credential. */
export function kernelWebBaseUrl(configured = process.env.NEXT_PUBLIC_KERNEL_WEB_BASE_URL): string | null {
  if (!configured) return null;
  try {
    const url = new URL(configured);
    if ((url.protocol !== "https:" && !(url.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname))) ||
      url.username || url.password || url.search || url.hash) return null;
    return url.href.replace(/\/$/, "");
  } catch { return null; }
}

export function kernelLaunchUrl(productId: string): string | null {
  const base = kernelWebBaseUrl();
  return base && launchProducts.has(productId)
    ? `${base}/portal-session/launch?return_to=${encodeURIComponent(`/products/${productId}`)}` : null;
}

export function parseKernelAuthorizationQuery(query: URLSearchParams): { state: string; challenge: string } | null {
  if (query.getAll("state").length !== 1 || query.getAll("code_challenge").length !== 1 ||
    query.getAll("code_challenge_method").length !== 1 || query.get("code_challenge_method") !== "S256" ||
    !/^[A-Za-z0-9_-]{43}$/.test(query.get("state") ?? "") ||
    !/^[A-Za-z0-9_-]{43}$/.test(query.get("code_challenge") ?? "")) return null;
  return { state: query.get("state")!, challenge: query.get("code_challenge")! };
}
