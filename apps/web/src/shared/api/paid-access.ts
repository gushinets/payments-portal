"use client";

import type { PaidAccessResponse } from "@/generated/api-contracts/types.gen";
import { getJson } from "./transport";

export function readPaidAccess(token: string, requestId: string) {
  return getJson<PaidAccessResponse>("/api/paid-access", token, "PaidAccessResponse", { "X-Request-ID": requestId });
}
