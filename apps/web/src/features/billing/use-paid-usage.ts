"use client";

import { readPaidUsage } from "@/shared/api/paid-usage";
import type { OnBillingSessionRefused } from "./errors";
import { usePaidRead } from "./use-paid-read";

export function usePaidUsage(enabled: boolean, onSessionRefused: OnBillingSessionRefused) {
  return usePaidRead(enabled, readPaidUsage, onSessionRefused);
}
