"use client";

import type { PaidUsageResponse } from "@/generated/api-contracts/types.gen";
import { getJson } from "./transport";

export function readPaidUsage(token: string, requestId: string) {
  return getJson<PaidUsageResponse>("/api/paid-usage", token, "PaidUsageResponse", { "X-Request-ID": requestId });
}
