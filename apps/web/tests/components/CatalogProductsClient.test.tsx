import { HttpResponse, delay, http, type JsonBodyType } from "msw";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  CatalogProductsClient,
  decodeCatalogProductsResponse,
  formatCatalogPrice,
  getCatalogProducts
} from "@/features/catalog";
import { requestTimeoutMs } from "@/shared/api/auth";
import {
  decodeAccountSubscriptionsResponse,
  hasCurrentProductEntitlement,
  type AccountSubscription
} from "@/shared/api/subscriptions";
import { server } from "../setup/msw-server";

const apiBase = "http://localhost:8000";
const documentProductId = "11111111-1111-4111-8111-111111111111";
const optimizerProductId = "22222222-2222-4222-8222-222222222222";

function catalogProduct(
  overrides: Record<string, JsonBodyType> = {}
): JsonBodyType {
  return {
    product_id: documentProductId,
    code: "document-summary",
    name: "Document Summary",
    description: "Backend document summary description",
    plan: catalogPlan(),
    ...overrides
  };
}

function catalogPlan(
  overrides: Record<string, JsonBodyType> = {}
): JsonBodyType {
  return {
    plan_id: "33333333-3333-4333-8333-333333333333",
    code: "document-summary-pro",
    name: "Document Summary Pro",
    price_amount_minor: 99000,
    currency: "RUB",
    billing_period: "month",
    renewal_mode: "manual",
    trial_days: 7,
    ...overrides
  };
}

