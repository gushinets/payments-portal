import { describe, expect, it } from "vitest";

import { isAbortedNextPrefetch } from "../helpers/request-failures";

const pageUrl = "http://localhost:39053/ru/products";
const prefetch: Parameters<typeof isAbortedNextPrefetch>[0] = {
  url: () => "http://localhost:39053/ru/products/proposal_ai?_rsc=test",
  method: () => "GET",
  resourceType: () => "fetch",
  headers: () => ({ rsc: "1", "next-router-prefetch": "1" }),
  failure: () => ({ errorText: "net::ERR_ABORTED" })
};

const unexpectedFailures: {
  name: string;
  changes: Partial<typeof prefetch>;
}[] = [
  { name: "foreground RSC navigation", changes: { headers: () => ({ rsc: "1" }) } },
  { name: "ordinary fetch", changes: { headers: () => ({}) } },
  { name: "non-RSC prefetch", changes: { headers: () => ({ "next-router-prefetch": "1" }) } },
  { name: "request without RSC query", changes: { url: () => "http://localhost:39053/ru/products/proposal_ai" } },
  { name: "API read", changes: { url: () => "http://localhost:39053/api/catalog/products?_rsc=test" } },
  { name: "API root", changes: { url: () => "http://localhost:39053/api?_rsc=test" } },
  { name: "another origin", changes: { url: () => "https://other.example/ru/products/proposal_ai?_rsc=test" } },
  { name: "document navigation", changes: { resourceType: () => "document" } },
  { name: "script load", changes: { resourceType: () => "script" } },
  { name: "POST", changes: { method: () => "POST" } },
  { name: "connection failure", changes: { failure: () => ({ errorText: "net::ERR_CONNECTION_REFUSED" }) } },
  { name: "timeout", changes: { failure: () => ({ errorText: "net::ERR_TIMED_OUT" }) } },
  { name: "successful request", changes: { failure: () => null } }
];

describe("public-route request failure classification", () => {
  it("recognizes an explicitly marked, same-origin Next prefetch cancellation", () => {
    expect(isAbortedNextPrefetch(prefetch, pageUrl)).toBe(true);
  });

  it.each(unexpectedFailures)("preserves $name in the failure list", ({ changes }) => {
    expect(isAbortedNextPrefetch({ ...prefetch, ...changes }, pageUrl)).toBe(false);
  });
});
