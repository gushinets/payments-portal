import { HttpResponse, http } from "msw";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { storeSessionToken } from "../helpers/storage";
import { server } from "../setup/msw-server";
import { AccountClient } from "@/features/account";

const apiBase = "http://localhost:8000";
const sessionChangedEvent = "anytoolai_session_changed";
const sessionTokenStorageKey = "anytoolai_session_token_v1";
const accountEmail = "buyer@example.com";

type ProductStatus = "inactive" | "pending" | "active" | "failed";

function sessionPayload(
  state: ReturnType<typeof productSessionState> | null = null
) {
  return {
    authenticated: true,
    user: {
      tenant_id: "anytoolai",
      region: "ru",
      user_id: "11111111-1111-4111-8111-111111111111",
      email: accountEmail
    },
    product_state: state
  };
}

function productSessionState(productCode: string, status: ProductStatus) {
  return {
    product_code: productCode,
    plan_code: `${productCode}-pro`,
    plan_name: `${productCode} Pro`,
    invoice_id: null,
    transaction_id: status === "active" ? `tx-${productCode}` : null,
    status,
    starts_at: status === "active" ? "2026-08-19T10:00:00Z" : null,
    expires_at: status === "active" ? "2026-09-19T10:00:00Z" : null
  };
}

function productCard(productName: string) {
  const heading = screen.getByRole("heading", { name: productName });
  const card = heading.closest("article");
  expect(card).not.toBeNull();
  return within(card as HTMLElement);
}

function dispatchSessionChanged() {
  act(() => {
    window.dispatchEvent(new Event(sessionChangedEvent));
  });
}

it("shows account and product states when every session request succeeds", async () => {
  storeSessionToken("session-token");
  server.use(
    http.get(`${apiBase}/api/auth/session`, ({ request }) => {
      expect(request.headers.get("authorization")).toBe("Bearer session-token");
      const productCode = new URL(request.url).searchParams.get("product");

      if (productCode === "document-summary") {
        return HttpResponse.json(
          sessionPayload(productSessionState(productCode, "active"))
        );
      }

      if (productCode === "prompt-optimizer") {
        return HttpResponse.json(
          sessionPayload(productSessionState(productCode, "inactive"))
        );
      }

      return HttpResponse.json(sessionPayload());
    })
  );

  render(<AccountClient />);

  expect(await screen.findByText(accountEmail)).toBeVisible();
  await waitFor(() => {
    expect(
      productCard("Document Summary").getByText("Подписка активна")
    ).toBeVisible();
    expect(
      productCard("Prompt Optimizer").getByText("Подписка не активна")
    ).toBeVisible();
  });
});

it("keeps loaded account data and reports a partial product-state failure", async () => {
  storeSessionToken("session-token");
  server.use(
    http.get(`${apiBase}/api/auth/session`, ({ request }) => {
      expect(request.headers.get("authorization")).toBe("Bearer session-token");
      const productCode = new URL(request.url).searchParams.get("product");

      if (productCode === "document-summary") {
        return new HttpResponse(null, { status: 504 });
      }

      if (productCode === "prompt-optimizer") {
        return HttpResponse.json(
          sessionPayload(productSessionState(productCode, "active"))
        );
      }

      return HttpResponse.json(sessionPayload());
    })
  );

  render(<AccountClient />);

  expect(await screen.findByText(accountEmail)).toBeVisible();
  expect(await screen.findByRole("status")).toHaveTextContent(
    "Не удалось загрузить статусы части подписок. Обновите страницу."
  );
  expect(
    productCard("Prompt Optimizer").getByText("Подписка активна")
  ).toBeVisible();
  expect(
    productCard("Document Summary").getByText("Статус подписки не загружен")
  ).toBeVisible();
  expect(
    productCard("Document Summary").queryByText("Подписка не активна")
  ).not.toBeInTheDocument();
});

it("keeps an existing active product state when refresh for that product fails", async () => {
  let failDocumentSummary = false;
  storeSessionToken("session-token");
  server.use(
    http.get(`${apiBase}/api/auth/session`, ({ request }) => {
      expect(request.headers.get("authorization")).toBe("Bearer session-token");
      const productCode = new URL(request.url).searchParams.get("product");

      if (productCode === "document-summary") {
        return failDocumentSummary
          ? new HttpResponse(null, { status: 504 })
          : HttpResponse.json(
              sessionPayload(productSessionState(productCode, "active"))
            );
      }

      if (productCode === "prompt-optimizer") {
        return HttpResponse.json(
          sessionPayload(productSessionState(productCode, "inactive"))
        );
      }

      return HttpResponse.json(sessionPayload());
    })
  );

  render(<AccountClient />);

  expect(await screen.findByText(accountEmail)).toBeVisible();
  await waitFor(() => {
    expect(
      productCard("Document Summary").getByText("Подписка активна")
    ).toBeVisible();
  });

  failDocumentSummary = true;
  dispatchSessionChanged();

  expect(await screen.findByRole("status")).toHaveTextContent(
    "Не удалось загрузить статусы части подписок. Обновите страницу."
  );
  expect(
    productCard("Document Summary").getByText("Подписка активна")
  ).toBeVisible();
});

