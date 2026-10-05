"use client";

import {
  zEmailVerificationConfirmResponse,
  zEmailVerificationRequestResponse,
  zLoginResponse,
  zLogoutResponse,
  zPasswordResetConfirmResponse,
  zPasswordResetRequestResponse,
  zRegisterResponse,
  zSessionResponse,
  type EmailVerificationConfirmRequest,
  type EmailVerificationConfirmResponse,
  type EmailVerificationRequest,
  type EmailVerificationRequestResponse,
  type LoginRequest,
  type LoginResponse,
  type LogoutResponse,
  type PasswordResetConfirmRequest,
  type PasswordResetConfirmResponse,
  type PasswordResetRequest,
  type PasswordResetRequestResponse,
  type RegisterRequest,
  type RegisterResponse,
  type SessionResponse
} from "@/generated/api-contracts/zod.gen";
import { reportApiContractError } from "@/shared/observability/sentry";

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

export type ApiErrorDetail = unknown;

export type ApiErrorEnvelope = {
  detail: ApiErrorDetail;
};

export class ApiError extends Error {
  status: number;
  detail: ApiErrorDetail;

  constructor(status: number, detail: ApiErrorDetail, rawBody: string) {
    super(`${status}:${rawBody}`);
    this.status = status;
    this.detail = detail;
  }
}

export class ApiContractError extends Error {
  constructor() {
    super("invalid_api_response");
    this.name = "ApiContractError";
  }
}

export function apiErrorCode(error: unknown): string | null {
  if (!(error instanceof ApiError) || !isRecord(error.detail)) {
    return null;
  }

  return typeof error.detail.code === "string" ? error.detail.code : null;
}

export const sessionStorageKey = "anytoolai_session_token_v1";
export const sessionChangedEvent = "anytoolai_session_changed";

const configuredApiBase =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
export const requestTimeoutMs = 5000;

type JsonSchema<T> = {
  safeParse: (payload: unknown) =>
    | { success: true; data: T }
    | { success: false };
};

export function resolveApiBase(): string {
  if (typeof window === "undefined") {
    return configuredApiBase;
  }

  try {
    const url = new URL(configuredApiBase);
    const isLocalApiHost =
      url.hostname === "localhost" || url.hostname === "127.0.0.1";
    const isLocalBrowserHost =
      window.location.hostname === "localhost" ||
      window.location.hostname === "127.0.0.1";

    if (isLocalApiHost && !isLocalBrowserHost) {
      url.hostname = window.location.hostname;
    }

    return url.toString().replace(/\/$/, "");
  } catch {
    return configuredApiBase.replace(/\/$/, "");
  }
}

async function makeApiError(response: Response): Promise<ApiError> {
  const rawBody = await response.text();
  let detail: ApiErrorDetail = rawBody;

  try {
    const payload: unknown = JSON.parse(rawBody);
    detail = decodeApiErrorEnvelope(payload).detail ?? rawBody;
  } catch {
    detail = rawBody;
  }

  return new ApiError(response.status, detail, rawBody);
}

async function decodeSuccessfulResponse<T>(
  response: Response,
  path: string,
  schema: JsonSchema<T>,
  contract: string
): Promise<T> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch (error) {
    if (error instanceof SyntaxError) {
      throwApiContractError(path, contract);
    }
    throw error;
  }

  const result = schema.safeParse(payload);
  if (!result.success) {
    throwApiContractError(path, contract);
  }

  return result.data;
}

function throwApiContractError(path: string, contract: string): never {
  const error = new ApiContractError();
  try {
    reportApiContractError(error, { route: path, contract });
  } catch {
    // Optional reporting must not replace the stable transport error.
  }
  throw error;
}

export async function postJson<T>(
  path: string,
  body: unknown,
  schema: JsonSchema<T>,
  contract: string,
  token?: string,
  extraHeaders?: Readonly<Record<string, string>>
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), requestTimeoutMs);
  const response = await fetch(`${resolveApiBase()}${path}`, {
    method: "POST",
    headers: {
      ...extraHeaders,
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    body: JSON.stringify(body),
    signal: controller.signal
  }).finally(() => window.clearTimeout(timeoutId));

  if (!response.ok) {
    throw await makeApiError(response);
  }

  return decodeSuccessfulResponse(response, path, schema, contract);
}

export async function getJson<T>(
  path: string,
  token: string,
  schema: JsonSchema<T>,
  contract: string
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), requestTimeoutMs);

  try {
    const response = await fetch(`${resolveApiBase()}${path}`, {
      headers: {
        Authorization: `Bearer ${token}`
      },
      signal: controller.signal
    });

    if (!response.ok) {
      throw await makeApiError(response);
    }

    return await decodeSuccessfulResponse(response, path, schema, contract);
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export function decodeApiErrorEnvelope(payload: unknown): ApiErrorEnvelope {
  if (!isRecord(payload) || !("detail" in payload)) {
    throw new Error("invalid_api_error_response");
  }

  return { detail: payload.detail };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

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
    return postJson(
      "/api/auth/register",
      request,
      zRegisterResponse,
      "RegisterResponse",
      undefined,
      { "Accept-Language": options.languageTag }
    );
  }

  const request: LoginRequest = {
    email: values.email,
    password: values.password
  };
  return postJson(
    "/api/auth/login",
    request,
    zLoginResponse,
    "LoginResponse"
  );
}

export async function getSession(
  sessionToken: string
): Promise<SessionResponse> {
  return getJson(
    "/api/auth/session",
    sessionToken,
    zSessionResponse,
    "SessionResponse"
  );
}

export async function logoutSession(
  sessionToken: string
): Promise<LogoutResponse> {
  return postJson(
    "/api/auth/logout",
    {},
    zLogoutResponse,
    "LogoutResponse",
    sessionToken
  );
}

export async function requestEmailVerification(
  sessionToken: string,
  languageTag: string
): Promise<EmailVerificationRequestResponse> {
  const request: EmailVerificationRequest = {};
  return postJson(
    "/api/auth/email-verification/request",
    request,
    zEmailVerificationRequestResponse,
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
  return postJson(
    "/api/auth/email-verification/confirm",
    request,
    zEmailVerificationConfirmResponse,
    "EmailVerificationConfirmResponse",
    sessionToken
  );
}

export async function requestPasswordReset(
  values: PasswordResetRequest,
  options: PasswordResetRequestOptions
): Promise<PasswordResetRequestResponse> {
  const request: PasswordResetRequest = { email: values.email };
  return postJson(
    "/api/auth/password-reset/request",
    request,
    zPasswordResetRequestResponse,
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
  return postJson(
    "/api/auth/password-reset/confirm",
    request,
    zPasswordResetConfirmResponse,
    "PasswordResetConfirmResponse"
  );
}
