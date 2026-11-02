// Explicitly simulated HTTP response, never a runtime catalog or approval.
import type { CatalogProductResponse } from "../../src/generated/api-contracts/types.gen";

export const simulatedProduct: CatalogProductResponse = {
  product_id: "proposal_ai",
  kernel_provenance: "SIMULATED",
  availability: "CURRENT_OFFER",
  availability_reason: null,
  offer: {
    revision_id: "22222222-2222-4222-8222-222222222222",
    revision_number: 1,
    billing_provenance: "CONFIGURED_SOURCE",
    money: {
      recurring_amount: "9007199254740993.01",
      connection_amount: "7.03",
      currency: "RUB",
      decimal_places: 2,
      units: "major"
    },
    period: { unit: "month", length: 1, anchor: "instance_start" },
    commercial_quantity: "1",
    prepaid: true,
    full_funding_required: true
  }
};
