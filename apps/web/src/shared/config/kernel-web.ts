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