function subscriptionPayload(
  overrides: Partial<AccountSubscription> = {}
): { subscriptions: AccountSubscription[] } {
  const now = Date.now();
  return {
    subscriptions: [
      {
        subscription_id: "44444444-4444-4444-8444-444444444444",
        plan: {
          plan_id: "33333333-3333-4333-8333-333333333333",
          code: "document-summary-pro",
          name: "Document Summary Pro",
          billing_period: "month"
        },
        scope: {
          scope_type: "product",
          product_id: documentProductId,
          bundle_id: null
        },
        status: "active",
        renewal_mode: "manual",
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

function installCatalogResponse(
  payload: JsonBodyType = { products: [catalogProduct()] }
) {
  server.use(
    http.get(`${apiBase}/api/catalog/products`, () =>
      HttpResponse.json(payload)
    )
  );
}

function installSubscriptionResponse(payload: JsonBodyType) {
  server.use(
    http.get(`${apiBase}/api/account/subscriptions`, ({ request }) => {
      expect(request.headers.get("authorization")).toBe("Bearer session-token");
      return HttpResponse.json(payload);
    })
  );
}

it("renders products and commercial fields from the catalog API", async () => {
  installCatalogResponse({
    products: [
      catalogProduct({
        name: "Backend Summary",
        plan: {
          plan_id: "33333333-3333-4333-8333-333333333333",
          code: "backend-summary-plan",
          name: "Backend Summary Plan",
          price_amount_minor: 125000,
          currency: "RUB",
          billing_period: "month",
          renewal_mode: "automatic",
          trial_days: 14
        }
      })
    ]
  });

  render(<CatalogProductsClient />);

  expect(await screen.findByRole("heading", { name: "Backend Summary" })).toBeVisible();
  expect(screen.getByText(/Тариф:\s*Backend Summary Plan/)).toBeVisible();
  expect(screen.getByText(/1\s250\s₽/)).toBeVisible();
  expect(screen.getByText("Продление: автоматически")).toBeVisible();
  expect(screen.getByText("14 дней бесплатно")).toBeVisible();
  expect(screen.getByRole("link", { name: /Оформить/ })).toHaveAttribute(
    "href",
    "/ru/auth-checkout?product=document-summary"
  );
});

it("renders manual renewal mode from the catalog plan", async () => {
  installCatalogResponse({
    products: [catalogProduct({ plan: catalogPlan({ renewal_mode: "manual" }) })]
  });

  render(<CatalogProductsClient />);

  expect(await screen.findByText("Продление: вручную")).toBeVisible();
});

it("does not require the old hardcoded product list", async () => {
  window.localStorage.removeItem("anytoolai_session_token_v1");
  installCatalogResponse({
    products: [
      catalogProduct({
        product_id: optimizerProductId,
        code: "new-backend-product",
        name: "New Backend Product",
        description: "Description from a product unknown to the RU map"
      })
    ]
  });

  render(<CatalogProductsClient />);

  expect(await screen.findByRole("heading", { name: "New Backend Product" })).toBeVisible();
  expect(
    screen.getByText("Description from a product unknown to the RU map")
  ).toBeVisible();
  expect(screen.getByRole("link", { name: /Оформить/ })).toBeVisible();
});

it("uses a generic presentation for an unknown product code", async () => {
  installCatalogResponse({
    products: [
      catalogProduct({
        code: "unknown-product",
        name: "Unknown Product",
        description: null
      })
    ]
  });

  render(<CatalogProductsClient />);

  expect(await screen.findByRole("heading", { name: "Unknown Product" })).toBeVisible();
  expect(screen.getByRole("link", { name: /Оформить/ })).toBeVisible();
  expect(screen.queryByText("3 summary в месяц")).not.toBeInTheDocument();
});

it("shows a loading state without rendering stale products", async () => {
  server.use(
    http.get(`${apiBase}/api/catalog/products`, async () => {
      await delay(100);
      return HttpResponse.json({ products: [catalogProduct()] });
    })
  );

  render(<CatalogProductsClient />);

  expect(screen.getByRole("status")).toHaveTextContent("Загрузка каталога");
  expect(screen.queryByRole("heading", { name: "Document Summary" })).not.toBeInTheDocument();
});

it("shows a catalog error without falling back to static products", async () => {
  server.use(
    http.get(
      `${apiBase}/api/catalog/products`,
      () => new HttpResponse(null, { status: 503 })
    )
  );

  render(<CatalogProductsClient />);

  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent(
    "Не удалось загрузить каталог. Обновите страницу и попробуйте ещё раз."
  );
  expect(screen.queryByText("Document Summary")).not.toBeInTheDocument();
});

it("shows an empty-catalog state", async () => {
  installCatalogResponse({ products: [] });

  render(<CatalogProductsClient />);

  const status = await screen.findByRole("status");
  expect(status).toHaveTextContent("Сейчас в каталоге нет доступных продуктов.");
});

it("rejects invalid catalog JSON", () => {
  expect(() =>
    decodeCatalogProductsResponse({
      products: [catalogProduct({ plan: { price_amount_minor: "99000" } })]
    })
  ).toThrow("invalid_catalog_plan");
});

it.each([
  "day",
  "days",
  "week",
  "weeks",
  "month",
  "months",
  "year",
  "years",
  "annual",
  "yearly"
])("accepts catalog billing period %s", (billingPeriod) => {
  expect(
    decodeCatalogProductsResponse({
      products: [
        catalogProduct({
          plan: catalogPlan({ billing_period: billingPeriod })
        })
      ]
    }).products[0]?.plan.billing_period
  ).toBe(billingPeriod);
});

it("rejects an invalid catalog billing period", () => {
  expect(() =>
    decodeCatalogProductsResponse({
      products: [
        catalogProduct({
          plan: catalogPlan({ billing_period: "foobar" })
        })
      ]
    })
  ).toThrow("invalid_catalog_plan");
});

it.each(["manual", "automatic"])(
  "accepts catalog renewal mode %s",
  (renewalMode) => {
    expect(
      decodeCatalogProductsResponse({
        products: [
          catalogProduct({
            plan: catalogPlan({ renewal_mode: renewalMode })
          })
        ]
      }).products[0]?.plan.renewal_mode
    ).toBe(renewalMode);
  }
);

it("rejects an invalid catalog renewal mode", () => {
  expect(() =>
    decodeCatalogProductsResponse({
      products: [
        catalogProduct({
          plan: catalogPlan({ renewal_mode: "sometimes" })
        })
      ]
    })
  ).toThrow("invalid_catalog_plan");
});

it("rejects unsupported catalog currency", () => {
  expect(() =>
    decodeCatalogProductsResponse({
      products: [
        catalogProduct({
          plan: catalogPlan({ currency: "USD" })
        })
      ]
    })
  ).toThrow("invalid_catalog_plan");
});

it("formats RUB prices from minor units", () => {
  expect(formatCatalogPrice(99000, "RUB")).toBe("990 ₽");
  expect(formatCatalogPrice(123456, "RUB")).toMatch(/1\s234,56 ₽/);
});

it("renders the purchase CTA for a guest", async () => {
  installCatalogResponse();

  render(<CatalogProductsClient />);

  expect(await screen.findByRole("link", { name: /Оформить/ })).toBeVisible();
});

it("does not send authorization for the public catalog request", async () => {
  server.use(
    http.get(`${apiBase}/api/catalog/products`, ({ request }) => {
      expect(request.headers.get("authorization")).toBeNull();
      return HttpResponse.json({ products: [catalogProduct()] });
    })
  );

  render(<CatalogProductsClient />);

  expect(await screen.findByRole("heading", { name: "Document Summary" })).toBeVisible();
});

it("keeps the catalog timeout active while consuming the response body", async () => {
  vi.useFakeTimers();
  let requestSignal: AbortSignal | null | undefined;
  let resolveBody: (value: unknown) => void = () => {};
  const body = new Promise<unknown>((resolve) => {
    resolveBody = resolve;
  });
  const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(
    (_input, init) => {
      requestSignal = init?.signal;
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => body
      } as Response);
    }
  );

  try {
    const request = getCatalogProducts();

    await vi.advanceTimersByTimeAsync(requestTimeoutMs);

    expect(requestSignal?.aborted).toBe(true);
    resolveBody({ products: [] });
    await expect(request).resolves.toEqual({ products: [] });
  } finally {
    resolveBody({ products: [] });
    fetchSpy.mockRestore();
    vi.useRealTimers();
  }
});

it("shows subscription loading and withholds the purchase CTA", async () => {
  window.localStorage.setItem("anytoolai_session_token_v1", "session-token");
  installCatalogResponse();
  server.use(
    http.get(`${apiBase}/api/account/subscriptions`, async () => {
      await delay(100);
      return HttpResponse.json({ subscriptions: [] });
    })
  );

  render(<CatalogProductsClient />);

  expect(await screen.findByRole("heading", { name: "Document Summary" })).toBeVisible();
  expect(screen.getByText("Проверяем текущую подписку...")).toBeVisible();
  expect(screen.queryByRole("link", { name: /Оформить/ })).not.toBeInTheDocument();
});

it("shows an authenticated subscription error and withholds the purchase CTA", async () => {
  window.localStorage.setItem("anytoolai_session_token_v1", "session-token");
  installCatalogResponse();
  server.use(
    http.get(
      `${apiBase}/api/account/subscriptions`,
      () => new HttpResponse(null, { status: 500 })
    )
  );

  render(<CatalogProductsClient />);

  expect(
    await screen.findByText(
      "Не удалось проверить текущие подписки. Оформление временно недоступно."
    )
  ).toBeVisible();
  expect(screen.queryByRole("link", { name: /Оформить/ })).not.toBeInTheDocument();
});

it("shows current access instead of a purchase CTA", async () => {
  window.localStorage.setItem("anytoolai_session_token_v1", "session-token");
  installCatalogResponse();
  installSubscriptionResponse(subscriptionPayload());

  render(<CatalogProductsClient />);

  expect(await screen.findByText("Доступ уже активен")).toBeVisible();
  expect(screen.getByText("Тариф: Document Summary Pro")).toBeVisible();
  expect(screen.getAllByText("Продление: вручную")).toHaveLength(2);
  expect(screen.getByRole("link", { name: /Личный кабинет/ })).toHaveAttribute(
    "href",
    "/ru/account"
  );
  expect(screen.queryByRole("link", { name: /Оформить/ })).not.toBeInTheDocument();
});

it.each([
  ["expired", "expired", new Date(Date.now() - 86400000).toISOString(), new Date(Date.now() + 86400000).toISOString()],
  ["revoked", "revoked", new Date(Date.now() - 86400000).toISOString(), new Date(Date.now() + 86400000).toISOString()],
  ["future", "active", new Date(Date.now() + 86400000).toISOString(), new Date(Date.now() + 86400000 * 2).toISOString()]
] as const)("does not treat %s entitlement as current access", (_label, status, validFrom, validUntil) => {
  const subscription = subscriptionPayload({
    entitlement_validity: {
      status,
      valid_from: validFrom,
      valid_until: validUntil
    }
  }).subscriptions[0];

  expect(
    hasCurrentProductEntitlement(subscription, documentProductId, new Date())
  ).toBe(false);
});

it("rejects invalid subscription JSON", () => {
  expect(() =>
    decodeAccountSubscriptionsResponse({ subscriptions: [{ status: "active" }] })
  ).toThrow("invalid_subscription");
});

it("rejects invalid subscription vocabulary", () => {
  expect(() =>
    decodeAccountSubscriptionsResponse({
      subscriptions: [
        {
          ...subscriptionPayload().subscriptions[0],
          status: "unknown"
        }
      ]
    })
  ).toThrow("invalid_subscription");
});

it("rejects invalid subscription billing period", () => {
  const subscription = subscriptionPayload().subscriptions[0];

  expect(() =>
    decodeAccountSubscriptionsResponse({
      subscriptions: [
        {
          ...subscription,
          plan: { ...subscription.plan, billing_period: "foobar" }
        }
      ]
    })
  ).toThrow("invalid_subscription_plan");
});

it("rejects invalid subscription renewal mode", () => {
  const subscription = subscriptionPayload().subscriptions[0];

  expect(() =>
    decodeAccountSubscriptionsResponse({
      subscriptions: [
        { ...subscription, renewal_mode: "sometimes" }
      ]
    })
  ).toThrow("invalid_subscription");
});

describe("subscription decoder dates", () => {
  it("does not grant access for invalid dates", () => {
    const subscription = subscriptionPayload({
      entitlement_validity: {
        status: "active",
        valid_from: "not-a-date",
        valid_until: new Date(Date.now() + 86400000).toISOString()
      }
    }).subscriptions[0];

    expect(
      hasCurrentProductEntitlement(subscription, documentProductId)
    ).toBe(false);
  });
});

it("does not allow bundle scope to grant product access", () => {
  const subscription = subscriptionPayload({
    scope: {
      scope_type: "bundle",
      product_id: documentProductId,
      bundle_id: "55555555-5555-4555-8555-555555555555"
    }
  }).subscriptions[0];

  expect(
    hasCurrentProductEntitlement(subscription, documentProductId)
  ).toBe(false);
});

it("keeps subscription data scoped to the matching product", () => {
  const subscription = subscriptionPayload();

  expect(
    hasCurrentProductEntitlement(
      subscription.subscriptions[0],
      optimizerProductId
    )
  ).toBe(false);
});

it("does not expose a purchase CTA while an authenticated subscription payload is invalid", async () => {
  window.localStorage.setItem("anytoolai_session_token_v1", "session-token");
  installCatalogResponse();
  installSubscriptionResponse({ subscriptions: [{ status: "active" }] });

  render(<CatalogProductsClient />);

  await waitFor(() => {
    expect(screen.getByText("Статус подписки пока недоступен.")).toBeVisible();
  });
  expect(screen.queryByRole("link", { name: /Оформить/ })).not.toBeInTheDocument();
});
