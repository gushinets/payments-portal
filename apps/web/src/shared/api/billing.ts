"use client";

import type { WidgetBootstrapRequest, WidgetBootstrapResponse } from "@/generated/api-contracts/types.gen";
import { billingRequestTimeoutMs } from "./billing-policy";
import { postJson } from "./transport";

export function bootstrapWidget(token: string, requestId: string, purchaseIntentId?: string): Promise<WidgetBootstrapResponse> {
  const request: WidgetBootstrapRequest = purchaseIntentId ? { purchase_intent_id: purchaseIntentId } : {};
  return postJson<WidgetBootstrapResponse>(
    "/api/billing/widget-bootstrap", request, "WidgetBootstrapResponse", token,
    { "X-Request-ID": requestId }, billingRequestTimeoutMs
  );
}
