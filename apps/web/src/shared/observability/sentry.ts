import * as Sentry from "@sentry/nextjs";

const SERVICE = "payment-portal-web";
const FAILURE_CATEGORY = "consistency_invariant_violation";
const OPERATION = "api_contract_validation";
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
  const sanitizedEvent = { ...event };

  delete sanitizedEvent.breadcrumbs;
  delete sanitizedEvent.contexts;
  delete sanitizedEvent.extra;
  delete sanitizedEvent.modules;
  delete sanitizedEvent.request;
  delete sanitizedEvent.server_name;
  delete sanitizedEvent.user;

  if (sanitizedEvent.tags?.operation === OPERATION) {
    const route = sanitizedEvent.tags.route;
    const contract = sanitizedEvent.tags.contract;

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
    delete sanitizedEvent.transaction;
    delete sanitizedEvent.transaction_info;
  }

  return sanitizedEvent;
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
  const sanitizedError = new Error("Generated API contract validation failed");
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
