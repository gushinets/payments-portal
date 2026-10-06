import "@testing-library/jest-dom/vitest";
import { act, cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AccountClient } from "@/features/account";
import ptMessages from "@/messages/pt.json";
import ruMessages from "@/messages/ru.json";
import {
  requestTimeoutMs,
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

const accountUser = {
  tenant_id: "anytoolai",
  region: "ru",
  user_id: "11111111-1111-4111-8111-111111111111",
  email: "account@example.com",
  email_verified: true
};

function sessionResponse(email = accountUser.email) {
  return jsonResponse({ authenticated: true, user: { ...accountUser, email } });
}

function deferredResponse() {
  let resolveResponse: (response: Response) => void = () => undefined;
  const promise = new Promise<Response>((resolve) => {
    resolveResponse = resolve;
  });
  return { promise, resolveResponse };
}

function renderAccountClient(locale: "ru" | "pt" = "ru") {
  const messages = locale === "pt" ? ptMessages : ruMessages;
  return renderWithIntl(
    <AccountClient languageTag={locale === "pt" ? "pt-BR" : "ru"} />,
    {
      locale,
      messages: {
        Auth: messages.Auth,
        Account: messages.Account,
        EmailVerification: messages.EmailVerification
      }
    }
  );
}

describe("direct account authentication and session", () => {
  beforeEach(() => {
    window.localStorage.clear();
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("renders direct login and registration without loading commerce APIs", async () => {
    renderAccountClient();

    expect(
      await screen.findByRole("heading", { name: ruMessages.Auth.dialogTitle })
    ).toBeVisible();
    expect(
      screen.getByRole("heading", { name: ruMessages.Account.title })
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Вход" })
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Регистрация" })
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "Забыли пароль?" })).toHaveAttribute(
      "href",
      "/ru/forgot-password"
    );
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
      await screen.findByRole("heading", { name: ruMessages.Auth.dialogTitle })
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
      await screen.findByRole("heading", { name: ruMessages.Auth.dialogTitle })
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

  it.each([true, false])(
    "presents the generated login user directly (email verified: %s)",
    async (emailVerified) => {
      const sessionChangedListener = vi.fn();
      window.addEventListener(sessionChangedEvent, sessionChangedListener);
      fetchMock.mockResolvedValueOnce(
        jsonResponse({
          status: "authenticated",
          token: "login-token",
          user: { ...accountUser, email_verified: emailVerified }
        })
      );
      const user = userEvent.setup();

      try {
        renderAccountClient();
        await user.type(await screen.findByLabelText("Email"), accountUser.email);
        await user.type(screen.getByLabelText("Пароль"), "existing-password");
        await user.click(
          screen.getByRole("button", { name: "Войти" })
        );

        expect(await screen.findByText(accountUser.email)).toBeVisible();
        expect(window.localStorage.getItem(sessionStorageKey)).toBe("login-token");
        expect(sessionChangedListener).toHaveBeenCalledTimes(1);
        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/api/auth/login");
        const requestBody: unknown = JSON.parse(
          String(fetchMock.mock.calls[0]?.[1]?.body)
        );
        expect(requestBody).toEqual({
          email: accountUser.email,
          password: "existing-password"
        });
        if (emailVerified) {
          expect(
            screen.queryByRole("heading", {
              name: ruMessages.EmailVerification.pending.title
            })
          ).not.toBeInTheDocument();
        } else {
          expect(
            screen.getByRole("heading", {
              name: ruMessages.EmailVerification.pending.title
            })
          ).toBeVisible();
        }
      } finally {
        window.removeEventListener(sessionChangedEvent, sessionChangedListener);
      }
    }
  );

  it("registers with both explicit legal confirmations and canonical pt-BR metadata", async () => {
    const password = 'Valid1! Юникод "quote";';
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: "registered",
        token: "registered-token",
        user: { ...accountUser, email_verified: false }
      })
    );
    const user = userEvent.setup();
    renderAccountClient("pt");

    await user.click(
      await screen.findByRole("button", {
        name: ptMessages.Auth.modes.register
      })
    );
    await user.type(
      screen.getByLabelText(ptMessages.Auth.fields.emailLabel),
      accountUser.email
    );
    await user.type(
      screen.getByLabelText(ptMessages.Auth.fields.passwordLabel),
      password
    );
    await user.type(
      screen.getByLabelText(ptMessages.Auth.fields.passwordConfirmLabel),
      password
    );
    const submit = screen.getAllByRole("button", {
      name: ptMessages.Auth.actions.createAccount
    })[1];
    await user.click(submit);
    expect(
      screen.getByText(ptMessages.Auth.validation.personalConsentRequired)
    ).toBeVisible();
    expect(fetchMock).not.toHaveBeenCalled();
    const checkboxes = screen.getAllByRole("checkbox");
    await user.click(checkboxes[0]);
    await user.click(submit);
    expect(
      screen.getByText(ptMessages.Auth.validation.offerConsentRequired)
    ).toBeVisible();
    expect(fetchMock).not.toHaveBeenCalled();
    await user.click(checkboxes[1]);
    await user.click(submit);

    expect(await screen.findByText(accountUser.email)).toBeVisible();
    expect(
      screen.getByRole("heading", {
        name: ptMessages.EmailVerification.pending.title
      })
    ).toBeVisible();
    expect(window.localStorage.getItem(sessionStorageKey)).toBe("registered-token");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/api/auth/register");
    const requestBody: unknown = JSON.parse(
      String(fetchMock.mock.calls[0]?.[1]?.body)
    );
    expect(requestBody).toEqual({
      email: accountUser.email,
      password,
      personal_consent: true,
      offer_consent: true
    });
    expect(fetchMock.mock.calls[0]?.[1]?.headers).toMatchObject({
      "Accept-Language": "pt-BR"
    });
  });

  it("rejects invalid JSON auth success without storing a bearer", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("invalid-json", { status: 200 })
    );
    const user = userEvent.setup();
    renderAccountClient();
    await user.type(await screen.findByLabelText("Email"), accountUser.email);
    await user.type(screen.getByLabelText("Пароль"), "existing-password");
    await user.click(
      screen.getByRole("button", { name: "Войти" })
    );

    expect(await screen.findByText(ruMessages.Auth.errors.contract)).toBeVisible();
    expect(window.localStorage.getItem(sessionStorageKey)).toBeNull();
    expect(screen.getByLabelText("Email")).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("clears only the current bearer on a session 401 and dispatches the session change", async () => {
    const sessionChangedListener = vi.fn();
    window.addEventListener(sessionChangedEvent, sessionChangedListener);
    window.localStorage.setItem(sessionStorageKey, "session-token");
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "unauthorized" }, 401));

    try {
      renderAccountClient();

      expect(
        await screen.findByRole("heading", { name: ruMessages.Auth.dialogTitle })
      ).toBeVisible();
      expect(window.localStorage.getItem(sessionStorageKey)).toBeNull();
      expect(sessionChangedListener).toHaveBeenCalledTimes(1);
      expect(fetchMock).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener(sessionChangedEvent, sessionChangedListener);
    }
  });

  it.each([
    [
      "500",
      () => jsonResponse({ detail: { code: "internal_server_error" } }, 500)
    ],
    ["503", () => jsonResponse({ detail: "unavailable" }, 503)],
    ["invalid JSON", () => new Response("invalid-json", { status: 200 })]
  ])(
    "preserves the bearer and offers retry after a session %s",
    async (_label, response) => {
      window.localStorage.setItem(sessionStorageKey, "session-token");
      fetchMock.mockResolvedValueOnce(response());
      renderAccountClient();

      expect(await screen.findByRole("alert")).toHaveTextContent(
        ruMessages.Account.sessionError.notice
      );
      expect(
        screen.getByRole("button", {
          name: ruMessages.Account.sessionError.retryAction
        })
      ).toBeVisible();
      expect(window.localStorage.getItem(sessionStorageKey)).toBe("session-token");
      expect(
        screen.queryByRole("heading", { name: ruMessages.Auth.dialogTitle })
      ).not.toBeInTheDocument();
      expect(fetchMock).toHaveBeenCalledTimes(1);
    }
  );

  it.each([
    ["network failure", new TypeError("network unavailable")],
    ["abort", new DOMException("Request aborted", "AbortError")]
  ])(
    "preserves the bearer and offers retry after a session %s",
    async (_label, error) => {
      window.localStorage.setItem(sessionStorageKey, "session-token");
      fetchMock.mockRejectedValueOnce(error);
      renderAccountClient();

      expect(await screen.findByRole("alert")).toHaveTextContent(
        ruMessages.Account.sessionError.notice
      );
      expect(window.localStorage.getItem(sessionStorageKey)).toBe("session-token");
      expect(
        screen.queryByRole("heading", { name: ruMessages.Auth.dialogTitle })
      ).not.toBeInTheDocument();
    }
  );

  it("keeps the bearer when the session request times out", async () => {
    vi.useFakeTimers();
    window.localStorage.setItem(sessionStorageKey, "session-token");
    fetchMock.mockImplementationOnce(
      (_input, init) => new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => reject(new DOMException("Request aborted", "AbortError")),
          { once: true }
        );
      })
    );
    renderAccountClient();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(requestTimeoutMs);
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      ruMessages.Account.sessionError.notice
    );
    expect(window.localStorage.getItem(sessionStorageKey)).toBe("session-token");
    expect(
      screen.queryByRole("heading", { name: ruMessages.Auth.dialogTitle })
    ).not.toBeInTheDocument();
  });

  it("retries only the session read after a transient failure", async () => {
    const sessionChangedListener = vi.fn();
    window.addEventListener(sessionChangedEvent, sessionChangedListener);
    window.localStorage.setItem(sessionStorageKey, "session-token");
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ detail: "unavailable" }, 503))
      .mockResolvedValueOnce(sessionResponse());
    const user = userEvent.setup();

    try {
      renderAccountClient();
      await user.click(
        await screen.findByRole("button", {
          name: ruMessages.Account.sessionError.retryAction
        })
      );

      expect(await screen.findByText(accountUser.email)).toBeVisible();
      expect(window.localStorage.getItem(sessionStorageKey)).toBe("session-token");
      expect(fetchMock).toHaveBeenCalledTimes(2);
      for (const [url, init] of fetchMock.mock.calls) {
        expect(String(url)).toContain("/api/auth/session");
        expect(init?.method).toBeUndefined();
        expect(init?.headers).toEqual({ Authorization: "Bearer session-token" });
      }
      expect(sessionChangedListener).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener(sessionChangedEvent, sessionChangedListener);
    }
  });

  it("shows a retryable error after a session refresh fails instead of showing login", async () => {
    window.localStorage.setItem(sessionStorageKey, "session-token");
    fetchMock
      .mockResolvedValueOnce(sessionResponse())
      .mockRejectedValueOnce(new TypeError("network unavailable"));
    renderAccountClient();
    expect(await screen.findByText(accountUser.email)).toBeVisible();

    act(() => window.dispatchEvent(new Event(sessionChangedEvent)));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      ruMessages.Account.sessionError.notice
    );
    expect(window.localStorage.getItem(sessionStorageKey)).toBe("session-token");
    expect(
      screen.queryByRole("heading", { name: ruMessages.Auth.dialogTitle })
    ).not.toBeInTheDocument();
  });

  it.each(["success", "401"])("ignores a stale session %s after a newer login event", async (result) => {
    const oldSession = deferredResponse();
    const sessionChangedListener = vi.fn();
    window.addEventListener(sessionChangedEvent, sessionChangedListener);
    window.localStorage.setItem(sessionStorageKey, "old-token");
    fetchMock
      .mockReturnValueOnce(oldSession.promise)
      .mockResolvedValueOnce(sessionResponse("new@example.com"));

    try {
      renderAccountClient();
      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      window.localStorage.setItem(sessionStorageKey, "new-token");
      act(() => window.dispatchEvent(new Event(sessionChangedEvent)));
      expect(await screen.findByText("new@example.com")).toBeVisible();

      await act(async () => {
        oldSession.resolveResponse(result === "401"
          ? jsonResponse({ detail: "unauthorized" }, 401)
          : sessionResponse("old@example.com"));
      });

      expect(window.localStorage.getItem(sessionStorageKey)).toBe("new-token");
      expect(screen.getByText("new@example.com")).toBeVisible();
      expect(screen.queryByText("old@example.com")).not.toBeInTheDocument();
      expect(sessionChangedListener).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener(sessionChangedEvent, sessionChangedListener);
    }
  });

  it.each(["success", "401"])("ignores a stale session %s when storage changed without an event", async (result) => {
    const oldSession = deferredResponse();
    window.localStorage.setItem(sessionStorageKey, "old-token");
    fetchMock.mockReturnValueOnce(oldSession.promise);
    renderAccountClient();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    window.localStorage.setItem(sessionStorageKey, "new-token");

    await act(async () => {
      oldSession.resolveResponse(result === "401"
        ? jsonResponse({ detail: "unauthorized" }, 401)
        : sessionResponse("old@example.com"));
    });

    expect(window.localStorage.getItem(sessionStorageKey)).toBe("new-token");
    expect(screen.queryByText("old@example.com")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: ruMessages.Auth.dialogTitle })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(ruMessages.Account.loading);
  });

  it("ignores an older session 401 after a newer read of the same bearer succeeds", async () => {
    const oldSession = deferredResponse();
    window.localStorage.setItem(sessionStorageKey, "session-token");
    fetchMock
      .mockReturnValueOnce(oldSession.promise)
      .mockResolvedValueOnce(sessionResponse());
    renderAccountClient();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    act(() => window.dispatchEvent(new Event(sessionChangedEvent)));
    expect(await screen.findByText(accountUser.email)).toBeVisible();

    await act(async () => {
      oldSession.resolveResponse(jsonResponse({ detail: "unauthorized" }, 401));
    });

    expect(window.localStorage.getItem(sessionStorageKey)).toBe("session-token");
    expect(screen.getByText(accountUser.email)).toBeVisible();
  });

  it("does not clear a bearer for a session 401 after unmount", async () => {
    const oldSession = deferredResponse();
    window.localStorage.setItem(sessionStorageKey, "session-token");
    fetchMock.mockReturnValueOnce(oldSession.promise);
    const { unmount } = renderAccountClient();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    unmount();

    await act(async () => {
      oldSession.resolveResponse(jsonResponse({ detail: "unauthorized" }, 401));
    });

    expect(window.localStorage.getItem(sessionStorageKey)).toBe("session-token");
  });

  it.each(["server failure", "network failure"])("clears the matching local bearer when logout encounters a %s", async (failure) => {
    window.localStorage.setItem(sessionStorageKey, "session-token");
    fetchMock.mockResolvedValueOnce(sessionResponse());
    if (failure === "server failure") {
      fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "unavailable" }, 503));
    } else {
      fetchMock.mockRejectedValueOnce(new TypeError("network unavailable"));
    }
    const sessionChangedListener = vi.fn();
    window.addEventListener(sessionChangedEvent, sessionChangedListener);
    const user = userEvent.setup();

    try {
      renderAccountClient();
      await user.click(await screen.findByRole("button", { name: "Выйти" }));

      expect(await screen.findByRole("heading", { name: ruMessages.Auth.dialogTitle })).toBeVisible();
      expect(window.localStorage.getItem(sessionStorageKey)).toBeNull();
      expect(sessionChangedListener).toHaveBeenCalledTimes(1);
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(String(fetchMock.mock.calls[1]?.[0])).toContain("/api/auth/logout");
      expect(fetchMock.mock.calls[1]?.[1]?.headers).toMatchObject({ Authorization: "Bearer session-token" });
    } finally {
      window.removeEventListener(sessionChangedEvent, sessionChangedListener);
    }
  });

  it("preserves a newer login when an older logout finishes", async () => {
    const oldLogout = deferredResponse();
    window.localStorage.setItem(sessionStorageKey, "old-token");
    fetchMock
      .mockResolvedValueOnce(sessionResponse("old@example.com"))
      .mockReturnValueOnce(oldLogout.promise)
      .mockResolvedValueOnce(sessionResponse("new@example.com"));
    const user = userEvent.setup();
    renderAccountClient();
    await user.click(await screen.findByRole("button", { name: "Выйти" }));
    window.localStorage.setItem(sessionStorageKey, "new-token");
    act(() => window.dispatchEvent(new Event(sessionChangedEvent)));
    expect(await screen.findByText("new@example.com")).toBeVisible();

    await act(async () => {
      oldLogout.resolveResponse(jsonResponse({ status: "logged_out" }));
    });

    expect(window.localStorage.getItem(sessionStorageKey)).toBe("new-token");
    expect(screen.getByText("new@example.com")).toBeVisible();
    expect(screen.queryByRole("heading", { name: ruMessages.Auth.dialogTitle })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Выйти" })).toBeEnabled();
  });
});
