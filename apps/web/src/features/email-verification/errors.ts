import { ApiError, apiErrorCode } from "@/shared/api/auth";
import {
  transportErrorMessageKey,
  type TransportErrorMessageKey
} from "@/shared/ui/transport-error";

export type EmailVerificationErrorMessageKey =
  | "errors.invalidOrExpiredToken"
  | "errors.signInRequired"
  | "errors.internalServer"
  | TransportErrorMessageKey;

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
    if (error.status === 401) {
      return "errors.signInRequired";
    }
    if (error.status === 500 && code === "internal_server_error") {
      return "errors.internalServer";
    }
  }

  return transportErrorMessageKey(error);
}
