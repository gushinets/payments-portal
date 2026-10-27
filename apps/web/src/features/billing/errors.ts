import { ApiError, apiErrorCode } from "@/shared/api/transport";

export type BillingErrorKey = "session" | "verification" | "identity" | "pending" | "review" | "serverAuth" | "rejected" | "response" | "client" | "configuration" | "unavailable" | "sdk" | "termsChanged" | "purchaseConflict" | "notPrepared" | "consent" | "offer" | "financialPending";

export function newRequestId(): string {
  return Array.from(window.crypto.getRandomValues(new Uint8Array(16)), (value) => value.toString(16).padStart(2, "0")).join("");
}

export function safeRequestId(error: unknown): string {
  if (!(error instanceof ApiError) || typeof error.detail !== "object" || error.detail === null || !("request_id" in error.detail)) return "";
  const id = error.detail.request_id;
  return typeof id === "string" && /^[A-Za-z0-9._-]{1,128}$/.test(id) ? id : "";
}

export function billingErrorKey(error: unknown): BillingErrorKey {
  switch (apiErrorCode(error)) {
    case "billing_session_required": return "session";
    case "billing_email_verification_required": return "verification";
    case "billing_connection_conflict":
    case "billing_identity_conflict":
    case "billing_identity_unproven":
    case "billing_legacy_identity_unproven": return "identity";
    case "purchase_pending": return "financialPending";
    case "billing_customer_pending": return "pending";
    case "billing_customer_review": return "review";
    case "lbx_authentication_failed":
    case "billing_server_auth_failed": return "serverAuth";
    case "lbx_scope_forbidden":
    case "lbx_provider_rejected":
    case "billing_source_rejected": return "rejected";
    case "lbx_response_invalid":
    case "billing_source_invalid_response": return "response";
    case "billing_client_not_ready": return "client";
    case "terms_changed": return "termsChanged";
    case "lbx_scope_mismatch":
    case "purchase_inventory_incomplete":
    case "purchase_scope_released":
    case "purchase_review_required":
    case "purchase_existing_subscription_review":
    case "purchase_history_unproven":
    case "purchase_scope_occupied":
    case "purchase_idempotency_conflict":
    case "purchase_binding_conflict":
    case "purchase_connection_conflict": return "purchaseConflict";
    case "purchase_not_prepared": return "notPrepared";
    case "purchase_legal_unavailable":
    case "purchase_consent_unproven": return "consent";
    case "purchase_offer_unavailable": return "offer";
    case "purchase_billing_not_configured":
    case "lbx_not_configured":
    case "lbx_connection_fields_required":
    case "lbx_base_url_invalid":
    case "lbx_base_url_requires_public_https":
    case "lbx_server_credentials_invalid":
    case "lbx_widget_signing_secret_required": return "configuration";
    default: return error instanceof ApiError && error.status === 401 ? "session" : "unavailable";
  }
}
