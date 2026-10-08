import * as Sentry from "@sentry/nextjs";
import type { Instrumentation } from "next";
import { isSentryEnabled } from "./shared/observability/sentry";

export async function register(): Promise<void> {
  if (!isSentryEnabled()) {
    return;
  }

  try {
    if (process.env.NEXT_RUNTIME === "nodejs") {
      await import("../sentry.server.config");
    }

    if (process.env.NEXT_RUNTIME === "edge") {
      await import("../sentry.edge.config");
    }
  } catch {
    // Optional observability must never affect application startup.
  }
}

export const onRequestError: Instrumentation.onRequestError = (...args) => {
  if (!isSentryEnabled()) {
    return;
  }

  try {
    Sentry.captureRequestError(...args);
  } catch {
    // Reporting is best-effort and must not affect request handling.
  }
};
