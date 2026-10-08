"use client";

import { reportApiContractError } from "@/shared/observability/sentry";

export type ApiErrorDetail = unknown;

export type ApiErrorEnvelope = {
  detail: ApiErrorDetail;
};

export class ApiError extends Error {
  status: number;
  detail: ApiErrorDetail;

  constructor(status: number, detail: ApiErrorDetail) {
    super("api_request_failed");
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
    const payload: unknown = JSON.parse(rawBody);
    detail = decodeApiErrorEnvelope(payload).detail ?? rawBody;
  } catch {
    detail = rawBody;
  }

  return new ApiError(response.status, detail);
}

async function decodeSuccessfulResponse<T>(
  response: Response,
  path: string,
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

  // Same-service trust boundary: FastAPI/Pydantic owns runtime validation.
  // Generated TypeScript owns the wire shape; this assertion does not validate JSON.
  return payload as T;
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

  return decodeSuccessfulResponse<T>(response, path, contract);
}

export async function getJson<T>(
  path: string,
  token: string,
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

    return await decodeSuccessfulResponse<T>(response, path, contract);
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

