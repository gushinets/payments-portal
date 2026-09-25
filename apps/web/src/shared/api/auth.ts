"use client";

export type AuthMode = "login" | "register";

export type AuthUser = {
  tenant_id: string;
  region: string;
  user_id: string;
  email: string;
};

export type AuthResponse = {
  status: string;
  token: string;
  user: AuthUser;
};

export type AuthSessionResponse = {
  authenticated: boolean;
  user: AuthUser;
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

export class ApiError extends Error {
  status: number;
  detail: ApiErrorDetail;

  constructor(status: number, detail: ApiErrorDetail, rawBody: string) {
    super(`${status}:${rawBody}`);
    this.status = status;
    this.detail = detail;
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
    const payload = JSON.parse(rawBody) as { detail?: ApiErrorDetail };
    detail = payload.detail ?? rawBody;
  } catch {
    detail = rawBody;
  }

  return new ApiError(response.status, detail, rawBody);
}

export async function postJson<T>(
  path: string,
  body: unknown,
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

  return response.json() as Promise<T>;
}

export async function getJson<T = unknown>(
  path: string,
  token: string,
  decoder?: JsonDecoder<T>
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), requestTimeoutMs);
  const response = await fetch(`${resolveApiBase()}${path}`, {
    headers: {
      Authorization: `Bearer ${token}`
    },
    signal: controller.signal
  }).finally(() => window.clearTimeout(timeoutId));

  if (!response.ok) {
    throw await makeApiError(response);
  }

  const payload = (await response.json()) as unknown;
  return decoder ? decoder(payload) : (payload as T);
}

export function decodeAuthSessionResponse(payload: unknown): AuthSessionResponse {
  if (!isRecord(payload)) {
    throw new Error("invalid_session_response");
  }

  const authenticated = payload.authenticated;
  const user = payload.user;

  if (typeof authenticated !== "boolean" || !isAuthUser(user)) {
    throw new Error("invalid_session_response");
  }

  return {
    authenticated,
    user
  };
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
    ? postJson<AuthResponse>("/api/auth/register", {
        email: values.email,
        password: values.password,
        personal_consent: values.personalConsent,
        offer_consent: values.offerConsent
      })
    : postJson<AuthResponse>("/api/auth/login", {
        email: values.email,
        password: values.password
      });
}

export async function requestPasswordReset(
  values: PasswordResetRequestValues
): Promise<{ status: string }> {
  return postJson<{ status: string }>("/api/auth/password-reset/request", {
    email: values.email
  });
}

export async function confirmPasswordReset(
  values: PasswordResetConfirmValues
): Promise<{ status: string }> {
  return postJson<{ status: string }>("/api/auth/password-reset/confirm", {
    token: values.token,
    password: values.password
  });
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
