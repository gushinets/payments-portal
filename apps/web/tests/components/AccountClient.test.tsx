import "@testing-library/jest-dom/vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AccountClient } from "@/features/account";
import {
  sessionChangedEvent,
  sessionStorageKey
} from "@/shared/api/auth";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" }
  });
}

describe("identity-only account", () => {
  beforeEach(() => {
    window.localStorage.clear();
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("directs a signed-out user to the retained auth surface", async () => {
    render(<AccountClient />);

    expect(
      await screen.findByRole("link", { name: "Войти или зарегистрироваться" })
    ).toHaveAttribute("href", "/ru/auth-checkout");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("loads only the canonical session and shows billing as unavailable", async () => {
    window.localStorage.setItem(sessionStorageKey, "session-token");
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        authenticated: true,
        user: {
          tenant_id: "anytoolai",
          region: "ru",
          user_id: "user-id",
          email: "account@example.com"
        }
      })
    );

    render(<AccountClient />);

    expect(await screen.findByText("account@example.com")).toBeVisible();
    expect(screen.getByText("Биллинг обновляется")).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/api/auth/session");
  });

  it("synchronizes login and logout events after mounting", async () => {
    render(<AccountClient />);

    expect(
      await screen.findByRole("link", { name: "Войти или зарегистрироваться" })
    ).toBeVisible();

    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        authenticated: true,
        user: {
          tenant_id: "anytoolai",
          region: "ru",
          user_id: "user-id",
          email: "synced-account@example.com"
        }
      })
    );
    window.localStorage.setItem(sessionStorageKey, "session-token");
    act(() => {
      window.dispatchEvent(new Event(sessionChangedEvent));
    });

    expect(await screen.findByText("synced-account@example.com")).toBeVisible();
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/api/auth/session");

    window.localStorage.removeItem(sessionStorageKey);
    act(() => {
      window.dispatchEvent(new Event(sessionChangedEvent));
    });

    expect(
      await screen.findByRole("link", { name: "Войти или зарегистрироваться" })
    ).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("revokes the backend session and clears the local bearer token", async () => {
    window.localStorage.setItem(sessionStorageKey, "session-token");
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({
          authenticated: true,
          user: {
            tenant_id: "anytoolai",
            region: "ru",
            user_id: "user-id",
            email: "account@example.com"
          }
        })
      )
      .mockResolvedValueOnce(jsonResponse({ status: "logged_out" }));
    const user = userEvent.setup();
    render(<AccountClient />);

    await user.click(await screen.findByRole("button", { name: "Выйти" }));

    await waitFor(() =>
      expect(window.localStorage.getItem(sessionStorageKey)).toBeNull()
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain("/api/auth/logout");
  });
});
