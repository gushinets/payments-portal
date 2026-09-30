import { ApiError, apiErrorCode } from "@/shared/api/auth";
import {
  transportErrorMessageKey,
  type TransportErrorMessageKey
} from "@/shared/ui/transport-error";

export type PasswordResetErrorMessageKey =
  | "errors.invalidOrExpiredToken"
  | "errors.rateLimited"
  | "errors.invalidInput"
  | "errors.internalServer"
  | TransportErrorMessageKey;

export function passwordResetErrorMessageKey(
  error: unknown
): PasswordResetErrorMessageKey {
  const code = apiErrorCode(error);

  if (error instanceof ApiError) {
    if (error.status === 400 && code === "invalid_or_expired_reset_token") {
      return "errors.invalidOrExpiredToken";
    }
    if (error.status === 429 && code === "password_reset_rate_limited") {
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
