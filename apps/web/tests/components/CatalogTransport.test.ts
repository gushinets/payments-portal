import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getCatalogProduct, getCatalogProducts } from "@/shared/api/catalog";
import { getSession } from "@/shared/api/auth";
import { ApiContractError, ApiError } from "@/shared/api/transport";
import { simulatedProduct } from "../fixtures/catalog";

const reportApiContractError = vi.hoisted(() => vi.fn());
vi.mock("@/shared/observability/sentry", () => ({ reportApiContractError }));

const fetchMock = vi.fn<typeof fetch>();

describe("anonymous catalog through the shared transport", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    reportApiContractError.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("omits Authorization on list/detail and encodes opaque product IDs", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ products: [simulatedProduct] }))
      .mockResolvedValueOnce(Response.json(simulatedProduct));
    await expect(getCatalogProducts()).resolves.toEqual({ products: [simulatedProduct] });
    await expect(getCatalogProduct("opaque/id ?#")).resolves.toEqual(simulatedProduct);
    expect(fetchMock.mock.calls[1][0]).toEqual(expect.stringContaining("/products/opaque%2Fid%20%3F%23"));
    for (const [, options] of fetchMock.mock.calls) {
      expect(new Headers(options?.headers).has("Authorization")).toBe(false);
    }
  });

  it("preserves authenticated GET headers", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ authenticated: true, user: {} }));
    await getSession("existing-session-token");
    expect(fetchMock.mock.calls[0][1]?.headers).toEqual({ Authorization: "Bearer existing-session-token" });
  });

  it("retains malformed successful JSON reporting and its stable error", async () => {
    fetchMock.mockResolvedValueOnce(new Response("not JSON", { status: 200 }));
    await expect(getCatalogProducts()).rejects.toBeInstanceOf(ApiContractError);
    expect(reportApiContractError).toHaveBeenCalledWith(expect.any(ApiContractError), {
      route: "/api/catalog/products", contract: "CatalogProductsResponse"
    });
  });

  it("preserves unknown-product and database failure facts", async () => {
    fetchMock.mockResolvedValueOnce(Response.json({ detail: { code: "catalog_product_not_found" } }, { status: 404 }))
      .mockResolvedValueOnce(Response.json({ detail: { code: "internal_server_error" } }, { status: 500 }));
    await expect(getCatalogProduct("unknown")).rejects.toMatchObject({ status: 404 });
    await expect(getCatalogProducts()).rejects.toBeInstanceOf(ApiError);
    expect(reportApiContractError).not.toHaveBeenCalled();
  });
});
