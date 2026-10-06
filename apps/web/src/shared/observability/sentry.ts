import * as Sentry from "@sentry/nextjs";

const SERVICE = "payment-portal-web";
const FAILURE_CATEGORY = "consistency_invariant_violation";
const OPERATION = "api_contract_validation";
const CONTRACT_EVENT_MESSAGE = "Generated API contract validation failed";
const GENERIC_EVENT_MESSAGE = "Frontend error";
const CONTRACT_NAME_PATTERN = /^[A-Za-z][A-Za-z0-9_.-]{0,127}$/;
const DISABLED_INTEGRATION_NAMES = new Set([
  "BrowserSession",
  "Http",
  "ProcessSession"
]);

type SentryInitOptions = Parameters<typeof Sentry.init>[0];

const DATA_COLLECTION: NonNullable<SentryInitOptions["dataCollection"]> = {
  userInfo: false,
  cookies: false,
  httpHeaders: false,
  httpBodies: [],
  urlQueryParams: false,
  graphQL: {
    document: false,
    variables: false
  },
  genAI: {
    inputs: false,
    outputs: false
  },
  databaseQueryData: false,
  queues: false,
  stackFrameVariables: false,
  frameContextLines: 0
};

type ApiContractErrorReport = Readonly<{
  route: string;
  contract: string;
}>;

export function isSentryEnabled(): boolean {
  return sentryDsn() !== undefined;
}

export function initializeSentry(): void {
  const dsn = sentryDsn();
  if (!dsn) {
    return;
  }

  try {
    Sentry.init({
      dsn,
      dataCollection: DATA_COLLECTION,
      tracesSampleRate: 0,
      integrations: (integrations) =>
        integrations.filter(
          (integration) => !DISABLED_INTEGRATION_NAMES.has(integration.name)
        ),
      beforeSend: sanitizeSentryEvent
    });
  } catch {
    // Optional observability must never affect application startup.
  }
}

export function reportApiContractError(
  error: unknown,
  report: ApiContractErrorReport
): void {
  if (!isSentryEnabled()) {
    return;
  }

  try {
    Sentry.captureException(sanitizeContractError(error), {
      tags: {
        service: SERVICE,
        failure_category: FAILURE_CATEGORY,
        operation: OPERATION,
        route: pathnameOnly(report.route),
        contract: contractName(report.contract)
      }
    });
  } catch {
    // Reporting is best-effort and must not change the caller's control flow.
  }
}

export function sanitizeSentryEvent(
  event: Sentry.ErrorEvent
): Sentry.ErrorEvent {
  const isContractEvent = event.tags?.operation === OPERATION;
  const genericMessage = isContractEvent
    ? CONTRACT_EVENT_MESSAGE
    : GENERIC_EVENT_MESSAGE;
  const sanitizedEvent: Sentry.ErrorEvent = {
    type: event.type,
    ...(event.event_id !== undefined ? { event_id: event.event_id } : {}),
    ...(event.timestamp !== undefined ? { timestamp: event.timestamp } : {}),
    ...(event.start_timestamp !== undefined
      ? { start_timestamp: event.start_timestamp }
      : {}),
    ...(event.level !== undefined ? { level: event.level } : {}),
    ...(event.platform !== undefined ? { platform: event.platform } : {}),
    ...(event.release !== undefined ? { release: event.release } : {}),
    ...(event.dist !== undefined ? { dist: event.dist } : {}),
    ...(event.environment !== undefined
      ? { environment: event.environment }
      : {}),
    ...(event.sdk !== undefined ? { sdk: event.sdk } : {}),
    message: genericMessage,
    ...(event.exception !== undefined
      ? { exception: sanitizeException(event.exception, genericMessage) }
      : {})
  };

  if (isContractEvent) {
    const route = event.tags?.route;
    const contract = event.tags?.contract;

    sanitizedEvent.tags = {
      service: SERVICE,
      failure_category: FAILURE_CATEGORY,
      operation: OPERATION,
      route: typeof route === "string" ? pathnameOnly(route) : "/",
      contract:
        typeof contract === "string"
          ? contractName(contract)
          : "unknown_contract"
    };
  }

  return sanitizedEvent;
}

function sanitizeException(
  exception: Sentry.ErrorEvent["exception"],
  genericMessage: string
): Sentry.ErrorEvent["exception"] {
  if (!exception) {
    return undefined;
  }

  return {
    values: exception.values?.map((value) => ({
      type: value.type,
      value: genericMessage,
      stacktrace: value.stacktrace
        ? {
            frames: value.stacktrace.frames?.map((frame) => ({
              function: frame.function,
              module: frame.module,
              platform: frame.platform,
              lineno: frame.lineno,
              colno: frame.colno,
              in_app: frame.in_app,
              instruction_addr: frame.instruction_addr,
              addr_mode: frame.addr_mode,
              debug_id: frame.debug_id
            })),
            frames_omitted: value.stacktrace.frames_omitted
          }
        : undefined
    }))
  };
}

function sentryDsn(): string | undefined {
  const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN?.trim();
  return dsn || undefined;
}

function pathnameOnly(route: string): string {
  try {
    return new URL(route, "https://payment-portal.invalid").pathname;
  } catch {
    return "/";
  }
}

function contractName(contract: string): string {
  return CONTRACT_NAME_PATTERN.test(contract) ? contract : "unknown_contract";
}

function sanitizeContractError(error: unknown): Error {
  const sanitizedError = new Error(CONTRACT_EVENT_MESSAGE);
  sanitizedError.name = "ApiContractError";

  if (!(error instanceof Error) || !error.stack) {
    return sanitizedError;
  }

  const stackFrames = error.stack
    .split("\n")
    .slice(1)
    .filter((line) => /^\s*at\s+/.test(line));

  if (stackFrames.length > 0) {
    sanitizedError.stack = [
      `${sanitizedError.name}: ${sanitizedError.message}`,
      ...stackFrames
    ].join("\n");
  }

  return sanitizedError;
}
