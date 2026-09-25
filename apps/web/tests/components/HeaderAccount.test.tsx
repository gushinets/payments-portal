import "@testing-library/jest-dom/vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  sessionChangedEvent,
  sessionStorageKey
} from "@/shared/api/auth";
import { HeaderAccount } from "@/shared/ui/HeaderAccount";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" }
  });
}

describe("header account session", () => {
  beforeEach(() => {
    window.localStorage.clear();
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("clears the trusted session when a successful response is malformed", async () => {
    window.localStorage.setItem(sessionStorageKey, "session-token");
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({
          authenticated: true,
          user: {
            tenant_id: "anytoolai",
            region: "ru",
            user_id: "user-id",
            email: "header@example.com"
          }
        })
      )
      .mockResolvedValueOnce(
        jsonResponse({ authenticated: true, user: { email: 123 } })
      );

    render(<HeaderAccount />);

    expect(await screen.findByText("header@example.com")).toBeVisible();

    act(() => {
      window.dispatchEvent(new Event(sessionChangedEvent));
    });

    await waitFor(() =>
      expect(window.localStorage.getItem(sessionStorageKey)).toBeNull()
    );
    expect(await screen.findByRole("button", { name: "Войти" })).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("retains the trusted session during a transient network failure", async () => {
    window.localStorage.setItem(sessionStorageKey, "session-token");
    fetchMock.mockRejectedValueOnce(new TypeError("network unavailable"));

    render(<HeaderAccount />);

    expect(await screen.findByRole("button", { name: "Войти" })).toBeVisible();
    expect(window.localStorage.getItem(sessionStorageKey)).toBe("session-token");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
