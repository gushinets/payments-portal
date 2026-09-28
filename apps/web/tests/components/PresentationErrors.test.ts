import { describe, expect, it } from "vitest";

import { ApiContractError, ApiError } from "@/shared/api/auth";
import { authErrorMessageKey } from "@/shared/ui/auth-errors";

function apiError(status: number, detail: unknown) {
  return new ApiError(status, detail, JSON.stringify({ detail }));
}

describe("auth Presentation error classification", () => {
  it.each([
    [409, "email_already_registered", "errors.emailAlreadyRegistered"],
    [401, "invalid_credentials", "errors.invalidCredentials"],
    [400, "missing_personal_consent", "errors.missingPersonalConsent"],
    [400, "missing_offer_consent", "errors.missingOfferConsent"],
    [500, "internal_server_error", "errors.internalServer"]
  ] as const)("maps status %s and code %s", (status, code, expectedKey) => {
    expect(authErrorMessageKey(apiError(status, { code }))).toBe(expectedKey);
  });

  it("classifies contract, network, and timeout failures", () => {
    expect(authErrorMessageKey(new ApiContractError())).toBe(
      "errors.contract"
    );
    expect(authErrorMessageKey(new TypeError("network unavailable"))).toBe(
      "errors.network"
    );
    expect(
      authErrorMessageKey(new DOMException("request timed out", "AbortError"))
    ).toBe("errors.network");
  });

  it("uses the generic key for unknown failures and wrong fact combinations", () => {
    expect(
      authErrorMessageKey(
        new Error("401 email_already_registered internal_server_error")
      )
    ).toBe("errors.generic");
    expect(
      authErrorMessageKey(
        apiError(401, { code: "email_already_registered" })
      )
    ).toBe("errors.generic");
    expect(authErrorMessageKey(apiError(500, { code: "server_error" }))).toBe(
      "errors.generic"
    );
  });
});
