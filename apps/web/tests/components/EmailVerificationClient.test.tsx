import "@testing-library/jest-dom/vitest";
import { cleanup, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EmailVerificationClient } from "@/features/email-verification";
import ruMessages from "@/messages/ru.json";
import {
  sessionChangedEvent,
  sessionStorageKey
} from "@/shared/api/auth";
import { renderWithIntl } from "../setup/render-with-intl";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

function renderEmailVerificationClient() {
  return renderWithIntl(<EmailVerificationClient languageTag="ru" />, {
    locale: "ru",
    messages: {
      Auth: ruMessages.Auth,
      EmailVerification: ruMessages.EmailVerification
    }
  });
}

describe("email verification session loading", () => {
  beforeEach(() => {
    window.localStorage.clear();
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("removes the bearer and dispatches a session change after a 401", async () => {
    const sessionChangedListener = vi.fn();
    window.addEventListener(sessionChangedEvent, sessionChangedListener);
    window.localStorage.setItem(sessionStorageKey, "session-token");
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "unauthorized" }, 401)
    );

    try {
      renderEmailVerificationClient();

      await waitFor(() => {
        expect(window.localStorage.getItem(sessionStorageKey)).toBeNull();
      });
      expect(sessionChangedListener).toHaveBeenCalledTimes(1);
      expect(await screen.findByRole("link", { name: "Войти" })).toBeVisible();
    } finally {
      window.removeEventListener(sessionChangedEvent, sessionChangedListener);
    }
  });

  it.each([
    [
      "500",
      () =>
        jsonResponse({ detail: { code: "internal_server_error" } }, 500),
      ruMessages.EmailVerification.errors.internalServer
    ],
    [
      "contract error",
      () => jsonResponse({ authenticated: true }),
      ruMessages.EmailVerification.errors.contract
    ]
  ])(
    "preserves the bearer after a session %s",
    async (_label, response, error) => {
      const sessionChangedListener = vi.fn();
      window.addEventListener(sessionChangedEvent, sessionChangedListener);
      window.localStorage.setItem(sessionStorageKey, "session-token");
      fetchMock.mockResolvedValueOnce(response());

      try {
        renderEmailVerificationClient();

        expect(await screen.findByRole("alert")).toHaveTextContent(error);
        expect(window.localStorage.getItem(sessionStorageKey)).toBe(
          "session-token"
        );
        expect(sessionChangedListener).not.toHaveBeenCalled();
        expect(
          screen.queryByRole("link", { name: "Войти" })
        ).not.toBeInTheDocument();
        expect(
          screen.queryByRole("button", { name: "Войти" })
        ).not.toBeInTheDocument();
      } finally {
        window.removeEventListener(sessionChangedEvent, sessionChangedListener);
      }
    }
  );

  it("shows already-verified UI and ignores an old fragment token", async () => {
    window.history.replaceState(
      window.history.state,
      "",
      "/ru/verify-email#token=old-verification-token"
    );
    window.localStorage.setItem(sessionStorageKey, "session-token");
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        authenticated: true,
        user: {
          tenant_id: "anytoolai",
          region: "ru",
          user_id: "user-id",
          email: "verified@example.com",
          email_verified: true
        }
      })
    );

    renderEmailVerificationClient();

    expect(
      await screen.findByRole("heading", { name: "Email уже подтверждён" })
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Подтвердить email" })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(window.localStorage.getItem(sessionStorageKey)).toBe("session-token");
    expect(window.location.hash).toBe("");
  });
});
