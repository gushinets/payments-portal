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

export type AuthProductState = {
  product_code: string;
  plan_code?: string | null;
  plan_name?: string | null;
  invoice_id?: string | null;
  transaction_id?: string | null;
  status: "inactive" | "pending" | "active" | "failed";
  starts_at?: string | null;
  expires_at?: string | null;
};

export type AuthSessionResponse = {
  authenticated: boolean;
  user: AuthUser;
  product_state?: AuthProductState | null;
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
  const productState = payload.product_state;

  if (typeof authenticated !== "boolean" || !isAuthUser(user)) {
    throw new Error("invalid_session_response");
  }

  if (
    productState !== undefined &&
    productState !== null &&
    !isAuthProductState(productState)
  ) {
    throw new Error("invalid_session_response");
  }

  return {
    authenticated,
    user,
    ...(productState !== undefined
      ? { product_state: productState }
      : {})
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

function isAuthProductState(value: unknown): value is AuthProductState {
  if (!isRecord(value)) {
    return false;
  }

  const status = value.status;
  return (
    typeof value.product_code === "string" &&
    (value.plan_code === undefined ||
      value.plan_code === null ||
      typeof value.plan_code === "string") &&
    (value.plan_name === undefined ||
      value.plan_name === null ||
      typeof value.plan_name === "string") &&
    (value.invoice_id === undefined ||
      value.invoice_id === null ||
      typeof value.invoice_id === "string") &&
    (value.transaction_id === undefined ||
      value.transaction_id === null ||
      typeof value.transaction_id === "string") &&
    (status === "inactive" ||
      status === "pending" ||
      status === "active" ||
      status === "failed") &&
    (value.starts_at === undefined ||
      value.starts_at === null ||
      typeof value.starts_at === "string") &&
    (value.expires_at === undefined ||
      value.expires_at === null ||
      typeof value.expires_at === "string")
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
  const message =
    requestError instanceof Error ? requestError.message : "auth_error";

  if (message.includes("409")) {
    return "Аккаунт с таким email уже существует. Попробуйте войти.";
  }

  if (message.includes("401")) {
    return "Неверный email или пароль.";
  }

  if (message.includes("missing_personal_consent")) {
    return "Нужно дать согласие на обработку персональных данных.";
  }

  if (message.includes("missing_offer_consent")) {
    return "Нужно принять условия оферты.";
  }

  return fallback;
}

export function passwordResetErrorMessage(requestError: unknown): string {
  const message =
    requestError instanceof Error ? requestError.message : "password_reset_error";

  if (message.includes("invalid_or_expired_reset_token")) {
    return "Ссылка недействительна или срок её действия истёк. Запросите новую ссылку.";
  }

  if (message.includes("422")) {
    return "Проверьте email и пароль. Пароль должен содержать не менее 8 символов.";
  }

  return "Не удалось выполнить восстановление пароля. Попробуйте ещё раз.";
}
