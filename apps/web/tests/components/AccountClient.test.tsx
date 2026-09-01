import { HttpResponse, http, type JsonBodyType } from "msw";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { storeSessionToken } from "../helpers/storage";
import { server } from "../setup/msw-server";
import { AccountClient } from "@/features/account";

const apiBase = "http://localhost:8000";
const sessionChangedEvent = "anytoolai_session_changed";
const sessionTokenStorageKey = "anytoolai_session_token_v1";
const accountEmail = "buyer@example.com";
const documentProductId = "11111111-1111-4111-8111-111111111111";
const optimizerProductId = "22222222-2222-4222-8222-222222222222";

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

function catalogProduct(
  productId: string,
  code: string,
  name: string,
  planCode: string,
  priceAmountMinor = 99000
) {
  return {
    product_id: productId,
    code,
    name,
    description: `${name} backend description`,
    plan: {
      plan_id: `${productId.slice(0, 8)}-3333-4333-8333-333333333333`,
      code: planCode,
      name: `${name} Plan`,
      price_amount_minor: priceAmountMinor,
      currency: "RUB",
      billing_period: "month",
      renewal_mode: "manual",
      trial_days: 7
    }
  };
}

function subscriptionPayload(
  productId: string,
  overrides: Record<string, unknown> = {}
) {
  const now = Date.now();
  return {
    subscriptions: [
      {
        subscription_id: "44444444-4444-4444-8444-444444444444",
        plan: {
          plan_id: "33333333-3333-4333-8333-333333333333",
          code: "document-summary-pro",
          name: "Backend Subscription Plan",
          billing_period: "month"
        },
        scope: {
          scope_type: "product",
          product_id: productId,
          bundle_id: null
        },
        status: "active",
        renewal_mode: "automatic",
        current_period: {
          starts_at: new Date(now - 86400000).toISOString(),
          ends_at: new Date(now + 86400000 * 30).toISOString()
        },
        cancellation: {
          cancel_requested_at: null,
          canceled_at: null
        },
        entitlement_validity: {
          status: "active",
          valid_from: new Date(now - 86400000).toISOString(),
          valid_until: new Date(now + 86400000 * 30).toISOString()
        },
        ...overrides
      }
    ]
  };
}

function subscriptionPayloadWithValidity(
  productId: string,
  status: "active" | "expired" | "revoked",
  validFrom: string,
  validUntil: string
) {
  const payload = subscriptionPayload(productId);
  return {
    subscriptions: [
      {
        ...payload.subscriptions[0],
        entitlement_validity: {
          status,
          valid_from: validFrom,
          valid_until: validUntil
        }
      }
    ]
  };
}

function installCatalogResponse(products = [
  catalogProduct(
    documentProductId,
    "document-summary",
    "Document Summary",
    "document-summary-pro"
  ),
  catalogProduct(
    optimizerProductId,
    "prompt-optimizer",
    "Prompt Optimizer",
    "prompt-optimizer-pro"
  )
]) {
  server.use(
    http.get(`${apiBase}/api/catalog/products`, () =>
      HttpResponse.json({ products })
    )
  );
}

function installSubscriptionsResponse(
  payload: JsonBodyType = { subscriptions: [] }
) {
  server.use(
    http.get(`${apiBase}/api/account/subscriptions`, ({ request }) => {
      expect(request.headers.get("authorization")).toBe("Bearer session-token");
      return HttpResponse.json(payload);
    })
  );
}

beforeEach(() => {
  installCatalogResponse();
  installSubscriptionsResponse();
});

function dispatchSessionChanged() {
  act(() => {
    window.dispatchEvent(new Event(sessionChangedEvent));
  });
}

