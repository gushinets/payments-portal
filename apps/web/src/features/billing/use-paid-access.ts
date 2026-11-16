"use client";

import type { PaidAccessResponse } from "@/generated/api-contracts/types.gen";
import { readPaidAccess } from "@/shared/api/paid-access";
import { paidReadRefreshMs, usePaidRead } from "./use-paid-read";

export const paidAccessRefreshMs = paidReadRefreshMs;
const expiry = (data: PaidAccessResponse, started: number) => data.effective_until
  ? started + Date.parse(data.effective_until) - Date.parse(data.read_at) : null;

export function usePaidAccess(enabled: boolean) {
  return usePaidRead(enabled, readPaidAccess, expiry);
}
