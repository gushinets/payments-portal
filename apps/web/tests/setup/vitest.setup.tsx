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
