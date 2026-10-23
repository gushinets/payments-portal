"use client";

import type {
  ProductPurchaseStatusResponse,
  PurchaseRequest,
  PurchaseResponse,
  PurchaseReviewResponse,
  WidgetBootstrapRequest,
  WidgetBootstrapResponse
} from "@/generated/api-contracts/types.gen";
import { getJson, postJson } from "./transport";

export function getPurchaseReview(productId: string, token: string) {
  return getJson<PurchaseReviewResponse>(
    `/api/purchases/review/${encodeURIComponent(productId)}`,
    token,
    "PurchaseReviewResponse"
  );
}

export function getProductPurchaseStatus(productId: string, token: string) {
  return getJson<ProductPurchaseStatusResponse>(
    `/api/billing/products/${encodeURIComponent(productId)}/status`,
    token,
    "ProductPurchaseStatusResponse"
  );
}

export function getPurchase(intentId: string, token: string) {
  return getJson<PurchaseResponse>(
    `/api/purchases/${encodeURIComponent(intentId)}`,
    token,
    "PurchaseResponse"
  );
}

export function createPurchase(
  payload: PurchaseRequest,
  key: string,
  token: string
) {
  return postJson<PurchaseResponse>(
    "/api/purchases",
    payload,
    "PurchaseResponse",
    token,
    { "Idempotency-Key": key }
  );
}

export function continuePurchase(intentId: string, token: string) {
  return postJson<PurchaseResponse>(
    `/api/purchases/${encodeURIComponent(intentId)}/continue`,
    {},
    "PurchaseResponse",
    token
  );
}

export function bootstrapWidget(
  payload: WidgetBootstrapRequest,
  token: string
) {
  return postJson<WidgetBootstrapResponse>(
    "/api/billing/widget-bootstrap",
    payload,
    "WidgetBootstrapResponse",
    token
  );
}
