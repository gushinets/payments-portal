import {
  ApiContractError,
  ApiError,
  apiErrorCode
} from "@/shared/api/auth";

export type PasswordResetErrorMessageKey =
  | "errors.invalidOrExpiredToken"
  | "errors.rateLimited"
  | "errors.invalidInput"
  | "errors.internalServer"
  | "errors.contract"
  | "errors.network"
  | "errors.generic";

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

  if (error instanceof ApiContractError) {
    return "errors.contract";
  }

  if (
    error instanceof TypeError ||
    (error instanceof DOMException && error.name === "AbortError") ||
    (error instanceof Error && error.name === "AbortError")
  ) {
    return "errors.network";
  }

  return "errors.generic";
}
