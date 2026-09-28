"use client";

export type AuthMode = "login" | "register";

export type AuthUser = {
  tenant_id: string;
  region: string;
  user_id: string;
  email: string;
};

export type AuthResponse = {
  status: "registered" | "authenticated";
  token: string;
  user: AuthUser;
};

export type AuthSessionResponse = {
  authenticated: true;
  user: AuthUser;
};

export type LogoutResponse = {
  status: "logged_out";
};

export type PasswordResetRequestResponse = {
  status: "accepted";
};

export type PasswordResetConfirmResponse = {
  status: "password_reset";
};

export type SubmitAuthValues = {
  mode: AuthMode;
  email: string;
  password: string;
  personalConsent: boolean;
  offerConsent: boolean;
};

export type PasswordResetRequestValues = {
  email: string;
};

export type PasswordResetConfirmValues = {
  token: string;
  password: string;
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

type JsonDecoder<T> = (payload: unknown) => T;

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
  decoder: JsonDecoder<T>
): Promise<T> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new ApiContractError();
    }
    throw error;
  }

  try {
    return decoder(payload);
  } catch {
    throw new ApiContractError();
  }
}

export async function postJson<T>(
  path: string,
  body: unknown,
  decoder: JsonDecoder<T>,
  token?: string
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), requestTimeoutMs);
  const response = await fetch(`${resolveApiBase()}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    body: JSON.stringify(body),
    signal: controller.signal
  }).finally(() => window.clearTimeout(timeoutId));

  if (!response.ok) {
    throw await makeApiError(response);
  }

  return decodeSuccessfulResponse(response, decoder);
}

export async function getJson<T>(
  path: string,
  token: string,
  decoder: JsonDecoder<T>
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

    return await decodeSuccessfulResponse(response, decoder);
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export function decodeRegisterResponse(payload: unknown): AuthResponse {
  return decodeAuthResponse(payload, "registered");
}

export function decodeLoginResponse(payload: unknown): AuthResponse {
  return decodeAuthResponse(payload, "authenticated");
}

export function decodeAuthSessionResponse(payload: unknown): AuthSessionResponse {
  if (!isRecord(payload)) {
    throw new Error("invalid_session_response");
  }

  const authenticated = payload.authenticated;
  const user = payload.user;

  if (authenticated !== true || !isAuthUser(user)) {
    throw new Error("invalid_session_response");
  }

  return {
    authenticated,
    user
  };
}

export function decodeLogoutResponse(payload: unknown): LogoutResponse {
  return decodeStatusResponse(payload, "logged_out", "invalid_logout_response");
}

export function decodePasswordResetRequestResponse(
  payload: unknown
): PasswordResetRequestResponse {
  return decodeStatusResponse(
    payload,
    "accepted",
    "invalid_password_reset_request_response"
  );
}

export function decodePasswordResetConfirmResponse(
  payload: unknown
): PasswordResetConfirmResponse {
  return decodeStatusResponse(
    payload,
    "password_reset",
    "invalid_password_reset_confirm_response"
  );
}

export function decodeApiErrorEnvelope(payload: unknown): ApiErrorEnvelope {
  if (!isRecord(payload) || !("detail" in payload)) {
    throw new Error("invalid_api_error_response");
  }

  return { detail: payload.detail };
}

function decodeAuthResponse(
  payload: unknown,
  expectedStatus: AuthResponse["status"]
): AuthResponse {
  if (!isRecord(payload)) {
    throw new Error("invalid_auth_response");
  }

  const status = payload.status;
  const token = payload.token;
  const user = payload.user;

  if (
    status !== expectedStatus ||
    typeof token !== "string" ||
    !isAuthUser(user)
  ) {
    throw new Error("invalid_auth_response");
  }

  return { status: expectedStatus, token, user };
}

function decodeStatusResponse<Status extends string>(
  payload: unknown,
  expectedStatus: Status,
  errorCode: string
): { status: Status } {
  if (!isRecord(payload) || payload.status !== expectedStatus) {
    throw new Error(errorCode);
  }

  return { status: expectedStatus };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isAuthUser(value: unknown): value is AuthUser {
  return (
    isRecord(value) &&
    typeof value.tenant_id === "string" &&
    typeof value.region === "string" &&
    typeof value.user_id === "string" &&
    typeof value.email === "string"
  );
}

export async function submitAuth(values: SubmitAuthValues): Promise<AuthResponse> {
  return values.mode === "register"
    ? postJson(
        "/api/auth/register",
        {
          email: values.email,
          password: values.password,
          personal_consent: values.personalConsent,
          offer_consent: values.offerConsent
        },
        decodeRegisterResponse
      )
    : postJson(
        "/api/auth/login",
        {
          email: values.email,
          password: values.password
        },
        decodeLoginResponse
      );
}

export async function requestPasswordReset(
  values: PasswordResetRequestValues
): Promise<PasswordResetRequestResponse> {
  return postJson(
    "/api/auth/password-reset/request",
    { email: values.email },
    decodePasswordResetRequestResponse
  );
}

export async function confirmPasswordReset(
  values: PasswordResetConfirmValues
): Promise<PasswordResetConfirmResponse> {
  return postJson(
    "/api/auth/password-reset/confirm",
    {
      token: values.token,
      password: values.password
    },
    decodePasswordResetConfirmResponse
  );
}

export function authErrorMessage(
  requestError: unknown,
  fallback = "Не удалось выполнить авторизацию. Попробуйте ещё раз."
): string {
  const code = apiErrorCode(requestError);

  if (
    requestError instanceof ApiError &&
    requestError.status === 409 &&
    code === "email_already_registered"
  ) {
    return "Аккаунт с таким email уже существует. Попробуйте войти.";
  }

  if (
    requestError instanceof ApiError &&
    requestError.status === 401 &&
    code === "invalid_credentials"
  ) {
    return "Неверный email или пароль.";
  }

  if (
    requestError instanceof ApiError &&
    requestError.status === 400 &&
    code === "missing_personal_consent"
  ) {
    return "Нужно дать согласие на обработку персональных данных.";
  }

  if (
    requestError instanceof ApiError &&
    requestError.status === 400 &&
    code === "missing_offer_consent"
  ) {
    return "Нужно принять условия оферты.";
  }

  return fallback;
}

export function passwordResetErrorMessage(requestError: unknown): string {
  const code = apiErrorCode(requestError);

  if (
    requestError instanceof ApiError &&
    requestError.status === 400 &&
    code === "invalid_or_expired_reset_token"
  ) {
    return "Ссылка недействительна или срок её действия истёк. Запросите новую ссылку.";
  }

  if (requestError instanceof ApiError && requestError.status === 422) {
    return "Проверьте email и пароль. Пароль должен содержать не менее 8 символов.";
  }

  return "Не удалось выполнить восстановление пароля. Попробуйте ещё раз.";
}
