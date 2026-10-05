import { beforeEach, describe, expect, it, vi } from "vitest";

const sentry = vi.hoisted(() => ({
  captureException: vi.fn(),
  captureRequestError: vi.fn(),
  init: vi.fn()
}));

vi.mock("@sentry/nextjs", () => sentry);

const enabledDsn = "https://public@example.invalid/1";

beforeEach(() => {
  vi.resetModules();
  sentry.captureException.mockReset();
  sentry.captureRequestError.mockReset();
  sentry.init.mockReset();
});

describe("frontend Sentry boundary", () => {
  it("does not initialize or capture when the DSN is missing", async () => {
    vi.stubEnv("NEXT_PUBLIC_SENTRY_DSN", "   ");

    await import("../../src/instrumentation-client");
    await import("../../sentry.server.config");
    await import("../../sentry.edge.config");

    const instrumentation = await import("../../src/instrumentation");
    const { reportApiContractError } = await import(
      "@/shared/observability/sentry"
    );

    await instrumentation.register();
    instrumentation.onRequestError(
      new Error("request failure"),
      { path: "/ru/account?token=secret", method: "GET", headers: {} },
      {
        routerKind: "App Router",
        routePath: "/app/[locale]/account/page",
        routeType: "render",
        renderSource: "server-rendering",
        revalidateReason: undefined
      }
    );
    reportApiContractError(new Error("contract failure"), {
      route: "/ru/account",
      contract: "AuthSessionResponse"
    });

    expect(sentry.init).not.toHaveBeenCalled();
    expect(sentry.captureRequestError).not.toHaveBeenCalled();
    expect(sentry.captureException).not.toHaveBeenCalled();
  });

  it("initializes with restrictive error-only data collection", async () => {
    vi.stubEnv("NEXT_PUBLIC_SENTRY_DSN", `  ${enabledDsn}  `);

    await import("../../src/instrumentation-client");

    expect(sentry.init).toHaveBeenCalledOnce();
    expect(sentry.init).toHaveBeenCalledWith({
      dsn: enabledDsn,
      dataCollection: {
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
      },
      tracesSampleRate: 0,
      integrations: expect.any(Function),
      beforeSend: expect.any(Function)
    });

    const initOptions = sentry.init.mock.calls[0][0];
    expect(
      initOptions.integrations([
        { name: "BrowserSession" },
        { name: "Http" },
        { name: "ProcessSession" },
        { name: "GlobalHandlers" }
      ])
    ).toEqual([{ name: "GlobalHandlers" }]);
  });

  it("reports only approved contract metadata with a pathname-only route", async () => {
    const secret = "do-not-send-this-token";
    vi.stubEnv("NEXT_PUBLIC_SENTRY_DSN", enabledDsn);
    const { reportApiContractError } = await import(
      "@/shared/observability/sentry"
    );
    const error = Object.assign(
      new Error(`raw payload contained ${secret}`),
      {
        payload: { email: "user@example.com" },
        token: secret,
        user: { email: "user@example.com" }
      }
    );
    const report = {
      route: `https://portal.example/ru/account?token=${secret}#${secret}`,
      contract: "AuthSessionResponse",
      payload: { token: secret },
      user: { email: "user@example.com" }
    };

    reportApiContractError(error, report);

    expect(sentry.captureException).toHaveBeenCalledOnce();
    const [capturedError, captureContext] =
      sentry.captureException.mock.calls[0];

    expect(capturedError).toBeInstanceOf(Error);
    expect(capturedError).toMatchObject({
      name: "ApiContractError",
      message: "Generated API contract validation failed"
    });
    expect(capturedError.stack).not.toContain(secret);
    expect(capturedError).not.toHaveProperty("payload");
    expect(capturedError).not.toHaveProperty("token");
    expect(capturedError).not.toHaveProperty("user");
    expect(captureContext).toEqual({
      tags: {
        service: "payment-portal-web",
        failure_category: "consistency_invariant_violation",
        operation: "api_contract_validation",
        route: "/ru/account",
        contract: "AuthSessionResponse"
      }
    });
    expect(JSON.stringify(captureContext)).not.toContain(secret);
    expect(JSON.stringify(captureContext)).not.toContain("user@example.com");
  });

  it("removes SDK-created request and application data before delivery", async () => {
    const { sanitizeSentryEvent } = await import(
      "@/shared/observability/sentry"
    );
    const sanitizedEvent = sanitizeSentryEvent({
      type: undefined,
      event_id: "event-id",
      message: "safe message",
      modules: { application: "1.0.0" },
      server_name: "internal-host",
      transaction: "/ru/account?token=sensitive",
      transaction_info: { source: "url" },
      breadcrumbs: [{ message: "sensitive breadcrumb" }],
      contexts: { application: { payload: "sensitive payload" } },
      extra: { token: "sensitive token" },
      request: {
        url: "https://portal.example/ru/account?token=sensitive"
      },
      user: { email: "user@example.com" },
      tags: {
        service: "payment-portal-web",
        failure_category: "consistency_invariant_violation",
        operation: "api_contract_validation",
        route: "/ru/account?token=sensitive#sensitive",
        contract: "AuthSessionResponse",
        arbitrary: "sensitive application data"
      }
    });

    expect(sanitizedEvent).toEqual({
      type: undefined,
      event_id: "event-id",
      message: "safe message",
      tags: {
        service: "payment-portal-web",
        failure_category: "consistency_invariant_violation",
        operation: "api_contract_validation",
        route: "/ru/account",
        contract: "AuthSessionResponse"
      }
    });
  });

  it("does not throw when capture fails", async () => {
    vi.stubEnv("NEXT_PUBLIC_SENTRY_DSN", enabledDsn);
    sentry.captureException.mockImplementationOnce(() => {
      throw new Error("Sentry unavailable");
    });
    const { reportApiContractError } = await import(
      "@/shared/observability/sentry"
    );

    expect(() =>
      reportApiContractError(new Error("contract failure"), {
        route: "/ru/account",
        contract: "AuthSessionResponse"
      })
    ).not.toThrow();
  });
});
