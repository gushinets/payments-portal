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
    fetchMock.mockReturnValueOnce(sessionRequest).mockResolvedValueOnce(jsonResponse({
      authenticated: true,
      user: { tenant_id: "anytoolai", region: "ru", user_id: "11111111-1111-4111-8111-111111111111", email: "new@example.com", email_verified: true }
    }));

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
      "invalid JSON syntax",
      () => new Response("not-json", { status: 200 }),
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

  it.each(["success", "failure"])("preserves login B and the capability after switch-account revoke A %s", async (result) => {
    const sessionChangedListener = vi.fn();
    let resolveLogout: (response: Response) => void = () => undefined;
    const logoutRequest = new Promise<Response>((resolve) => {
      resolveLogout = resolve;
    });
    const user = {
      tenant_id: "anytoolai", region: "ru",
      user_id: "11111111-1111-4111-8111-111111111111",
      email: "signed-in@example.com", email_verified: false
    };
    window.addEventListener(sessionChangedEvent, sessionChangedListener);
    window.history.replaceState(null, "", "/ru/verify-email#token=verification-token");
    window.localStorage.setItem(sessionStorageKey, "token-a");
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ authenticated: true, user }))
      .mockReturnValueOnce(logoutRequest)
      .mockResolvedValueOnce(jsonResponse({
        status: "authenticated", token: "token-b",
        user: { ...user, email: "new@example.com" }
      }))
      .mockResolvedValueOnce(jsonResponse({ status: "verified" }));

    try {
      renderEmailVerificationClient();
      fireEvent.click(await screen.findByRole("button", { name: "Выйти и сменить аккаунт" }));
      expect(window.localStorage.getItem(sessionStorageKey)).toBeNull();
      expect(sessionChangedListener).toHaveBeenCalledTimes(1);
      const email = screen.getByLabelText("Email");
      fireEvent.change(email, { target: { value: "new@example.com" } });
      fireEvent.change(screen.getByLabelText("Пароль", { exact: true }), { target: { value: "Synthetic-password-123!" } });
      fireEvent.submit(email.closest("form")!);
      expect(await screen.findByText("new@example.com")).toBeVisible();
      expect(sessionChangedListener).toHaveBeenCalledTimes(2);

      await act(async () => {
        resolveLogout(result === "success"
          ? jsonResponse({ status: "logged_out" })
          : jsonResponse({ detail: "unavailable" }, 503));
      });

      expect(window.localStorage.getItem(sessionStorageKey)).toBe("token-b");
      expect(screen.getByText("new@example.com")).toBeVisible();
      expect(screen.queryByRole("button", { name: "Войти" })).not.toBeInTheDocument();
      expect(sessionChangedListener).toHaveBeenCalledTimes(2);
      expect(fetchMock).toHaveBeenCalledTimes(3);
      expect(fetchMock.mock.calls[1]?.[1]?.headers).toMatchObject({ Authorization: "Bearer token-a" });
      expect(window.location.hash).toBe("");
      fireEvent.click(screen.getByRole("button", { name: "Подтвердить email" }));
      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
      expect(fetchMock.mock.calls[3]?.[1]?.headers).toMatchObject({ Authorization: "Bearer token-b" });
      expect(fetchMock.mock.calls[3]?.[1]?.body).toBe(JSON.stringify({ token: "verification-token" }));
      expect(await screen.findByRole("heading", { name: ruMessages.EmailVerification.verify.successTitle })).toBeVisible();
    } finally {
      window.removeEventListener(sessionChangedEvent, sessionChangedListener);
    }
  });

  it.each(["500", "503", "network failure"])("signs out locally when switch-account revoke encounters %s", async (failure) => {
    const sessionChangedListener = vi.fn();
    window.addEventListener(sessionChangedEvent, sessionChangedListener);
    window.history.replaceState(null, "", "/ru/verify-email#token=verification-token");
    window.localStorage.setItem(sessionStorageKey, "session-token");
    fetchMock.mockResolvedValueOnce(jsonResponse({
      authenticated: true,
      user: {
        tenant_id: "anytoolai", region: "ru",
        user_id: "11111111-1111-4111-8111-111111111111",
        email: "signed-in@example.com", email_verified: false
      }
    }));
    if (failure === "network failure") {
      fetchMock.mockRejectedValueOnce(new TypeError("network unavailable"));
    } else {
      fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "unavailable" }, Number(failure)));
    }

    try {
      renderEmailVerificationClient();
      fireEvent.click(await screen.findByRole("button", { name: "Выйти и сменить аккаунт" }));
      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
      expect(window.localStorage.getItem(sessionStorageKey)).toBeNull();
      expect(sessionChangedListener).toHaveBeenCalledTimes(1);
      expect(screen.getByRole("button", { name: "Войти" })).toBeEnabled();
      expect(screen.queryByText("signed-in@example.com")).not.toBeInTheDocument();
      expect(fetchMock.mock.calls[1]?.[1]?.headers).toMatchObject({ Authorization: "Bearer session-token" });
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
