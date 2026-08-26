import { HttpResponse, http } from "msw";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { storeSessionToken } from "../helpers/storage";
import { server } from "../setup/msw-server";
import { AccountClient } from "@/features/account";

const apiBase = "http://localhost:8000";

it("clears local session state and announces logout", async () => {
  const user = userEvent.setup();
  const sessionChanged = vi.fn();
  const originalConsoleError = console.error;
  const consoleError = vi.spyOn(console, "error").mockImplementation((...args) => {
    if (String(args[0]).includes("Not implemented: navigation (except hash changes)")) {
      return;
    }
    originalConsoleError(...args);
  });
  window.addEventListener("anytoolai_session_changed", sessionChanged, {
    once: true
  });
  storeSessionToken("session-token");
  server.use(
    http.get(`${apiBase}/api/auth/session`, ({ request }) => {
      expect(request.headers.get("authorization")).toBe("Bearer session-token");
      return HttpResponse.json({
        authenticated: true,
        user: {
          tenant_id: "anytoolai",
          region: "ru",
          user_id: "11111111-1111-4111-8111-111111111111",
          email: "buyer@example.com"
        },
        product_state: null
      });
    })
  );

  render(<AccountClient />);

  expect(await screen.findByText("buyer@example.com")).toBeVisible();
  try {
    await user.click(screen.getByRole("button", { name: /Выйти/ }));
  } finally {
    consoleError.mockRestore();
  }

  await waitFor(() => {
    expect(window.localStorage.getItem("anytoolai_session_token_v1")).toBeNull();
  });
  expect(sessionChanged).toHaveBeenCalledOnce();
});

it("keeps the account summary available when product state loading fails", async () => {
  const sessionChanged = vi.fn();
  window.addEventListener("anytoolai_session_changed", sessionChanged);
  storeSessionToken("session-token");
  server.use(
    http.get(`${apiBase}/api/auth/session`, ({ request }) => {
      expect(request.headers.get("authorization")).toBe("Bearer session-token");
      const url = new URL(request.url);
      if (url.searchParams.has("product")) {
        return new HttpResponse(null, { status: 504 });
      }
      return HttpResponse.json({
        authenticated: true,
        user: {
          tenant_id: "anytoolai",
          region: "ru",
          user_id: "11111111-1111-4111-8111-111111111111",
          email: "buyer@example.com"
        },
        product_state: null
      });
    })
  );

  render(<AccountClient />);

  expect(await screen.findByText("buyer@example.com")).toBeVisible();
  expect(screen.getByRole("button", { name: /Выйти/ })).toBeVisible();
  expect(window.localStorage.getItem("anytoolai_session_token_v1")).toBe(
    "session-token"
  );
  expect(sessionChanged).not.toHaveBeenCalled();
  window.removeEventListener("anytoolai_session_changed", sessionChanged);
});
