import { ApiError, apiErrorCode } from "@/shared/api/auth";
import {
  transportErrorMessageKey,
  type TransportErrorMessageKey
} from "./transport-error";

export type AuthErrorMessageKey =
  | "errors.emailAlreadyRegistered"
  | "errors.invalidCredentials"
  | "errors.missingPersonalConsent"
  | "errors.missingOfferConsent"
  | "errors.passwordPolicyNotMet"
  | "errors.internalServer"
  | TransportErrorMessageKey;

export function authErrorMessageKey(error: unknown): AuthErrorMessageKey {
  const code = apiErrorCode(error);

  if (error instanceof ApiError) {
    if (error.status === 409 && code === "email_already_registered") {
      return "errors.emailAlreadyRegistered";
    }
    if (error.status === 401 && code === "invalid_credentials") {
      return "errors.invalidCredentials";
    }
    if (error.status === 400 && code === "missing_personal_consent") {
      return "errors.missingPersonalConsent";
    }
    if (error.status === 400 && code === "missing_offer_consent") {
      return "errors.missingOfferConsent";
    }
    if (error.status === 400 && code === "password_policy_not_met") {
      return "errors.passwordPolicyNotMet";
    }
    if (error.status === 500 && code === "internal_server_error") {
      return "errors.internalServer";
    }
  }

  return transportErrorMessageKey(error);
}
