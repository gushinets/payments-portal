import { describe, expect, it } from "vitest";
import {
  ApiError,
  apiErrorCode,
  passwordResetErrorMessage
} from "@/shared/api/auth";

const passwordResetFallback =
  "Не удалось выполнить восстановление пароля. Попробуйте ещё раз.";

function apiError(status: number, detail: unknown) {
  return new ApiError(status, detail, JSON.stringify({ detail }));
}

describe("API error classification", () => {
  it("keeps status and structured code as language-neutral transport facts", () => {
    const error = apiError(409, { code: "email_already_registered" });

    expect(error.status).toBe(409);
    expect(apiErrorCode(error)).toBe("email_already_registered");
  });

  it("maps the password-reset token error and validation status", () => {
    expect(
      passwordResetErrorMessage(
        apiError(400, { code: "invalid_or_expired_reset_token" })
      )
    ).toBe(
      "Ссылка недействительна или срок её действия истёк. Запросите новую ссылку."
    );
    expect(
      passwordResetErrorMessage(apiError(422, { code: "validation_error" }))
    ).toBe(
      "Проверьте email и пароль. Пароль должен содержать не менее 8 символов."
    );
  });

  it("does not classify misleading Error.message text", () => {
    expect(
      passwordResetErrorMessage(new Error("422 invalid_or_expired_reset_token"))
    ).toBe(passwordResetFallback);
  });

  it("does not classify wrong status and code combinations", () => {
    expect(
      passwordResetErrorMessage(
        apiError(409, { code: "invalid_or_expired_reset_token" })
      )
    ).toBe(passwordResetFallback);
  });

  it.each([
    new Error("known_code"),
    apiError(400, "known_code"),
    apiError(400, null),
    apiError(400, []),
    apiError(400, { code: 123 })
  ])("returns null unless detail.code is structured and string-valued", (error) => {
    expect(apiErrorCode(error)).toBeNull();
  });

  it("keeps the default fallbacks", () => {
    expect(
      passwordResetErrorMessage(apiError(429, { code: "rate_limited" }))
    ).toBe(passwordResetFallback);
  });
});