it("shows account and product states when every session request succeeds", async () => {
  storeSessionToken("session-token");
  installSubscriptionsResponse(subscriptionPayload(documentProductId));
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
  installSubscriptionsResponse(subscriptionPayload(optimizerProductId));
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
  installSubscriptionsResponse(subscriptionPayload(documentProductId));
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
  installSubscriptionsResponse(subscriptionPayload(documentProductId));
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

it("drives account products and price from the catalog API", async () => {
  storeSessionToken("session-token");
  installCatalogResponse([
    catalogProduct(
      "33333333-3333-4333-8333-333333333333",
      "new-backend-product",
      "New Backend Product",
      "new-backend-plan",
      125000
    )
  ]);
  server.use(
    http.get(`${apiBase}/api/auth/session`, () =>
      HttpResponse.json(sessionPayload())
    )
  );

  render(<AccountClient />);

  await screen.findByRole("heading", { name: "New Backend Product" });
  const card = productCard("New Backend Product");
  expect(card.getByText(/1\s250 ₽/)).toBeVisible();
  expect(card.getByText("New Backend Product backend description")).toBeVisible();
  expect(card.queryByText("Document Summary")).not.toBeInTheDocument();
});

it("shows current access and subscription details from a valid entitlement", async () => {
  storeSessionToken("session-token");
  installSubscriptionsResponse(subscriptionPayload(documentProductId));
  server.use(
    http.get(`${apiBase}/api/auth/session`, ({ request }) => {
      const productCode = new URL(request.url).searchParams.get("product");
      return HttpResponse.json(
        sessionPayload(
          productCode === "document-summary"
            ? productSessionState(productCode, "inactive")
            : null
        )
      );
    })
  );

  render(<AccountClient />);

  await screen.findByRole("heading", { name: "Document Summary" });
  const card = productCard("Document Summary");
  expect(await card.findByText("Доступ уже активен")).toBeVisible();
  expect(card.getByText(/Backend\s+Subscription\s+Plan/)).toBeVisible();
  expect(card.getByText(/Продление:\s+автоматически/)).toBeVisible();
  expect(card.queryByRole("link", { name: /Оформить/ })).not.toBeInTheDocument();
  expect(card.getByRole("link", { name: /Управлять/ })).toBeVisible();
});

it("suppresses purchase when product state is active before subscriptions update", async () => {
  storeSessionToken("session-token");
  server.use(
    http.get(`${apiBase}/api/auth/session`, ({ request }) => {
      const productCode = new URL(request.url).searchParams.get("product");
      return HttpResponse.json(
        sessionPayload(
          productCode === "document-summary"
            ? productSessionState(productCode, "active")
            : null
        )
      );
    })
  );

  render(<AccountClient />);

  await screen.findByRole("heading", { name: "Document Summary" });
  const card = productCard("Document Summary");
  expect(await card.findByText("Подписка активна")).toBeVisible();
  expect(card.queryByRole("link", { name: /Оформить/ })).not.toBeInTheDocument();
  expect(card.getByRole("link", { name: /Управлять/ })).toBeVisible();
});

it.each([
  ["expired", "expired", new Date(Date.now() - 86400000), new Date(Date.now() + 86400000)],
  ["revoked", "revoked", new Date(Date.now() - 86400000), new Date(Date.now() + 86400000)],
  ["future", "active", new Date(Date.now() + 86400000), new Date(Date.now() + 172800000)]
] as const)(
  "does not treat %s entitlement as current access",
  async (_label, status, validFrom, validUntil) => {
    storeSessionToken("session-token");
    installSubscriptionsResponse(
      subscriptionPayloadWithValidity(
        documentProductId,
        status,
        validFrom.toISOString(),
        validUntil.toISOString()
      )
    );
    server.use(
      http.get(`${apiBase}/api/auth/session`, () =>
        HttpResponse.json(sessionPayload())
      )
    );

    render(<AccountClient />);

    await screen.findByRole("heading", { name: "Document Summary" });
    const card = productCard("Document Summary");
    expect(await card.findByText("Подписка не активна")).toBeVisible();
    expect(card.getByRole("link", { name: /Оформить/ })).toBeVisible();
    expect(card.queryByText("Доступ уже активен")).not.toBeInTheDocument();
  }
);

it("preserves pending and failed product-state presentation", async () => {
  storeSessionToken("session-token");
  server.use(
    http.get(`${apiBase}/api/auth/session`, ({ request }) => {
      const productCode = new URL(request.url).searchParams.get("product");
      if (productCode === "document-summary") {
        return HttpResponse.json(
          sessionPayload(productSessionState(productCode, "pending"))
        );
      }
      if (productCode === "prompt-optimizer") {
        return HttpResponse.json(
          sessionPayload(productSessionState(productCode, "failed"))
        );
      }
      return HttpResponse.json(sessionPayload());
    })
  );

  render(<AccountClient />);

  await screen.findByRole("heading", { name: "Document Summary" });
  await screen.findByRole("heading", { name: "Prompt Optimizer" });
  expect(
    productCard("Document Summary").getByText(
      "Платёж ожидает подтверждения"
    )
  ).toBeVisible();
  expect(
    productCard("Prompt Optimizer").getByText("Платёж не подтверждён")
  ).toBeVisible();
});

it("handles a catalog decoder failure without showing static products", async () => {
  storeSessionToken("session-token");
  server.use(
    http.get(`${apiBase}/api/auth/session`, () =>
      HttpResponse.json(sessionPayload())
    ),
    http.get(`${apiBase}/api/catalog/products`, () =>
      HttpResponse.json({ products: [{ code: "document-summary" }] })
    )
  );

  render(<AccountClient />);

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Не удалось загрузить каталог"
  );
  expect(screen.queryByRole("heading", { name: "Document Summary" })).not.toBeInTheDocument();
});

it("handles a subscription decoder failure without enabling purchase", async () => {
  storeSessionToken("session-token");
  installSubscriptionsResponse({ subscriptions: [{}] });
  server.use(
    http.get(`${apiBase}/api/auth/session`, () =>
      HttpResponse.json(sessionPayload())
    )
  );

  render(<AccountClient />);

  expect(
    await screen.findByText(
      "Не удалось проверить текущие подписки. Статус доступа временно недоступен."
    )
  ).toBeVisible();
  await screen.findByRole("heading", { name: "Document Summary" });
  const card = productCard("Document Summary");
  expect(
    card.getByText("Статус подписки недоступен. Обновите страницу.")
  ).toBeVisible();
  expect(
    card.queryByText("Проверяем текущую подписку...")
  ).not.toBeInTheDocument();
  expect(card.queryByRole("link", { name: /Оформить/ })).not.toBeInTheDocument();
});

it("does not expose purchase while subscriptions are loading", async () => {
  storeSessionToken("session-token");
  let resolveSubscriptions!: () => void;
  const subscriptionsPending = new Promise<void>((resolve) => {
    resolveSubscriptions = resolve;
  });
  server.use(
    http.get(`${apiBase}/api/account/subscriptions`, async () => {
      await subscriptionsPending;
      return HttpResponse.json({ subscriptions: [] });
    }),
    http.get(`${apiBase}/api/auth/session`, ({ request }) => {
      const productCode = new URL(request.url).searchParams.get("product");
      return HttpResponse.json(
        productCode === "document-summary"
          ? sessionPayload(productSessionState(productCode, "pending"))
          : sessionPayload()
      );
    })
  );

  render(<AccountClient />);

  await screen.findByRole("heading", { name: "Document Summary" });
  const card = productCard("Document Summary");
  expect(await card.findByText("Платёж ожидает подтверждения")).toBeVisible();
  expect(
    card.queryByRole("link", { name: /Оформить/ })
  ).not.toBeInTheDocument();

  await act(async () => {
    resolveSubscriptions();
  });
});

it("offers purchase after subscriptions load without a current entitlement", async () => {
  storeSessionToken("session-token");
  server.use(
    http.get(`${apiBase}/api/auth/session`, () =>
      HttpResponse.json(sessionPayload())
    )
  );

  render(<AccountClient />);

  await screen.findByRole("heading", { name: "Document Summary" });
  const card = productCard("Document Summary");
  expect(await card.findByText("Подписка не активна")).toBeVisible();
  expect(card.getByRole("link", { name: /Оформить/ })).toBeVisible();
});

it("does not expose purchase when subscriptions and product state both fail", async () => {
  storeSessionToken("session-token");
  server.use(
    http.get(
      `${apiBase}/api/account/subscriptions`,
      () => new HttpResponse(null, { status: 500 })
    ),
    http.get(`${apiBase}/api/auth/session`, ({ request }) => {
      const productCode = new URL(request.url).searchParams.get("product");
      return productCode
        ? new HttpResponse(null, { status: 504 })
        : HttpResponse.json(sessionPayload());
    })
  );

  render(<AccountClient />);

  expect(
    await screen.findByText(
      "Не удалось проверить текущие подписки. Статус доступа временно недоступен."
    )
  ).toBeVisible();
  const card = productCard("Document Summary");
  expect(await card.findByText("Статус подписки не загружен")).toBeVisible();
  expect(card.queryByRole("link", { name: /Оформить/ })).not.toBeInTheDocument();
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
