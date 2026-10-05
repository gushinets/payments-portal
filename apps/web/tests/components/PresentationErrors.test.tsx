import { screen } from "@testing-library/react";
import { useTranslations } from "next-intl";
import { describe, expect, it } from "vitest";

import { emailVerificationErrorMessageKey } from "@/features/email-verification";
import { passwordResetErrorMessageKey } from "@/features/password-reset";
import enMessages from "@/messages/en.json";
import { ApiContractError, ApiError } from "@/shared/api/auth";
import { authErrorMessageKey } from "@/shared/ui/auth-errors";
import { transportErrorMessageKey } from "@/shared/ui/transport-error";
import { renderWithIntl } from "../setup/render-with-intl";

function apiError(status: number, detail: unknown) {
  return new ApiError(status, detail);
}

function AuthErrorText({ error }: { error: unknown }) {
  const t = useTranslations("Auth");
  return <p>{t(authErrorMessageKey(error))}</p>;
}

function PasswordResetErrorText({ error }: { error: unknown }) {
  const t = useTranslations("PasswordReset");
  return <p>{t(passwordResetErrorMessageKey(error))}</p>;
}

describe("shared transport Presentation error classification", () => {
  it.each([
    [new ApiContractError(), "errors.contract"],
    [new TypeError("network unavailable"), "errors.network"],
    [new DOMException("request timed out", "AbortError"), "errors.network"],
    [new Error("unknown failure"), "errors.generic"]
  ] as const)("maps a transport failure", (error, expectedKey) => {
    expect(transportErrorMessageKey(error)).toBe(expectedKey);
  });
});

describe("auth Presentation error classification", () => {
  it.each([
    [409, "email_already_registered", "errors.emailAlreadyRegistered"],
    [401, "invalid_credentials", "errors.invalidCredentials"],
    [400, "missing_personal_consent", "errors.missingPersonalConsent"],
    [400, "missing_offer_consent", "errors.missingOfferConsent"],
    [400, "password_policy_not_met", "errors.passwordPolicyNotMet"],
    [500, "internal_server_error", "errors.internalServer"]
  ] as const)("maps status %s and code %s", (status, code, expectedKey) => {
    expect(authErrorMessageKey(apiError(status, { code }))).toBe(expectedKey);
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

  it("resolves an uncommon contract failure through real Auth messages", () => {
    renderWithIntl(<AuthErrorText error={new ApiContractError()} />, {
      locale: "en",
      messages: { Auth: enMessages.Auth }
    });

    expect(
      screen.getByText("The service returned an unexpected response. Try again.")
    ).toBeVisible();
    expect(screen.queryByText("errors.contract")).not.toBeInTheDocument();
  });
});

describe("password-reset Presentation error classification", () => {
  it.each([
    [400, "invalid_or_expired_reset_token", "errors.invalidOrExpiredToken"],
    [429, "password_reset_rate_limited", "errors.rateLimited"],
    [400, "password_policy_not_met", "errors.passwordPolicyNotMet"],
    [422, "validation_error", "errors.invalidInput"],
    [500, "internal_server_error", "errors.internalServer"]
  ] as const)("maps status %s and code %s", (status, code, expectedKey) => {
    expect(passwordResetErrorMessageKey(apiError(status, { code }))).toBe(
      expectedKey
    );
  });

  it("uses the generic key for unknown failures and wrong fact combinations", () => {
    expect(
      passwordResetErrorMessageKey(
        new Error("422 invalid_or_expired_reset_token")
      )
    ).toBe("errors.generic");
    expect(
      passwordResetErrorMessageKey(
        apiError(409, { code: "invalid_or_expired_reset_token" })
      )
    ).toBe("errors.generic");
    expect(
      passwordResetErrorMessageKey(
        apiError(429, { code: "rate_limited" })
      )
    ).toBe("errors.generic");
    expect(
      passwordResetErrorMessageKey(apiError(500, { code: "server_error" }))
    ).toBe("errors.generic");
  });

  it("resolves rate limiting through real PasswordReset messages", () => {
    renderWithIntl(
      <PasswordResetErrorText
        error={apiError(429, { code: "password_reset_rate_limited" })}
      />,
      {
        locale: "en",
        messages: { PasswordReset: enMessages.PasswordReset }
      }
    );

    expect(
      screen.getByText("Too many password recovery attempts. Try again later.")
    ).toBeVisible();
    expect(screen.queryByText("errors.rateLimited")).not.toBeInTheDocument();
  });
});

describe("email-verification Presentation error classification", () => {
  it.each([
    [
      400,
      "invalid_or_expired_verification_token",
      "errors.invalidOrExpiredToken"
    ],
    [401, "invalid_session", "errors.signInRequired"],
    [500, "internal_server_error", "errors.internalServer"]
  ] as const)("maps status %s and code %s", (status, code, expectedKey) => {
    expect(
      emailVerificationErrorMessageKey(apiError(status, { code }))
    ).toBe(expectedKey);
  });

  it("keeps wrong status/code combinations generic", () => {
    expect(
      emailVerificationErrorMessageKey(
        apiError(409, { code: "invalid_or_expired_verification_token" })
      )
    ).toBe("errors.generic");
  });
});
