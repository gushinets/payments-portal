import type { PurchaseIntentState } from "@/generated/api-contracts/types.gen";

export function isResolvedPurchase(state: PurchaseIntentState): boolean {
  return state === "resolved_no_external_effect" || state === "resolved_external_terminal" || state === "failed_before_external_effect";
}
