import "@testing-library/jest-dom/vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  requestTimeoutMs,
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
    vi.useRealTimers();
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
      render(<HeaderAccount />);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(requestSignals[0]?.aborted).toBe(false);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(requestTimeoutMs);
      });

      expect(requestSignals[0]?.aborted).toBe(true);
      expect(screen.getByRole("button", { name: "Войти" })).toBeEnabled();
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
