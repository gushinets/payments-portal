// Explicitly simulated HTTP response, never a runtime catalog or approval.
import type { CatalogProductResponse } from "../../src/generated/api-contracts/types.gen";

export const simulatedProduct: CatalogProductResponse = {
  product_id: "proposal_ai",
  evidence_mode: "SIMULATED",
  availability: "SIMULATED_PREVIEW",
  offer: {
    offer_id: "11111111-1111-4111-8111-111111111111",
    revision_id: "22222222-2222-4222-8222-222222222222",
    revision_number: 1,
    evidence_mode: "SIMULATED",
    publication_state: "SIMULATED",
    money: {
      recurring_amount: "9007199254740993.01",
      connection_amount: "7.03",
      currency: "RUB",
      decimal_places: 2,
      units: "major"
    },
    period: { unit: "month", length: 1, anchor: "instance_start" },
    allowance: { quantity: "25", metric_key: "proposal_ai.test_generations", unit: "generation" },
    terms: {
      prepaid: true,
      full_funding_required: true,
      tax_treatment: "included",
      discounts: "none",
      proration: "none",
      connection_charge_basis: "per_service_unit"
    }
  }
};
