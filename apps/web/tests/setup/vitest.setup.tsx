import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, vi } from "vitest";
import { server } from "./msw-server";

declare global {
  var __NEXT_SEARCH_PARAMS__: string | undefined;
}

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string;
    children: React.ReactNode;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  )
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(globalThis.__NEXT_SEARCH_PARAMS__ ?? "")
}));

beforeAll(() => {
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
  server.listen({ onUnhandledRequest: "error" });
  installFetchAbortSignalCompatibility();
});

afterEach(() => {
  cleanup();
  server.resetHandlers();
  window.localStorage.clear();
  window.sessionStorage.clear();
  globalThis.__NEXT_SEARCH_PARAMS__ = "";
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

afterAll(() => {
  server.close();
});

function installFetchAbortSignalCompatibility() {
  const interceptedFetch = globalThis.fetch.bind(globalThis);

  globalThis.fetch = ((input, init) => {
    if (init?.signal && !requestAcceptsSignal(init.signal)) {
      const nextInit = { ...init };
      delete nextInit.signal;
      return interceptedFetch(input, nextInit);
    }

    return interceptedFetch(input, init);
  }) as typeof fetch;
  window.fetch = globalThis.fetch;
}

function requestAcceptsSignal(signal: AbortSignal) {
  try {
    new Request("http://localhost", { signal });
    return true;
  } catch (error) {
    if (error instanceof TypeError && String(error.message).includes("signal")) {
      return false;
    }

    throw error;
  }
}
