import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import ruMessages from "@/messages/ru.json";
import {
  requestTimeoutMs,
  sessionChangedEvent,
  sessionStorageKey
} from "@/shared/api/auth";
import { HeaderAccount } from "@/shared/ui/HeaderAccount";
import { renderWithIntl } from "../setup/render-with-intl";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

function renderHeaderAccount() {
  return renderWithIntl(<HeaderAccount languageTag="ru" />, {
    locale: "ru",
    messages: {
      Auth: ruMessages.Auth,
      EmailVerification: ruMessages.EmailVerification
    }
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
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it.each([true, false])("submits modal login once with Enter (email verified: %s)", async (emailVerified) => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input) => jsonResponse(
      String(input).endsWith("/api/auth/login")
        ? {
          status: "authenticated",
          token: "modal-token",
          user: {
            tenant_id: "anytoolai", region: "ru",
            user_id: "11111111-1111-4111-8111-111111111111",
            email: "modal@example.com", email_verified: emailVerified
          }
        }
        : {
          authenticated: true,
          user: {
            tenant_id: "anytoolai", region: "ru",
            user_id: "11111111-1111-4111-8111-111111111111",
            email: "modal@example.com", email_verified: emailVerified
          }
        }
    ));
    renderHeaderAccount();
    await user.click(await screen.findByRole("button", { name: "Войти" }));
    await user.type(screen.getByLabelText("Email"), "modal@example.com");
    await user.type(screen.getByLabelText("Пароль"), "password-123{Enter}");

    expect(await screen.findByText("modal@example.com")).toBeVisible();
    expect(window.localStorage.getItem(sessionStorageKey)).toBe("modal-token");
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/auth/login"))).toHaveLength(1);
    if (emailVerified) {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    } else {
      expect(screen.getByRole("heading", { name: ruMessages.EmailVerification.pending.title })).toBeVisible();
      expect(screen.getByRole("dialog").querySelector("form")).toBeNull();
    }
  });

  it("retains the trusted session when a successful response has invalid JSON syntax", async () => {
    window.localStorage.setItem(sessionStorageKey, "session-token");
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({
          authenticated: true,
          user: {
            tenant_id: "anytoolai",
            region: "ru",
            user_id: "11111111-1111-4111-8111-111111111111",
            email: "header@example.com",
            email_verified: true
          }
        })
      )
      .mockResolvedValueOnce(
        new Response("not-json", { status: 200 })
      );

    renderHeaderAccount();

    expect(await screen.findByText("header@example.com")).toBeVisible();

    act(() => {
      window.dispatchEvent(new Event(sessionChangedEvent));
    });

    await waitFor(() =>
      expect(window.localStorage.getItem(sessionStorageKey)).toBe("session-token")
    );
    expect(await screen.findByText("header@example.com")).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("clears the trusted session and dispatches a session change after a 401", async () => {
    const sessionChangedListener = vi.fn();
    window.addEventListener(sessionChangedEvent, sessionChangedListener);
    window.localStorage.setItem(sessionStorageKey, "session-token");
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "unauthorized" }, 401));

    try {
      renderHeaderAccount();

      await waitFor(() =>
        expect(window.localStorage.getItem(sessionStorageKey)).toBeNull()
      );
      expect(sessionChangedListener).toHaveBeenCalledTimes(1);
      expect(await screen.findByRole("button", { name: "Войти" })).toBeVisible();
    } finally {
      window.removeEventListener(sessionChangedEvent, sessionChangedListener);
    }
  });

  it("ignores a stale 401 after the bearer changes", async () => {
    const sessionChangedListener = vi.fn();
    let resolveSession: (response: Response) => void = () => undefined;
    const sessionRequest = new Promise<Response>((resolve) => {
      resolveSession = resolve;
    });

    window.addEventListener(sessionChangedEvent, sessionChangedListener);
    window.localStorage.setItem(sessionStorageKey, "token-a");
    fetchMock.mockReturnValueOnce(sessionRequest);

    try {
      renderHeaderAccount();

      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      window.localStorage.setItem(sessionStorageKey, "token-b");

      await act(async () => {
        resolveSession(jsonResponse({ detail: "unauthorized" }, 401));
      });

      expect(window.localStorage.getItem(sessionStorageKey)).toBe("token-b");
      expect(sessionChangedListener).not.toHaveBeenCalled();
      expect(screen.queryByRole("button", { name: "Войти" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Аккаунт" })).toBeDisabled();
    } finally {
      window.removeEventListener(sessionChangedEvent, sessionChangedListener);
    }
  });

  it("ignores a stale successful response after the bearer changes", async () => {
    let resolveSession: (response: Response) => void = () => undefined;
    const sessionRequest = new Promise<Response>((resolve) => {
      resolveSession = resolve;
    });

    window.localStorage.setItem(sessionStorageKey, "token-a");
    fetchMock.mockReturnValueOnce(sessionRequest);

    renderHeaderAccount();

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    window.localStorage.setItem(sessionStorageKey, "token-b");

    await act(async () => {
      resolveSession(
        jsonResponse({
          authenticated: true,
          user: {
            tenant_id: "anytoolai",
            region: "ru",
            user_id: "22222222-2222-4222-8222-222222222222",
            email: "user-a@example.com",
            email_verified: true
          }
        })
      );
    });

    expect(screen.queryByText("user-a@example.com")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Аккаунт" })).toBeDisabled();
  });

  it("retains the trusted session after a transient 500 response", async () => {
    const sessionChangedListener = vi.fn();
    window.addEventListener(sessionChangedEvent, sessionChangedListener);
    window.localStorage.setItem(sessionStorageKey, "session-token");
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: { code: "internal_server_error" } }, 500)
    );

    try {
      renderHeaderAccount();

      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      expect(window.localStorage.getItem(sessionStorageKey)).toBe("session-token");
      expect(sessionChangedListener).not.toHaveBeenCalled();
      expect(screen.getByRole("button", { name: "Аккаунт" })).not.toBeDisabled();
      expect(screen.queryByRole("button", { name: "Войти" })).not.toBeInTheDocument();

      fetchMock.mockResolvedValueOnce(
        jsonResponse({
          authenticated: true,
          user: {
            tenant_id: "anytoolai",
            region: "ru",
            user_id: "11111111-1111-4111-8111-111111111111",
            email: "header@example.com",
            email_verified: true
          }
        })
      );
      fireEvent.click(screen.getByRole("button", { name: "Аккаунт" }));

      expect(await screen.findByText("header@example.com")).toBeVisible();
      expect(fetchMock).toHaveBeenCalledTimes(2);
    } finally {
      window.removeEventListener(sessionChangedEvent, sessionChangedListener);
    }
  });

  it("retains the trusted session during a transient network failure", async () => {
    window.localStorage.setItem(sessionStorageKey, "session-token");
    fetchMock.mockRejectedValueOnce(new TypeError("network unavailable"));

    renderHeaderAccount();

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(window.localStorage.getItem(sessionStorageKey)).toBe("session-token");
    expect(screen.getByRole("button", { name: "Аккаунт" })).not.toBeDisabled();
    expect(screen.queryByRole("button", { name: "Войти" })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("times out while reading a stalled successful response body", async () => {
    vi.useFakeTimers();
    window.localStorage.setItem(sessionStorageKey, "session-token");
    const sessionChangedListener = vi.fn();
    const requestSignals: AbortSignal[] = [];
    let bodyController: ReadableStreamDefaultController<Uint8Array> | undefined;
    let bodySettled = false;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        bodyController = controller;
      }
    });

    window.addEventListener(sessionChangedEvent, sessionChangedListener);
    fetchMock.mockImplementationOnce(async (_input, init) => {
      if (!(init?.signal instanceof AbortSignal)) {
        throw new Error("expected request abort signal");
      }

      requestSignals.push(init.signal);
      init.signal.addEventListener(
        "abort",
        () => {
          bodySettled = true;
          bodyController?.error(
            new DOMException("Request aborted", "AbortError")
          );
        },
        { once: true }
      );

      return new Response(body, {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    });

    try {
      renderHeaderAccount();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(requestSignals[0]?.aborted).toBe(false);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(requestTimeoutMs);
      });

      expect(requestSignals[0]?.aborted).toBe(true);
      expect(screen.getByRole("button", { name: "Аккаунт" })).not.toBeDisabled();
      expect(screen.queryByRole("button", { name: "Войти" })).not.toBeInTheDocument();
      expect(window.localStorage.getItem(sessionStorageKey)).toBe(
        "session-token"
      );
      expect(sessionChangedListener).not.toHaveBeenCalled();
      expect(fetchMock).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener(sessionChangedEvent, sessionChangedListener);
      if (!bodySettled) {
        bodyController?.error(new DOMException("Test cleanup", "AbortError"));
      }
    }
  });
});
