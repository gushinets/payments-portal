"use client";

import type { WidgetBootstrapRequest, WidgetBootstrapResponse } from "@/generated/api-contracts/types.gen";
import { postJson } from "./transport";

export function bootstrapWidget(token: string, requestId: string): Promise<WidgetBootstrapResponse> {
  const request: WidgetBootstrapRequest = {};
  return postJson<WidgetBootstrapResponse>(
    "/api/billing/widget-bootstrap", request, "WidgetBootstrapResponse", token,
    { "X-Request-ID": requestId }
  );
}
