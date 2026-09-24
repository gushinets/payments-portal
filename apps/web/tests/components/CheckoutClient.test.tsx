import "@testing-library/jest-dom/vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CheckoutClient } from "@/features/checkout";
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

describe("provider-independent auth shell", () => {
  beforeEach(() => {
    window.localStorage.clear();
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders login and registration without loading commerce APIs", async () => {
    render(<CheckoutClient />);

    expect(
      await screen.findByRole("heading", { name: "Вход или регистрация" })
    ).toBeVisible();
    expect(screen.getByText("Оплата временно недоступна")).toBeVisible();
    expect(screen.getByRole("button", { name: "Вход" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Регистрация" })).toBeVisible();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("logs in, stores the bearer session and shows the canonical user", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({
          status: "authenticated",
          token: "session-token",
          user: {
            tenant_id: "anytoolai",
            region: "ru",
            user_id: "user-id",
            email: "user@example.com"
          }
        })
      )
      .mockResolvedValueOnce(
        jsonResponse({
          authenticated: true,
          user: {
            tenant_id: "anytoolai",
            region: "ru",
            user_id: "user-id",
            email: "user@example.com"
          }
        })
      );
    const user = userEvent.setup();
    render(<CheckoutClient />);

    await user.type(await screen.findByLabelText("Email"), "user@example.com");
    await user.type(screen.getByLabelText("Пароль"), "very-secret-password");
    await user.click(screen.getByRole("button", { name: /^Войти/ }));

    expect(await screen.findByText("user@example.com")).toBeVisible();
    expect(window.localStorage.getItem(sessionStorageKey)).toBe("session-token");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/api/auth/login");
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain("/api/auth/session");
  });

  it("registers with explicit legal confirmations and stores the bearer session", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({
          status: "registered",
          token: "registered-session-token",
          user: {
            tenant_id: "anytoolai",
            region: "ru",
            user_id: "registered-user-id",
            email: "new-user@example.com"
          }
        })
      )
      .mockResolvedValueOnce(
        jsonResponse({
          authenticated: true,
          user: {
            tenant_id: "anytoolai",
            region: "ru",
            user_id: "registered-user-id",
            email: "new-user@example.com"
          }
        })
      );
    const user = userEvent.setup();
    render(<CheckoutClient />);

    await user.click(
      await screen.findByRole("button", { name: "Регистрация" })
    );
    await user.type(screen.getByLabelText("Email"), "new-user@example.com");
    await user.type(screen.getByLabelText("Пароль"), "very-secret-password");
    await user.type(
      screen.getByLabelText("Повторите пароль"),
      "very-secret-password"
    );
    for (const checkbox of screen.getAllByRole("checkbox")) {
      await user.click(checkbox);
    }
    await user.click(screen.getByRole("button", { name: /Создать аккаунт/ }));

    expect(await screen.findByText("new-user@example.com")).toBeVisible();
    expect(window.localStorage.getItem(sessionStorageKey)).toBe(
      "registered-session-token"
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/api/auth/register");
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain("/api/auth/session");
  });

  it("restores an existing identity session without product selectors", async () => {
    window.localStorage.setItem(sessionStorageKey, "session-token");
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        authenticated: true,
        user: {
          tenant_id: "anytoolai",
          region: "ru",
          user_id: "user-id",
          email: "returning@example.com"
        }
      })
    );

    render(<CheckoutClient />);

    expect(await screen.findByText("returning@example.com")).toBeVisible();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/api/auth/session");
  });

  it("synchronizes login and logout events after mounting", async () => {
    render(<CheckoutClient />);

    expect(
      await screen.findByRole("heading", { name: "Вход или регистрация" })
    ).toBeVisible();

    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        authenticated: true,
        user: {
          tenant_id: "anytoolai",
          region: "ru",
          user_id: "user-id",
          email: "synced-checkout@example.com"
        }
      })
    );
    window.localStorage.setItem(sessionStorageKey, "session-token");
    act(() => {
      window.dispatchEvent(new Event(sessionChangedEvent));
    });

    expect(await screen.findByText("synced-checkout@example.com")).toBeVisible();
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/api/auth/session");

    window.localStorage.removeItem(sessionStorageKey);
    act(() => {
      window.dispatchEvent(new Event(sessionChangedEvent));
    });

    expect(
      await screen.findByRole("heading", { name: "Вход или регистрация" })
    ).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
