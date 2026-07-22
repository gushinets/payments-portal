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

export type SubmitAuthValues = {
  mode: AuthMode;
  email: string;
  password: string;
  personalConsent: boolean;
  offerConsent: boolean;
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

const configuredApiBase =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
export const requestTimeoutMs = 5000;

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

export async function getJson<T>(path: string, token: string): Promise<T> {
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

  return response.json() as Promise<T>;
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
