import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EmailVerificationClient } from "@/features/email-verification";
import ruMessages from "@/messages/ru.json";
import {
  sessionChangedEvent,
  sessionStorageKey
} from "@/shared/api/auth";
import { EmailVerificationPending } from "@/shared/ui";
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

  it("ignores a stale session 401 after the bearer changes", async () => {
    const sessionChangedListener = vi.fn();
    let resolveSession: (response: Response) => void = () => undefined;
    const sessionRequest = new Promise<Response>((resolve) => {
      resolveSession = resolve;
    });

    window.addEventListener(sessionChangedEvent, sessionChangedListener);
    window.localStorage.setItem(sessionStorageKey, "token-a");
    fetchMock.mockReturnValueOnce(sessionRequest);

    try {
      renderEmailVerificationClient();

      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      window.localStorage.setItem(sessionStorageKey, "token-b");

      await act(async () => {
        resolveSession(jsonResponse({ detail: "unauthorized" }, 401));
      });

      expect(window.localStorage.getItem(sessionStorageKey)).toBe("token-b");
      expect(sessionChangedListener).not.toHaveBeenCalled();
      expect(
        screen.queryByRole("link", { name: "Войти" })
      ).not.toBeInTheDocument();
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

  it("refreshes the session after an external login without losing the fragment token", async () => {
    window.history.replaceState(
      window.history.state,
      "",
      "/ru/verify-email#token=external-login-token"
    );
    renderEmailVerificationClient();

    expect(await screen.findByRole("button", { name: "Войти" })).toBeVisible();

    window.localStorage.setItem(sessionStorageKey, "session-token");
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        authenticated: true,
        user: {
          tenant_id: "anytoolai",
          region: "ru",
          user_id: "11111111-1111-4111-8111-111111111111",
          email: "signed-in@example.com",
          email_verified: false
        }
      })
    );

    await act(async () => {
      window.dispatchEvent(new Event(sessionChangedEvent));
    });

    expect(
      await screen.findByRole("heading", { name: "Подтвердите email" })
    ).toBeVisible();
    fetchMock.mockResolvedValueOnce(jsonResponse({ status: "verified" }));
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить email" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenNthCalledWith(
        2,
        expect.stringContaining("/api/auth/email-verification/confirm"),
        expect.objectContaining({
          body: JSON.stringify({ token: "external-login-token" })
        })
      );
    });
    expect(
      await screen.findByRole("heading", { name: "Email подтверждён" })
    ).toBeVisible();
  });

  it("does not clear a newer bearer after a stale verification 401", async () => {
    const sessionChangedListener = vi.fn();
    let resolveVerification: (response: Response) => void = () => undefined;
    const verificationRequest = new Promise<Response>((resolve) => {
      resolveVerification = resolve;
    });

    window.addEventListener(sessionChangedEvent, sessionChangedListener);
    window.history.replaceState(
      window.history.state,
      "",
      "/ru/verify-email#token=verification-token"
    );
    window.localStorage.setItem(sessionStorageKey, "token-a");
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({
          authenticated: true,
          user: {
            tenant_id: "anytoolai",
            region: "ru",
            user_id: "11111111-1111-4111-8111-111111111111",
            email: "signed-in@example.com",
            email_verified: false
          }
        })
      )
      .mockReturnValueOnce(verificationRequest);

    try {
      renderEmailVerificationClient();
      fireEvent.click(
        await screen.findByRole("button", { name: "Подтвердить email" })
      );
      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
      window.localStorage.setItem(sessionStorageKey, "token-b");

      await act(async () => {
        resolveVerification(jsonResponse({ detail: "unauthorized" }, 401));
      });

      expect(window.localStorage.getItem(sessionStorageKey)).toBe("token-b");
      expect(sessionChangedListener).not.toHaveBeenCalled();
      expect(
        screen.getByRole("heading", { name: "Подтвердите email" })
      ).toBeVisible();
    } finally {
      window.removeEventListener(sessionChangedEvent, sessionChangedListener);
    }
  });

  it("clears the current bearer after a verification 401", async () => {
    const sessionChangedListener = vi.fn();
    window.addEventListener(sessionChangedEvent, sessionChangedListener);
    window.history.replaceState(
      window.history.state,
      "",
      "/ru/verify-email#token=verification-token"
    );
    window.localStorage.setItem(sessionStorageKey, "session-token");
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({
          authenticated: true,
          user: {
            tenant_id: "anytoolai",
            region: "ru",
            user_id: "11111111-1111-4111-8111-111111111111",
            email: "signed-in@example.com",
            email_verified: false
          }
        })
      )
      .mockResolvedValueOnce(jsonResponse({ detail: "unauthorized" }, 401));

    try {
      renderEmailVerificationClient();
      fireEvent.click(
        await screen.findByRole("button", { name: "Подтвердить email" })
      );

      await waitFor(() => {
        expect(window.localStorage.getItem(sessionStorageKey)).toBeNull();
      });
      expect(sessionChangedListener).toHaveBeenCalledTimes(1);
      expect(await screen.findByRole("button", { name: "Войти" })).toBeVisible();
    } finally {
      window.removeEventListener(sessionChangedEvent, sessionChangedListener);
    }
  });

  it("ignores a stale switch-account logout after the bearer changes", async () => {
    const sessionChangedListener = vi.fn();
    let resolveLogout: (response: Response) => void = () => undefined;
    const logoutRequest = new Promise<Response>((resolve) => {
      resolveLogout = resolve;
    });

    window.addEventListener(sessionChangedEvent, sessionChangedListener);
    window.history.replaceState(
      window.history.state,
      "",
      "/ru/verify-email#token=verification-token"
    );
    window.localStorage.setItem(sessionStorageKey, "token-a");
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({
          authenticated: true,
          user: {
            tenant_id: "anytoolai",
            region: "ru",
            user_id: "11111111-1111-4111-8111-111111111111",
            email: "signed-in@example.com",
            email_verified: false
          }
        })
      )
      .mockReturnValueOnce(logoutRequest);

    try {
      renderEmailVerificationClient();
      fireEvent.click(
        await screen.findByRole("button", {
          name: "Выйти и сменить аккаунт"
        })
      );
      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
      window.localStorage.setItem(sessionStorageKey, "token-b");

      await act(async () => {
        resolveLogout(jsonResponse({ status: "logged_out" }));
      });

      expect(window.localStorage.getItem(sessionStorageKey)).toBe("token-b");
      expect(sessionChangedListener).not.toHaveBeenCalled();
      expect(
        await screen.findByRole("heading", { name: "Подтвердите email" })
      ).toBeVisible();
      expect(
        screen.queryByRole("button", { name: "Войти" })
      ).not.toBeInTheDocument();
    } finally {
      window.removeEventListener(sessionChangedEvent, sessionChangedListener);
    }
  });

  it("signs out locally when the current switch-account logout fails", async () => {
    const sessionChangedListener = vi.fn();
    window.addEventListener(sessionChangedEvent, sessionChangedListener);
    window.history.replaceState(
      window.history.state,
      "",
      "/ru/verify-email#token=verification-token"
    );
    window.localStorage.setItem(sessionStorageKey, "session-token");
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({
          authenticated: true,
          user: {
            tenant_id: "anytoolai",
            region: "ru",
            user_id: "11111111-1111-4111-8111-111111111111",
            email: "signed-in@example.com",
            email_verified: false
          }
        })
      )
      .mockResolvedValueOnce(jsonResponse({ detail: "unavailable" }, 500));

    try {
      renderEmailVerificationClient();
      fireEvent.click(
        await screen.findByRole("button", {
          name: "Выйти и сменить аккаунт"
        })
      );

      await waitFor(() => {
        expect(window.localStorage.getItem(sessionStorageKey)).toBeNull();
      });
      expect(sessionChangedListener).toHaveBeenCalledTimes(1);
      expect(await screen.findByRole("button", { name: "Войти" })).toBeVisible();
    } finally {
      window.removeEventListener(sessionChangedEvent, sessionChangedListener);
    }
  });

  it("preserves a pending fragment token for an already-verified session", async () => {
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
          user_id: "11111111-1111-4111-8111-111111111111",
          email: "verified@example.com",
          email_verified: true
        }
      })
    );
    fetchMock.mockResolvedValueOnce(jsonResponse({ status: "verified" }));

    renderEmailVerificationClient();

    expect(
      await screen.findByRole("heading", { name: "Подтвердите email" })
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Подтвердить email" })
    ).toBeVisible();
    expect(
      screen.queryByRole("heading", { name: "Email уже подтверждён" })
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Подтвердить email" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenNthCalledWith(
        2,
        expect.stringContaining("/api/auth/email-verification/confirm"),
        expect.objectContaining({
          body: JSON.stringify({ token: "old-verification-token" })
        })
      );
    });
    expect(
      await screen.findByRole("heading", { name: "Email подтверждён" })
    ).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(window.localStorage.getItem(sessionStorageKey)).toBe("session-token");
    expect(window.location.hash).toBe("");
  });
});

