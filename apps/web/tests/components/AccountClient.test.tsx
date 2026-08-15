import { HttpResponse, http } from "msw";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { storeSessionToken } from "../helpers/storage";
import { server } from "../setup/msw-server";
import { AccountClient } from "@/features/account";

const apiBase = "http://localhost:8000";

it("clears the session and uses Next navigation on logout", async () => {
  const user = userEvent.setup();
  const routerPush = vi.fn();
  globalThis.__NEXT_ROUTER_PUSH__ = routerPush;
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
  await user.click(screen.getByRole("button", { name: /Выйти/ }));

  await waitFor(() => {
    expect(window.localStorage.getItem("anytoolai_session_token_v1")).toBeNull();
  });
  expect(routerPush).toHaveBeenCalledWith("/ru");
});
