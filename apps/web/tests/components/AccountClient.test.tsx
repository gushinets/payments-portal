import "@testing-library/jest-dom/vitest";
import { act, cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AccountClient } from "@/features/account";
import ruMessages from "@/messages/ru.json";
import {
  sessionChangedEvent,
  sessionStorageKey
} from "@/shared/api/auth";
import { renderWithIntl } from "../setup/render-with-intl";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" }
  });
}

function renderAccountClient() {
  return renderWithIntl(<AccountClient languageTag="ru" />, {
    locale: "ru",
    messages: {
      Account: ruMessages.Account,
      EmailVerification: ruMessages.EmailVerification
    }
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
    renderAccountClient();

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
          user_id: "11111111-1111-4111-8111-111111111111",
          email: "account@example.com",
          email_verified: true
        }
      })
    );

    renderAccountClient();

    expect(await screen.findByText("account@example.com")).toBeVisible();
    expect(screen.getByText("Биллинг обновляется")).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/api/auth/session");
  });

  it("synchronizes login and logout events after mounting", async () => {
    renderAccountClient();

    expect(
      await screen.findByRole("link", { name: "Войти или зарегистрироваться" })
    ).toBeVisible();

    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        authenticated: true,
        user: {
          tenant_id: "anytoolai",
          region: "ru",
          user_id: "11111111-1111-4111-8111-111111111111",
          email: "synced-account@example.com",
          email_verified: true
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
            user_id: "11111111-1111-4111-8111-111111111111",
            email: "account@example.com",
            email_verified: true
          }
        })
      )
      .mockResolvedValueOnce(jsonResponse({ status: "logged_out" }));
    const user = userEvent.setup();
    renderAccountClient();

    await user.click(await screen.findByRole("button", { name: "Выйти" }));

    await waitFor(() =>
      expect(window.localStorage.getItem(sessionStorageKey)).toBeNull()
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain("/api/auth/logout");
  });
});
