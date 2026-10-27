"use client";

import type {
  CurrentPurchaseResponse,
  PurchaseConfirmRequest,
  PurchaseIntentResponse,
  PurchaseReviewRequest,
  PurchaseReviewResponse
} from "@/generated/api-contracts/types.gen";
import { getJson, postJson } from "./transport";
import { billingRequestTimeoutMs } from "./billing-policy";

export function reviewPurchase(token: string, productId: string, requestId: string) {
  const request: PurchaseReviewRequest = { product_id: productId };
  return postJson<PurchaseReviewResponse>("/api/purchases/review", request, "PurchaseReviewResponse", token, { "X-Request-ID": requestId }, billingRequestTimeoutMs);
}

export function confirmPurchase(token: string, request: PurchaseConfirmRequest, key: string, requestId: string) {
  return postJson<PurchaseIntentResponse>("/api/purchase-intents", request, "PurchaseIntentResponse", token, {
    "Idempotency-Key": key, "X-Request-ID": requestId
  }, billingRequestTimeoutMs);
}

export function currentPurchase(token: string, productId: string, requestId: string) {
  return getJson<CurrentPurchaseResponse>(`/api/purchase-intents/current?product_id=${encodeURIComponent(productId)}`, token, "CurrentPurchaseResponse", { "X-Request-ID": requestId });
}

export function purchaseStatus(token: string, purchaseId: string, requestId: string) {
  return getJson<PurchaseIntentResponse>(`/api/purchase-intents/${encodeURIComponent(purchaseId)}`, token, "PurchaseIntentResponse", { "X-Request-ID": requestId });
}

export function advancePurchase(token: string, purchaseId: string, requestId: string) {
  return postJson<PurchaseIntentResponse>(`/api/purchase-intents/${encodeURIComponent(purchaseId)}/advance`, {}, "PurchaseIntentResponse", token, { "X-Request-ID": requestId }, billingRequestTimeoutMs);
}
