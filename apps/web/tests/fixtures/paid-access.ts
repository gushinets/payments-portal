import type { PaidAccessResponse } from "@/generated/api-contracts/types.gen";

export function paidState(overrides: Partial<PaidAccessResponse> = {}): PaidAccessResponse {
  return {
    access_revision: 1,
    grants: [{ product_id: "proposal_ai", valid_until: null }],
    allowances: [{ allowance_id: "77777777-7777-4777-8777-777777777777", product_id: "proposal_ai", metric_key: "proposal_ai.test_generations", unit: "generation", quantity: 100, provenance: "SIMULATED" }],
    products: [{ product_id: "proposal_ai", status: "confirmed", observed_at: new Date().toISOString(), effective_until: null }],
    committed_at: new Date().toISOString(), read_at: new Date().toISOString(),
    effective_until: new Date(Date.now() + 6 * 60 * 60 * 1000).toISOString(), evidence_complete: true,
    ...overrides
  };
}

export function emptyPaidState(): PaidAccessResponse {
  return paidState({
    access_revision: 0, grants: [], allowances: [], products: [],
    committed_at: null, effective_until: null
  });
}