describe("pending email verification", () => {
  beforeEach(() => {
    window.localStorage.clear();
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("does not clear a newer bearer after a stale resend 401", async () => {
    const sessionChangedListener = vi.fn();
    let resolveResend: (response: Response) => void = () => undefined;
    const resendRequest = new Promise<Response>((resolve) => {
      resolveResend = resolve;
    });

    window.addEventListener(sessionChangedEvent, sessionChangedListener);
    window.localStorage.setItem(sessionStorageKey, "token-a");
    fetchMock.mockReturnValueOnce(resendRequest);

    try {
      renderWithIntl(<EmailVerificationPending languageTag="ru" />, {
        locale: "ru",
        messages: {
          EmailVerification: ruMessages.EmailVerification
        }
      });
      fireEvent.click(
        screen.getByRole("button", { name: "Отправить письмо ещё раз" })
      );
      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      window.localStorage.setItem(sessionStorageKey, "token-b");

      await act(async () => {
        resolveResend(jsonResponse({ detail: "unauthorized" }, 401));
      });

      expect(window.localStorage.getItem(sessionStorageKey)).toBe("token-b");
      expect(sessionChangedListener).not.toHaveBeenCalled();
      expect(
        screen.queryByText(ruMessages.EmailVerification.errors.signInRequired)
      ).not.toBeInTheDocument();
    } finally {
      window.removeEventListener(sessionChangedEvent, sessionChangedListener);
    }
  });
});
