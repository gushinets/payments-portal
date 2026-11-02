// Synthetic Portal wire responses. No provider objects or credentials are used.
import type { PurchaseIntentResponse, PurchaseReviewResponse, SessionUserResponse, WidgetBootstrapResponse } from "../../src/generated/api-contracts/types.gen";

export const purchaseUser: SessionUserResponse = {
  tenant_id: "anytoolai", region: "ru", user_id: "11111111-1111-4111-8111-111111111111",
  email: "synthetic@example.com", email_verified: true
};
export const purchaseReview: PurchaseReviewResponse = {
  product_id: "proposal_ai", revision_id: "22222222-2222-4222-8222-222222222222",
  expected_fingerprint: "sha256:" + "a".repeat(64), legal_status: "draft",
  terms: { recurring_unit_amount: "100", recurring_amount: "100", connection_unit_amount: "0", connection_amount: "0", currency: "RUB", decimal_places: 2, units: "major", commercial_quantity: "1", period_unit: "month", period_length: 1, period_anchor: "instance_start", prepaid: true, full_funding_required: true },
  documents: [{ document_version_id: "33333333-3333-4333-8333-333333333333", acceptance_text_hash: "b".repeat(64), doc_type: "offer", version: "synthetic-v1", content_hash: "c".repeat(64), title: "Тестовый проект оферты", url_path: "/ru/offer", acceptance_text: "Я принимаю тестовые условия оферты." }]
};
export const savedPurchase: PurchaseIntentResponse = {
  purchase_intent_id: "44444444-4444-4444-8444-444444444444", product_id: "proposal_ai",
  state: "linked", reason: null, scope_held: true, accepted: purchaseReview, paid_access_granted: false
};
export function widgetResponse(payment = false): WidgetBootstrapResponse {
  return {
    presentation: payment ? "payment" : "account", credential: "synthetic-widget-token",
    widget_origin: "https://billing.test", sdk_url: "https://billing.test/lbxwidget.js", serviceBaseUrl: "https://billing.test/api/rest/v1/client",
    disableCreateSubscription: true, disableEditSubscription: true, disableStopSubscription: true, disableAutopayments: true, disablePayments: !payment, disableInvoiceGeneration: true,
    request_id: "synthetic-request", payment_target: payment ? { purchase_intent_id: savedPurchase.purchase_intent_id, agreement_reference: "synthetic-agreement", seller_reference: "synthetic-seller" } : null
  };
}
