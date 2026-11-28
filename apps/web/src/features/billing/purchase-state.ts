import type { PurchaseIntentState } from "@/generated/api-contracts/types.gen";

const resolvedByState = {
  created: false,
  preparing: false,
  awaiting_external_result: false,
  linked: false,
  resolved_no_external_effect: true,
  resolved_external_terminal: true,
  failed_before_external_effect: true,
  manual_review: false,
} satisfies Record<PurchaseIntentState, boolean>;

export function isResolvedPurchase(state: PurchaseIntentState): boolean {
  return resolvedByState[state];
}
