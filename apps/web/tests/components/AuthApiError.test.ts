import { describe, expect, it } from "vitest";
import {
  ApiError,
  apiErrorCode,
  authErrorMessage,
  passwordResetErrorMessage
} from "@/shared/api/auth";

const authFallback = "Не удалось выполнить авторизацию. Попробуйте ещё раз.";
const passwordResetFallback =
  "Не удалось выполнить восстановление пароля. Попробуйте ещё раз.";

function apiError(status: number, detail: unknown) {
  return new ApiError(status, detail, JSON.stringify({ detail }));
}

describe("API error classification", () => {
  it.each<[number, string, string]>([
    [409, "email_already_registered", "Аккаунт с таким email уже существует. Попробуйте войти."],
    [401, "invalid_credentials", "Неверный email или пароль."],
    [400, "missing_personal_consent", "Нужно дать согласие на обработку персональных данных."],
    [400, "missing_offer_consent", "Нужно принять условия оферты."]
  ])("maps auth status %s and code %s to the existing message", (status, code, message) => {
    expect(authErrorMessage(apiError(status, { code }))).toBe(message);
  });

  it("maps the password-reset token error and validation status", () => {
    expect(
      passwordResetErrorMessage(
        apiError(400, { code: "invalid_or_expired_reset_token" })
      )
    ).toBe("Ссылка недействительна или срок её действия истёк. Запросите новую ссылку.");
    expect(passwordResetErrorMessage(apiError(422, { code: "validation_error" }))).toBe(
      "Проверьте email и пароль. Пароль должен содержать не менее 8 символов."
    );
  });

  it("does not classify misleading Error.message text", () => {
    expect(
      authErrorMessage(new Error("401 409 email_already_registered invalid_credentials"))
    ).toBe(authFallback);
    expect(
      passwordResetErrorMessage(new Error("422 invalid_or_expired_reset_token"))
    ).toBe(passwordResetFallback);
  });

  it("does not classify wrong status and code combinations", () => {
    expect(authErrorMessage(apiError(401, { code: "email_already_registered" }))).toBe(
      authFallback
    );
    expect(
      passwordResetErrorMessage(apiError(409, { code: "invalid_or_expired_reset_token" }))
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
    expect(authErrorMessage(apiError(500, { code: "server_error" }))).toBe(authFallback);
    expect(passwordResetErrorMessage(apiError(429, { code: "rate_limited" }))).toBe(
      passwordResetFallback
    );
  });
});
