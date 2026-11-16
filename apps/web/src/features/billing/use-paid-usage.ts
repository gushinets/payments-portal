"use client";

import { readPaidUsage } from "@/shared/api/paid-usage";
import { usePaidRead } from "./use-paid-read";

export function usePaidUsage(enabled: boolean) {
  return usePaidRead(enabled, readPaidUsage);
}