it("clears the partial product-state notice after a fully successful refresh", async () => {
  let failPromptOptimizer = true;
  storeSessionToken("session-token");
  server.use(
    http.get(`${apiBase}/api/auth/session`, ({ request }) => {
      expect(request.headers.get("authorization")).toBe("Bearer session-token");
      const productCode = new URL(request.url).searchParams.get("product");

      if (productCode === "document-summary") {
        return HttpResponse.json(
          sessionPayload(productSessionState(productCode, "active"))
        );
      }

      if (productCode === "prompt-optimizer") {
        return failPromptOptimizer
          ? new HttpResponse(null, { status: 504 })
          : HttpResponse.json(
              sessionPayload(productSessionState(productCode, "inactive"))
            );
      }

      return HttpResponse.json(sessionPayload());
    })
  );

  render(<AccountClient />);

  expect(await screen.findByText(accountEmail)).toBeVisible();
  expect(await screen.findByRole("status")).toHaveTextContent(
    "Не удалось загрузить статусы части подписок. Обновите страницу."
  );

  failPromptOptimizer = false;
  dispatchSessionChanged();

  await waitFor(() => {
    expect(
      screen.queryByText(
        "Не удалось загрузить статусы части подписок. Обновите страницу."
      )
    ).not.toBeInTheDocument();
    expect(
      productCard("Prompt Optimizer").getByText("Подписка не активна")
    ).toBeVisible();
  });
});

it("keeps base session failure as a fatal account error", async () => {
  storeSessionToken("session-token");
  server.use(
    http.get(`${apiBase}/api/auth/session`, ({ request }) => {
      expect(request.headers.get("authorization")).toBe("Bearer session-token");
      return new HttpResponse(null, { status: 500 });
    })
  );

  render(<AccountClient />);

  expect(
    await screen.findByText("Не удалось загрузить аккаунт. Войдите ещё раз.")
  ).toBeVisible();
  expect(screen.queryByText(accountEmail)).not.toBeInTheDocument();
  expect(window.localStorage.getItem(sessionTokenStorageKey)).toBeNull();
});

it("keeps invalid base session payload as a fatal account error", async () => {
  storeSessionToken("session-token");
  server.use(
    http.get(`${apiBase}/api/auth/session`, ({ request }) => {
      expect(request.headers.get("authorization")).toBe("Bearer session-token");
      return HttpResponse.json({
        authenticated: true,
        user: {
          email: accountEmail
        },
        product_state: null
      });
    })
  );

  render(<AccountClient />);

  expect(
    await screen.findByText("Не удалось загрузить аккаунт. Войдите ещё раз.")
  ).toBeVisible();
  expect(screen.queryByText(accountEmail)).not.toBeInTheDocument();
  expect(window.localStorage.getItem(sessionTokenStorageKey)).toBeNull();
});

it("clears local session state and announces logout", async () => {
  const user = userEvent.setup();
  const sessionChanged = vi.fn();
  const originalConsoleError = console.error;
  const consoleError = vi
    .spyOn(console, "error")
    .mockImplementation((...args) => {
      if (
        String(args[0]).includes(
          "Not implemented: navigation (except hash changes)"
        )
      ) {
        return;
      }
      originalConsoleError(...args);
    });
  window.addEventListener(sessionChangedEvent, sessionChanged, {
    once: true
  });
  storeSessionToken("session-token");
  server.use(
    http.get(`${apiBase}/api/auth/session`, ({ request }) => {
      expect(request.headers.get("authorization")).toBe("Bearer session-token");
      return HttpResponse.json(sessionPayload());
    })
  );

  render(<AccountClient />);

  expect(await screen.findByText(accountEmail)).toBeVisible();
  try {
    await user.click(screen.getByRole("button", { name: /Выйти/ }));
  } finally {
    consoleError.mockRestore();
  }

  await waitFor(() => {
    expect(window.localStorage.getItem(sessionTokenStorageKey)).toBeNull();
  });
  expect(sessionChanged).toHaveBeenCalledOnce();
});
