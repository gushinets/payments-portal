import type { Request } from "@playwright/test";

type ObservedRequest = Pick<Request, "url" | "method" | "resourceType" | "headers" | "failure">;

export function isAbortedNextPrefetch(request: ObservedRequest, pageUrl: string): boolean {
  if (
    request.failure()?.errorText !== "net::ERR_ABORTED" ||
    request.method() !== "GET" ||
    request.resourceType() !== "fetch"
  ) {
    return false;
  }

  const url = new URL(request.url());
  const headers = request.headers();
  // Next may cancel speculative RSC reads. An aborted foreground navigation,
  // API call or resource load still belongs in the smoke test's failure list.
  return (
    url.origin === new URL(pageUrl).origin &&
    url.pathname !== "/api" &&
    !url.pathname.startsWith("/api/") &&
    url.searchParams.has("_rsc") &&
    headers.rsc === "1" &&
    headers["next-router-prefetch"] === "1"
  );
}
