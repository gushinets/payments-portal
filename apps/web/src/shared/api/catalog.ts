"use client";

import type {
  CatalogProductResponse,
  CatalogProductsResponse
} from "@/generated/api-contracts/types.gen";
import { getJson } from "./transport";

export function getCatalogProducts(): Promise<CatalogProductsResponse> {
  return getJson<CatalogProductsResponse>(
    "/api/catalog/products", undefined, "CatalogProductsResponse"
  );
}

export function getCatalogProduct(productId: string): Promise<CatalogProductResponse> {
  return getJson<CatalogProductResponse>(
    `/api/catalog/products/${encodeURIComponent(productId)}`,
    undefined,
    "CatalogProductResponse"
  );
}
