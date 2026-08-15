import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, vi } from "vitest";
import { server } from "./msw-server";

declare global {
  var __NEXT_SEARCH_PARAMS__: string | undefined;
  var __NEXT_ROUTER_PUSH__: ((href: string) => void) | undefined;
  var __ANYTOOLAI_FETCH_SIGNAL_STRIPPED_COUNT__: number | undefined;
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
  useRouter: () => ({
    push: (href: string) => globalThis.__NEXT_ROUTER_PUSH__?.(href)
  }),
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
  globalThis.__NEXT_ROUTER_PUSH__ = undefined;
  globalThis.__ANYTOOLAI_FETCH_SIGNAL_STRIPPED_COUNT__ = 0;
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

afterAll(() => {
  server.close();
});

function installFetchAbortSignalCompatibility() {
  const interceptedFetch = globalThis.fetch.bind(globalThis);
  globalThis.__ANYTOOLAI_FETCH_SIGNAL_STRIPPED_COUNT__ = 0;

  globalThis.fetch = ((input, init) => {
    if (init?.signal && !requestAcceptsSignal(init.signal)) {
      const nextInit = { ...init };
      delete nextInit.signal;
      globalThis.__ANYTOOLAI_FETCH_SIGNAL_STRIPPED_COUNT__ =
        (globalThis.__ANYTOOLAI_FETCH_SIGNAL_STRIPPED_COUNT__ ?? 0) + 1;
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
