import { ApiContractError } from "@/shared/api/auth";

export type TransportErrorMessageKey =
  | "errors.contract"
  | "errors.network"
  | "errors.generic";

export function transportErrorMessageKey(
  error: unknown
): TransportErrorMessageKey {
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
