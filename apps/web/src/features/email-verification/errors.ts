import { ApiError, apiErrorCode } from "@/shared/api/auth";
import {
  transportErrorMessageKey,
  type TransportErrorMessageKey
} from "@/shared/ui/transport-error";

export type EmailVerificationErrorMessageKey =
  | "errors.invalidOrExpiredToken"
  | "errors.invalidCredentials"
  | "errors.rateLimited"
  | "errors.invalidInput"
  | "errors.internalServer"
  | TransportErrorMessageKey;

export function isInvalidVerificationTokenError(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === 400 &&
    apiErrorCode(error) === "invalid_or_expired_verification_token"
  );
}

export function emailVerificationErrorMessageKey(
  error: unknown
): EmailVerificationErrorMessageKey {
  const code = apiErrorCode(error);

  if (error instanceof ApiError) {
    if (
      error.status === 400 &&
      code === "invalid_or_expired_verification_token"
    ) {
      return "errors.invalidOrExpiredToken";
    }
    if (error.status === 401 && code === "invalid_credentials") {
      return "errors.invalidCredentials";
    }
    if (error.status === 429 && code === "authentication_rate_limited") {
      return "errors.rateLimited";
    }
    if (error.status === 422) {
      return "errors.invalidInput";
    }
    if (error.status === 500 && code === "internal_server_error") {
      return "errors.internalServer";
    }
  }

  return transportErrorMessageKey(error);
}
