"use client";

import type {
  EmailVerificationConfirmRequest,
  EmailVerificationConfirmResponse,
  EmailVerificationRequest,
  EmailVerificationRequestResponse,
  LoginRequest,
  LoginResponse,
  LogoutResponse,
  PasswordResetConfirmRequest,
  PasswordResetConfirmResponse,
  PasswordResetRequest,
  PasswordResetRequestResponse,
  RegisterRequest,
  RegisterResponse,
  SessionResponse
} from "@/generated/api-contracts/types.gen";
import { getJson, postJson } from "./transport";

export type AuthMode = "login" | "register";

export type AuthResponse = RegisterResponse | LoginResponse;

export type SubmitAuthValues = {
  mode: AuthMode;
  email: string;
  password: string;
  personalConsent: boolean;
  offerConsent: boolean;
};

export type SubmitAuthOptions = {
  languageTag: string;
};

export type PasswordResetRequestOptions = {
  languageTag: string;
};

// Preserve existing auth consumers while transport owns these shared error facts.
export {
  ApiContractError,
  ApiError,
  apiErrorCode,
  decodeApiErrorEnvelope,
  requestTimeoutMs,
  resolveApiBase
} from "./transport";
export type { ApiErrorDetail, ApiErrorEnvelope } from "./transport";

export const sessionStorageKey = "anytoolai_session_token_v1";
export const sessionChangedEvent = "anytoolai_session_changed";

export async function submitAuth(
  values: SubmitAuthValues,
  options: SubmitAuthOptions
): Promise<AuthResponse> {
  if (values.mode === "register") {
    const request: RegisterRequest = {
      email: values.email,
      password: values.password,
      personal_consent: values.personalConsent,
      offer_consent: values.offerConsent
    };
    return postJson<RegisterResponse>(
      "/api/auth/register",
      request,
      "RegisterResponse",
      undefined,
      { "Accept-Language": options.languageTag }
    );
  }

  const request: LoginRequest = {
    email: values.email,
    password: values.password
  };
  return postJson<LoginResponse>(
    "/api/auth/login",
    request,
    "LoginResponse"
  );
}

export async function getSession(
  sessionToken: string
): Promise<SessionResponse> {
  return getJson<SessionResponse>(
    "/api/auth/session",
    sessionToken,
    "SessionResponse"
  );
}

export async function logoutSession(
  sessionToken: string
): Promise<LogoutResponse> {
  return postJson<LogoutResponse>(
    "/api/auth/logout",
    {},
    "LogoutResponse",
    sessionToken
  );
}

export async function requestEmailVerification(
  sessionToken: string,
  languageTag: string
): Promise<EmailVerificationRequestResponse> {
  const request: EmailVerificationRequest = {};
  return postJson<EmailVerificationRequestResponse>(
    "/api/auth/email-verification/request",
    request,
    "EmailVerificationRequestResponse",
    sessionToken,
    { "Accept-Language": languageTag }
  );
}

export async function confirmEmailVerification(
  sessionToken: string,
  token: string
): Promise<EmailVerificationConfirmResponse> {
  const request: EmailVerificationConfirmRequest = { token };
  return postJson<EmailVerificationConfirmResponse>(
    "/api/auth/email-verification/confirm",
    request,
    "EmailVerificationConfirmResponse",
    sessionToken
  );
}

export async function requestPasswordReset(
  values: PasswordResetRequest,
  options: PasswordResetRequestOptions
): Promise<PasswordResetRequestResponse> {
  const request: PasswordResetRequest = { email: values.email };
  return postJson<PasswordResetRequestResponse>(
    "/api/auth/password-reset/request",
    request,
    "PasswordResetRequestResponse",
    undefined,
    { "Accept-Language": options.languageTag }
  );
}

export async function confirmPasswordReset(
  values: PasswordResetConfirmRequest
): Promise<PasswordResetConfirmResponse> {
  const request: PasswordResetConfirmRequest = {
    token: values.token,
    password: values.password
  };
  return postJson<PasswordResetConfirmResponse>(
    "/api/auth/password-reset/confirm",
    request,
    "PasswordResetConfirmResponse"
  );
}
