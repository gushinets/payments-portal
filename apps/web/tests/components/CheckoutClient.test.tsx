import { HttpResponse, http } from "msw";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setRouteSearchParams } from "../helpers/navigation";
import { installProviderUiStub, expectNoCardData } from "../helpers/provider-ui";
import { readStoredPaymentResult, storeSessionToken } from "../helpers/storage";
import { server } from "../setup/msw-server";

const apiBase = "http://localhost:8000";
const sessionUser = {
  tenant_id: "anytoolai",
  region: "ru",
  user_id: "11111111-1111-4111-8111-111111111111",
  email: "buyer@example.com"
};

function catalogResponse(
  overrides: Record<string, unknown> = {},
  planOverrides: Record<string, unknown> = {}
) {
  return {
    products: [
      {
        product_id: "11111111-1111-4111-8111-111111111111",
        code: "document-summary",
        name: "Document Summary",
        description: "Backend document summary description",
        plan: {
          plan_id: "33333333-3333-4333-8333-333333333333",
          code: "document-summary-pro",
          name: "Document Summary Pro",
          price_amount_minor: 99000,
          currency: "RUB",
          billing_period: "month",
          renewal_mode: "manual",
          trial_days: 7,
          ...planOverrides
        },
        ...overrides
      }
    ]
  };
}

async function renderCheckoutWithProviderStub() {
  vi.resetModules();
  const provider = installProviderUiStub();
  const { CheckoutClient } = await import("@/features/checkout/CheckoutClient");
  render(<CheckoutClient checkoutAdapterStatus="ready" />);
  return provider;
}

function checkoutAction(
  invoiceId: string,
  mode = "charge",
  publicIdentifier: string | null = "pk_backend_terminal"
) {
  return {
    provider: "cloudpayments",
    experience: "widget",
    mode,
    public_identifier: publicIdentifier,
    amount_minor: 99000,
    amount: 990,
    currency: "RUB",
    merchant_order_id: invoiceId,
    provider_invoice_id: invoiceId,
    account_id: sessionUser.email,
    description: "Document Summary Pro",
    metadata: {
      product_code: "document-summary",
      plan_code: "document-summary-pro"
    }
  };
}

function sessionResponse(status: "inactive" | "pending" | "active" | "failed") {
  return {
    authenticated: true,
    user: sessionUser,
    product_state: {
      product_code: "document-summary",
      plan_code: "document-summary-pro",
      plan_name: "Document Summary Pro",
      invoice_id: status === "pending" ? "invoice-pending" : null,
      transaction_id: null,
      status,
      starts_at: null,
      expires_at: null
    }
  };
}

describe("CheckoutClient critical characterization", () => {
  beforeEach(() => {
    setRouteSearchParams("product=document-summary");
    server.use(
      http.get(`${apiBase}/api/catalog/products`, () =>
        HttpResponse.json(catalogResponse())
      )
    );
  });

  it("uses the selected product and commercial fields from the backend catalog", async () => {
    const user = userEvent.setup();
    storeSessionToken("session-token");
    const checkoutBodies: Record<string, unknown>[] = [];
    server.use(
      http.get(`${apiBase}/api/auth/session`, () =>
        HttpResponse.json(sessionResponse("inactive"))
      ),
      http.get(`${apiBase}/api/catalog/products`, () =>
        HttpResponse.json(
          catalogResponse(
            { name: "Backend Summary" },
            {
              code: "backend-summary-plan",
              name: "Backend Summary Plan",
              price_amount_minor: 125000,
              trial_days: 14
            }
          )
        )
      ),
      http.post(`${apiBase}/api/auth/checkout-intent`, async ({ request }) => {
        checkoutBodies.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json({
          product_state: {
            product_code: "document-summary",
            plan_code: "backend-summary-plan",
            plan_name: "Backend Summary Plan",
            invoice_id: "invoice-backend-catalog",
            transaction_id: null,
            status: "pending",
            starts_at: null,
            expires_at: null
          },
          checkout: {
            amount_minor: 125000,
            amount: 1250,
            currency: "RUB",
            action: checkoutAction("invoice-backend-catalog")
          }
        });
      })
    );

    const provider = await renderCheckoutWithProviderStub();

    expect(await screen.findByRole("heading", { name: "Backend Summary" })).toBeVisible();
    expect(screen.getByText(/1\s250\s₽/)).toBeVisible();
    expect(screen.getByText("Пробный период 14 дней")).toBeVisible();
    await screen.findByText("buyer@example.com");
    await user.click(screen.getByRole("button", { name: /^Оплатить/ }));

    await waitFor(() => expect(provider.payments).toHaveLength(1));
    expect(checkoutBodies).toEqual([
      {
        product: "document-summary",
        plan_code: "backend-summary-plan",
        auto_renew: false
      }
    ]);
  });

  it("uses the catalog plan name when inactive session data is stale", async () => {
    storeSessionToken("session-token");
    server.use(
      http.get(`${apiBase}/api/catalog/products`, () =>
        HttpResponse.json(
          catalogResponse({}, { name: "Backend Renamed Plan" })
        )
      ),
      http.get(`${apiBase}/api/auth/session`, () =>
        HttpResponse.json({
          ...sessionResponse("inactive"),
          product_state: {
            ...sessionResponse("inactive").product_state,
            plan_name: "Old Hardcoded Plan"
          }
        })
      )
    );

    await renderCheckoutWithProviderStub();

    expect(await screen.findByText("buyer@example.com")).toBeVisible();
    const subscriptionState = screen.getByRole("heading", {
      name: "2. Статус подписки"
    }).nextElementSibling;
    expect(subscriptionState).toHaveTextContent("Backend Renamed Plan");
    expect(subscriptionState).not.toHaveTextContent("Old Hardcoded Plan");
  });

  it("keeps checkout controls unavailable while the catalog is loading", async () => {
    setRouteSearchParams("product=does-not-exist");
    server.use(
      http.get(`${apiBase}/api/catalog/products`, async () => {
        await new Promise((resolve) => setTimeout(resolve, 50));
        return HttpResponse.json(catalogResponse());
      })
    );

    await renderCheckoutWithProviderStub();

    expect(screen.getByRole("status")).toHaveTextContent("Загрузка каталога");
    expect(screen.queryByText(/Мы не нашли запрошенный продукт/)).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Оплатить/ })).not.toBeInTheDocument();
  });

  it("blocks checkout when the catalog request fails", async () => {
    server.use(
      http.get(
        `${apiBase}/api/catalog/products`,
        () => new HttpResponse(null, { status: 503 })
      )
    );

    await renderCheckoutWithProviderStub();

    expect(
      await screen.findByText(
        "Не удалось загрузить каталог. Обновите страницу и попробуйте ещё раз."
      )
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: /^Оплатить/ })).not.toBeInTheDocument();
  });

  it("blocks checkout when the catalog payload is invalid", async () => {
    server.use(
      http.get(`${apiBase}/api/catalog/products`, () =>
        HttpResponse.json({ products: [{ code: "document-summary" }] })
      )
    );

    await renderCheckoutWithProviderStub();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Не удалось загрузить каталог"
    );
    expect(screen.queryByRole("button", { name: /^Оплатить/ })).not.toBeInTheDocument();
  });

  it("resolves an unknown query product only after catalog loading", async () => {
    setRouteSearchParams("product=does-not-exist");

    await renderCheckoutWithProviderStub();

    expect(
      await screen.findByText(/Мы не нашли запрошенный продукт/)
    ).toBeVisible();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Оплатить/ })).not.toBeInTheDocument();
  });

  it("blocks repeat purchase controls for active access and links to the account", async () => {
    storeSessionToken("session-token");
    const checkoutAttempts = { count: 0 };
    server.use(
      http.get(`${apiBase}/api/auth/session`, () =>
        HttpResponse.json({
          ...sessionResponse("active"),
          product_state: {
            ...sessionResponse("active").product_state,
            plan_name: "Backend Active Plan",
            expires_at: "2026-09-30T12:00:00Z"
          }
        })
      ),
      http.post(`${apiBase}/api/auth/checkout-intent`, () => {
        checkoutAttempts.count += 1;
        return HttpResponse.json({});
      })
    );

    await renderCheckoutWithProviderStub();

    expect(await screen.findByText("buyer@example.com")).toBeVisible();
    expect(screen.getByText("Backend Active Plan")).toBeVisible();
    expect(screen.getByText(/Действует до:/)).toBeVisible();
    expect(screen.getByRole("link", { name: /Перейти в аккаунт/ })).toHaveAttribute(
      "href",
      "/ru/account"
    );
    expect(screen.queryByRole("button", { name: /^Оплатить/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Оформить" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Включить автопродление")).not.toBeInTheDocument();
    expect(checkoutAttempts.count).toBe(0);
  });

  it("blocks unauthenticated checkout before payment preparation", async () => {
    await renderCheckoutWithProviderStub();

    expect(
      await screen.findAllByText(/Чтобы продолжить оформление, войдите в аккаунт/)
    ).toHaveLength(2);
    expect(
      screen.getByRole("button", { name: /Войти или зарегистрироваться/ })
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: /^Оплатить/ })).not.toBeInTheDocument();
  });

  it("logs in through the checkout form and stores the session token", async () => {
    const user = userEvent.setup();
    setRouteSearchParams("product=document-summary&auth=login");
    const loginUser = { ...sessionUser, email: "login-buyer@example.com" };

    server.use(
      http.post(`${apiBase}/api/auth/login`, async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        expect(body).toEqual({
          email: "login-buyer@example.com",
          password: "password-123"
        });
        return HttpResponse.json({
          status: "authenticated",
          token: "login-session-token",
          user: loginUser
        });
      }),
      http.get(`${apiBase}/api/auth/session`, ({ request }) => {
        expect(request.headers.get("authorization")).toBe(
          "Bearer login-session-token"
        );
        return HttpResponse.json({
          ...sessionResponse("inactive"),
          user: loginUser
        });
      })
    );

    await renderCheckoutWithProviderStub();

    await user.type(await screen.findByLabelText("Email"), "login-buyer@example.com");
    await user.type(await screen.findByLabelText("Пароль"), "password-123");
    await user.click(screen.getByRole("button", { name: /^Войти$/ }));

    await waitFor(() => {
      expect(window.localStorage.getItem("anytoolai_session_token_v1")).toBe(
        "login-session-token"
      );
    });
    expect(await screen.findByText("login-buyer@example.com")).toBeVisible();
    expect(screen.getByRole("button", { name: /^Оплатить/ })).toBeEnabled();
  });

  it("registers through the checkout form and stores the session token", async () => {
    const user = userEvent.setup();
    const registerUser = { ...sessionUser, email: "register-buyer@example.com" };

    server.use(
      http.post(`${apiBase}/api/auth/register`, async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        expect(body).toEqual({
          email: "register-buyer@example.com",
          password: "password-123",
          personal_consent: true,
          offer_consent: true
        });
        return HttpResponse.json({
          status: "registered",
          token: "register-session-token",
          user: registerUser
        });
      }),
      http.get(`${apiBase}/api/auth/session`, ({ request }) => {
        expect(request.headers.get("authorization")).toBe(
          "Bearer register-session-token"
        );
        return HttpResponse.json({
          ...sessionResponse("inactive"),
          user: registerUser
        });
      })
    );

    await renderCheckoutWithProviderStub();

    await user.type(await screen.findByLabelText("Email"), "register-buyer@example.com");
    await user.type(await screen.findByLabelText("Пароль"), "password-123");
    await user.type(await screen.findByLabelText("Повторите пароль"), "password-123");
    await user.click(
      screen.getByLabelText(/Я даю согласие на обработку персональных данных/)
    );
    await user.click(screen.getByLabelText(/Я принимаю условия/));
    await user.click(screen.getByRole("button", { name: /Создать аккаунт/ }));

    await waitFor(() => {
      expect(window.localStorage.getItem("anytoolai_session_token_v1")).toBe(
        "register-session-token"
      );
    });
    expect(await screen.findByText("register-buyer@example.com")).toBeVisible();
    expect(screen.getByRole("button", { name: /^Оплатить/ })).toBeEnabled();
  });

  it("loads an existing session and clears it on logout", async () => {
    const user = userEvent.setup();
    storeSessionToken("session-token");
    server.use(
      http.get(`${apiBase}/api/auth/session`, ({ request }) => {
        expect(request.headers.get("authorization")).toBe("Bearer session-token");
        return HttpResponse.json(sessionResponse("inactive"));
      }),
      http.post(`${apiBase}/api/auth/logout`, ({ request }) => {
        expect(request.headers.get("authorization")).toBe("Bearer session-token");
        return HttpResponse.json({ status: "ok" });
      })
    );

    await renderCheckoutWithProviderStub();

    expect(await screen.findByText("buyer@example.com")).toBeVisible();
    await user.click(screen.getByRole("button", { name: /Выйти/ }));

    await waitFor(() => {
      expect(window.localStorage.getItem("anytoolai_session_token_v1")).toBeNull();
    });
    expect(
      screen.getByRole("button", { name: /Войти или зарегистрироваться/ })
    ).toBeVisible();
  });

  it("requires every active legal document before creating provider checkout", async () => {
    const user = userEvent.setup();
    storeSessionToken("session-token");
    let checkoutAttempts = 0;
    const acceptedDocumentIds: string[] = [];
    server.use(
      http.get(`${apiBase}/api/auth/session`, () =>
        HttpResponse.json(sessionResponse("inactive"))
      ),
      http.post(`${apiBase}/api/auth/checkout-intent`, async ({ request }) => {
        checkoutAttempts += 1;
        const body = (await request.json()) as Record<string, unknown>;
        expect(body).toEqual({
          product: "document-summary",
          plan_code: "document-summary-pro",
          auto_renew: false
        });
        expect(body).not.toHaveProperty("recurring_consent_acceptance_id");
        expect(JSON.stringify(body).toLowerCase()).not.toContain("card");

        if (checkoutAttempts === 1) {
          return HttpResponse.json(
            {
              detail: {
                code: "missing_required_documents",
                documents: [
                  {
                    document_version_id: "doc-offer-v1",
                    doc_type: "offer",
                    version: "2026-07-11",
                    title: "Публичная оферта",
                    url_path: "/ru/offer",
                    acceptance_text: "Принимаю условия оферты.",
                    acceptance_text_hash: "hash-offer"
                  },
                  {
                    document_version_id: "doc-consent-v1",
                    doc_type: "consent_personal_data",
                    version: "2026-07-11",
                    title: "Согласие на обработку персональных данных",
                    url_path: "/ru/consent-personal-data",
                    acceptance_text: "Принимаю обработку персональных данных.",
                    acceptance_text_hash: "hash-consent"
                  }
                ]
              }
            },
            { status: 409 }
          );
        }

        return HttpResponse.json({
          product_state: {
            product_code: "document-summary",
            plan_code: "document-summary-pro",
            plan_name: "Document Summary Pro",
            invoice_id: "invoice-after-legal",
            transaction_id: null,
            status: "pending",
            starts_at: null,
            expires_at: null
          },
          checkout: {
            amount_minor: 99000,
            amount: 990,
            currency: "RUB",
            action: checkoutAction("invoice-after-legal")
          }
        });
      }),
      http.post(`${apiBase}/api/legal/acceptances`, async ({ request }) => {
        const body = (await request.json()) as {
          document_version_id: string;
          acceptance_text_hash: string;
          entrypoint_type: string;
          entrypoint_value: string;
          source_url: string;
        };
        acceptedDocumentIds.push(body.document_version_id);
        expect(body.entrypoint_type).toBe("product");
        expect(body.entrypoint_value).toBe("document-summary");
        expect(body.source_url).toEqual(expect.any(String));
        return HttpResponse.json({ status: "accepted" });
      })
    );

    const provider = await renderCheckoutWithProviderStub();

    expect(await screen.findByText("buyer@example.com")).toBeVisible();
    await user.click(screen.getByRole("button", { name: /^Оплатить/ }));
    expect(
      await screen.findByText("Перед оплатой нужно принять актуальные юридические документы.")
    ).toBeVisible();
    expect(screen.getByRole("button", { name: /Принять и продолжить/ })).toBeDisabled();

    await user.click(screen.getByLabelText(/Принять документ Публичная оферта/));
    await user.click(
      screen.getByLabelText(/Принять документ Согласие на обработку персональных данных/)
    );
    await user.click(screen.getByRole("button", { name: /Принять и продолжить/ }));

    await waitFor(() => {
      expect(provider.payments).toHaveLength(1);
    });
    expect(provider.modes).toEqual(["charge"]);
    expect(acceptedDocumentIds).toEqual(["doc-offer-v1", "doc-consent-v1"]);
    expectNoCardData(provider.payments[0]);
    expect(provider.payments[0]).toMatchObject({
      publicId: "pk_backend_terminal",
      amount: 990,
      currency: "RUB",
      invoiceId: "invoice-after-legal",
      accountId: "buyer@example.com"
    });
    expect(readStoredPaymentResult()).toMatchObject({
      status: "pending",
      productCode: "document-summary",
      email: "buyer@example.com",
      invoiceId: "invoice-after-legal"
    });
  });

  it("does not start automatic checkout before the local recurring consent checkbox is selected", async () => {
    const user = userEvent.setup();
    storeSessionToken("session-token");
    let checkoutAttempts = 0;
    server.use(
      http.get(`${apiBase}/api/auth/session`, () =>
        HttpResponse.json(sessionResponse("inactive"))
      ),
      http.post(`${apiBase}/api/auth/checkout-intent`, () => {
        checkoutAttempts += 1;
        return HttpResponse.json({});
      })
    );

    await renderCheckoutWithProviderStub();

    expect(await screen.findByText("buyer@example.com")).toBeVisible();
    await user.click(screen.getByLabelText("Включить автопродление"));
    await user.click(screen.getByRole("button", { name: /^Оплатить/ }));

    expect(
      await screen.findByText(/Для автопродления нужно отдельное согласие/)
    ).toBeVisible();
    expect(checkoutAttempts).toBe(0);
  });

  it("stores the recurring acceptance id and repeats checkout with that exact id", async () => {
    const user = userEvent.setup();
    storeSessionToken("session-token");
    const checkoutBodies: Record<string, unknown>[] = [];
    server.use(
      http.get(`${apiBase}/api/auth/session`, () =>
        HttpResponse.json(sessionResponse("inactive"))
      ),
      http.post(`${apiBase}/api/auth/checkout-intent`, async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        checkoutBodies.push(body);
        if (checkoutBodies.length === 1) {
          expect(body).toEqual({
            product: "document-summary",
            plan_code: "document-summary-pro",
            auto_renew: true
          });
          return HttpResponse.json(
            {
              detail: {
                code: "missing_required_documents",
                documents: [
                  {
                    document_version_id: "doc-offer-v1",
                    doc_type: "offer",
                    version: "2026-07-11",
                    title: "Публичная оферта",
                    url_path: "/ru/offer",
                    acceptance_text: "Принимаю условия оферты.",
                    acceptance_text_hash: "hash-offer"
                  },
                  {
                    document_version_id: "doc-recurring-v1",
                    doc_type: "recurring_consent",
                    version: "2026-08-25",
                    title: "Согласие на регулярные списания",
                    url_path: "/ru/offer",
                    acceptance_text: "Принимаю регулярные списания.",
                    acceptance_text_hash: "hash-recurring"
                  }
                ]
              }
            },
            { status: 409 }
          );
        }

        expect(body).toEqual({
          product: "document-summary",
          plan_code: "document-summary-pro",
          auto_renew: true,
          recurring_consent_acceptance_id: "acceptance-recurring-v1"
        });
        return HttpResponse.json({
          product_state: {
            product_code: "document-summary",
            plan_code: "document-summary-pro",
            plan_name: "Document Summary Pro",
            invoice_id: "invoice-after-recurring",
            transaction_id: null,
            status: "pending",
            starts_at: null,
            expires_at: null
          },
          checkout: {
            amount_minor: 99000,
            amount: 990,
            currency: "RUB",
            action: checkoutAction("invoice-after-recurring")
          }
        });
      }),
      http.post(`${apiBase}/api/legal/acceptances`, async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        expect(body).toMatchObject({
          entrypoint_type: "product",
          entrypoint_value: "document-summary",
          metadata: {
            plan_code: "document-summary-pro",
            auto_renew: true
          }
        });
        if (body.document_version_id === "doc-recurring-v1") {
          return HttpResponse.json({
            status: "accepted",
            acceptance_id: "acceptance-recurring-v1",
            doc_type: "recurring_consent"
          });
        }
        return HttpResponse.json({
          status: "accepted",
          acceptance_id: "acceptance-offer-v1",
          doc_type: "offer"
        });
      })
    );

    const provider = await renderCheckoutWithProviderStub();

    expect(await screen.findByText("buyer@example.com")).toBeVisible();
    await user.click(screen.getByLabelText("Включить автопродление"));
    await user.click(
      screen.getByLabelText(/Я соглашаюсь на регулярное автоматическое списание/)
    );
    await user.click(screen.getByRole("button", { name: /^Оплатить/ }));
    await user.click(screen.getByLabelText(/Принять документ Публичная оферта/));
    await user.click(
      screen.getByLabelText(/Принять документ Согласие на регулярные списания/)
    );
    await user.click(
      screen.getByRole("button", { name: /Принять и продолжить/ })
    );

    await waitFor(() => expect(provider.payments).toHaveLength(1));
    expect(checkoutBodies).toHaveLength(2);
    expect(provider.payments[0]).toMatchObject({
      invoiceId: "invoice-after-recurring",
      accountId: "buyer@example.com"
    });
  });

  it("clears the recurring acceptance id when auto-renew is turned off", async () => {
    const user = userEvent.setup();
    storeSessionToken("session-token");
    const checkoutBodies: Record<string, unknown>[] = [];
    server.use(
      http.get(`${apiBase}/api/auth/session`, () =>
        HttpResponse.json(sessionResponse("inactive"))
      ),
      http.post(`${apiBase}/api/auth/checkout-intent`, async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        checkoutBodies.push(body);
        if (checkoutBodies.length === 1) {
          return HttpResponse.json(
            {
              detail: {
                code: "missing_required_documents",
                documents: [
                  {
                    document_version_id: "doc-recurring-v1",
                    doc_type: "recurring_consent",
                    version: "2026-08-25",
                    title: "Согласие на регулярные списания",
                    url_path: "/ru/offer",
                    acceptance_text: "Принимаю регулярные списания.",
                    acceptance_text_hash: "hash-recurring"
                  }
                ]
              }
            },
            { status: 409 }
          );
        }
        return HttpResponse.json({
          product_state: {
            product_code: "document-summary",
            plan_code: "document-summary-pro",
            plan_name: "Document Summary Pro",
            invoice_id: `invoice-${checkoutBodies.length}`,
            transaction_id: null,
            status: "pending",
            starts_at: null,
            expires_at: null
          },
          checkout: {
            amount_minor: 99000,
            amount: 990,
            currency: "RUB",
            action: checkoutAction(`invoice-${checkoutBodies.length}`)
          }
        });
      }),
      http.post(`${apiBase}/api/legal/acceptances`, () =>
        HttpResponse.json({
          status: "accepted",
          acceptance_id: "acceptance-recurring-v1",
          doc_type: "recurring_consent"
        })
      )
    );

    const provider = await renderCheckoutWithProviderStub();

    expect(await screen.findByText("buyer@example.com")).toBeVisible();
    await user.click(screen.getByLabelText("Включить автопродление"));
    await user.click(screen.getByLabelText(/Я соглашаюсь на регулярное автоматическое списание/));
    await user.click(screen.getByRole("button", { name: /^Оплатить/ }));
    await user.click(screen.getByLabelText(/Принять документ Согласие на регулярные списания/));
    await user.click(screen.getByRole("button", { name: /Принять и продолжить/ }));
    await waitFor(() => expect(provider.payments).toHaveLength(1));

    await user.click(screen.getByLabelText("Включить автопродление"));
    await user.click(screen.getByRole("button", { name: /^Оплатить/ }));

    await waitFor(() => expect(provider.payments).toHaveLength(2));
    expect(checkoutBodies[2]).toEqual({
      product: "document-summary",
      plan_code: "document-summary-pro",
      auto_renew: false
    });
  });

  it("clears the recurring acceptance id on logout", async () => {
    const user = userEvent.setup();
    storeSessionToken("session-token");
    const checkoutBodies: Record<string, unknown>[] = [];
    server.use(
      http.get(`${apiBase}/api/auth/session`, ({ request }) => {
        expect(request.headers.get("authorization") ?? "").toMatch(/Bearer (session-token|new-session-token)/);
        return HttpResponse.json(sessionResponse("inactive"));
      }),
      http.post(`${apiBase}/api/auth/logout`, () =>
        HttpResponse.json({ status: "logged_out" })
      ),
      http.post(`${apiBase}/api/auth/checkout-intent`, async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        checkoutBodies.push(body);
        if (checkoutBodies.length === 1) {
          return HttpResponse.json(
            {
              detail: {
                code: "missing_required_documents",
                documents: [
                  {
                    document_version_id: "doc-recurring-v1",
                    doc_type: "recurring_consent",
                    version: "2026-08-25",
                    title: "Согласие на регулярные списания",
                    url_path: "/ru/offer",
                    acceptance_text: "Принимаю регулярные списания.",
                    acceptance_text_hash: "hash-recurring"
                  }
                ]
              }
            },
            { status: 409 }
          );
        }
        if (checkoutBodies.length === 2) {
          return HttpResponse.json({
            product_state: {
              product_code: "document-summary",
              plan_code: "document-summary-pro",
              plan_name: "Document Summary Pro",
              invoice_id: "invoice-before-logout",
              transaction_id: null,
              status: "pending",
              starts_at: null,
              expires_at: null
            },
            checkout: {
              amount_minor: 99000,
              amount: 990,
              currency: "RUB",
              action: checkoutAction("invoice-before-logout")
            }
          });
        }
        expect(body).not.toHaveProperty("recurring_consent_acceptance_id");
        return HttpResponse.json(
          { detail: { code: "recurring_consent_required" } },
          { status: 409 }
        );
      }),
      http.post(`${apiBase}/api/legal/acceptances`, () =>
        HttpResponse.json({
          status: "accepted",
          acceptance_id: "acceptance-before-logout",
          doc_type: "recurring_consent"
        })
      )
    );

    const provider = await renderCheckoutWithProviderStub();

    expect(await screen.findByText("buyer@example.com")).toBeVisible();
    await user.click(screen.getByLabelText("Включить автопродление"));
    await user.click(screen.getByLabelText(/Я соглашаюсь на регулярное автоматическое списание/));
    await user.click(screen.getByRole("button", { name: /^Оплатить/ }));
    await user.click(screen.getByLabelText(/Принять документ Согласие на регулярные списания/));
    await user.click(screen.getByRole("button", { name: /Принять и продолжить/ }));
    await waitFor(() => expect(provider.payments).toHaveLength(1));

    await user.click(screen.getByRole("button", { name: /Выйти/ }));
    await waitFor(() => {
      expect(window.localStorage.getItem("anytoolai_session_token_v1")).toBeNull();
    });
    window.localStorage.setItem("anytoolai_session_token_v1", "new-session-token");
    window.dispatchEvent(new Event("anytoolai_session_changed"));
    expect(await screen.findByText("buyer@example.com")).toBeVisible();
    await user.click(screen.getByLabelText(/Я соглашаюсь на регулярное автоматическое списание/));
    await user.click(screen.getByRole("button", { name: /^Оплатить/ }));

    expect(
      await screen.findByText(/Для автопродления нужно принять актуальный документ/)
    ).toBeVisible();
  });

  it.each<[string, RegExp]>([
    [
      "automatic_renewal_not_permitted",
      /Выбранный тариф не поддерживает автопродление/
    ],
    [
      "recurring_consent_required",
      /Для автопродления нужно принять актуальный документ/
    ],
    [
      "recurring_consent_invalid",
      /Согласие на регулярные списания устарело/
    ]
  ])("shows a specific checkout message for %s", async (code, message) => {
    const user = userEvent.setup();
    storeSessionToken("session-token");
    server.use(
      http.get(`${apiBase}/api/auth/session`, () =>
        HttpResponse.json(sessionResponse("inactive"))
      ),
      http.post(`${apiBase}/api/auth/checkout-intent`, () =>
        HttpResponse.json({ detail: { code } }, { status: 409 })
      )
    );

    await renderCheckoutWithProviderStub();

    expect(await screen.findByText("buyer@example.com")).toBeVisible();
    await user.click(screen.getByLabelText("Включить автопродление"));
    await user.click(screen.getByLabelText(/Я соглашаюсь на регулярное автоматическое списание/));
    await user.click(screen.getByRole("button", { name: /^Оплатить/ }));

    expect(await screen.findByText(message)).toBeVisible();
    expect(screen.queryByText("Не удалось подготовить оплату. Попробуйте ещё раз.")).not.toBeInTheDocument();
  });

  it("starts the CloudPayments widget in two-stage auth mode", async () => {
    const user = userEvent.setup();
    storeSessionToken("session-token");
    server.use(
      http.get(`${apiBase}/api/auth/session`, () =>
        HttpResponse.json(sessionResponse("inactive"))
      ),
      http.post(`${apiBase}/api/auth/checkout-intent`, () =>
        HttpResponse.json({
          product_state: {
            product_code: "document-summary",
            plan_code: "document-summary-pro",
            plan_name: "Document Summary Pro",
            invoice_id: "invoice-auth-mode",
            transaction_id: null,
            status: "pending",
            starts_at: null,
            expires_at: null
          },
          checkout: {
            amount_minor: 99000,
            amount: 990,
            currency: "RUB",
            action: checkoutAction("invoice-auth-mode", "auth")
          }
        })
      )
    );
    const provider = await renderCheckoutWithProviderStub();

    expect(await screen.findByText("buyer@example.com")).toBeVisible();
    await user.click(screen.getByRole("button", { name: /^Оплатить/ }));

    await waitFor(() => expect(provider.payments).toHaveLength(1));
    expect(provider.modes).toEqual(["auth"]);
    expectNoCardData(provider.payments[0]);
  });

  it("does not create checkout state when the required provider widget failed to load", async () => {
    const user = userEvent.setup();
    storeSessionToken("session-token");
    let checkoutAttempts = 0;
    vi.resetModules();
    server.use(
      http.get(`${apiBase}/api/auth/session`, () =>
        HttpResponse.json(sessionResponse("inactive"))
      ),
      http.post(`${apiBase}/api/auth/checkout-intent`, () => {
        checkoutAttempts += 1;
        return HttpResponse.json({});
      })
    );
    const { CheckoutClient } = await import("@/features/checkout/CheckoutClient");
    render(<CheckoutClient checkoutAdapterStatus="failed" />);

    expect(await screen.findByText("buyer@example.com")).toBeVisible();
    expect(
      screen.getByText(/Не удалось загрузить платёжный виджет/)
    ).toBeVisible();
    const checkoutButton = screen.getByRole("button", { name: /^Оплатить/ });
    expect(checkoutButton).toBeDisabled();
    await user.click(checkoutButton);

    expect(checkoutAttempts).toBe(0);
    expect(readStoredPaymentResult()).toBeNull();
  });

  it("fails explicitly when the selected provider SDK is unavailable", async () => {
    const user = userEvent.setup();
    storeSessionToken("session-token");
    vi.resetModules();
    window.cp = undefined;
    server.use(
      http.get(`${apiBase}/api/auth/session`, () =>
        HttpResponse.json(sessionResponse("inactive"))
      ),
      http.post(`${apiBase}/api/auth/checkout-intent`, () =>
        HttpResponse.json({
          product_state: {
            product_code: "document-summary",
            plan_code: "document-summary-pro",
            plan_name: "Document Summary Pro",
            invoice_id: "invoice-sdk-missing",
            transaction_id: null,
            status: "pending",
            starts_at: null,
            expires_at: null
          },
          checkout: {
            amount_minor: 99000,
            amount: 990,
            currency: "RUB",
            action: checkoutAction("invoice-sdk-missing")
          }
        })
      )
    );
    const { CheckoutClient } = await import("@/features/checkout/CheckoutClient");
    render(<CheckoutClient checkoutAdapterStatus="ready" />);

    expect(await screen.findByText("buyer@example.com")).toBeVisible();
    await user.click(screen.getByRole("button", { name: /^Оплатить/ }));

    expect(
      await screen.findByText(/Не удалось открыть платёжный виджет/)
    ).toBeVisible();
    expect(readStoredPaymentResult()).toBeNull();
  });

  it("fails explicitly when backend omits the provider public terminal id", async () => {
    const user = userEvent.setup();
    storeSessionToken("session-token");
    server.use(
      http.get(`${apiBase}/api/auth/session`, () =>
        HttpResponse.json(sessionResponse("inactive"))
      ),
      http.post(`${apiBase}/api/auth/checkout-intent`, () =>
        HttpResponse.json({
          product_state: {
            product_code: "document-summary",
            plan_code: "document-summary-pro",
            plan_name: "Document Summary Pro",
            invoice_id: "invoice-missing-public-id",
            transaction_id: null,
            status: "pending",
            starts_at: null,
            expires_at: null
          },
          checkout: {
            amount_minor: 99000,
            amount: 990,
            currency: "RUB",
            action: checkoutAction("invoice-missing-public-id", "charge", null)
          }
        })
      )
    );
    const provider = await renderCheckoutWithProviderStub();

    expect(await screen.findByText("buyer@example.com")).toBeVisible();
    await user.click(screen.getByRole("button", { name: /^Оплатить/ }));

    expect(
      await screen.findByText(/Не удалось открыть платёжный виджет/)
    ).toBeVisible();
    expect(provider.payments).toHaveLength(0);
    expect(readStoredPaymentResult()).toBeNull();
  });

  it("shows an actionable error when backend rejects provider configuration", async () => {
    const user = userEvent.setup();
    storeSessionToken("session-token");
    server.use(
      http.get(`${apiBase}/api/auth/session`, () =>
        HttpResponse.json(sessionResponse("inactive"))
      ),
      http.post(`${apiBase}/api/auth/checkout-intent`, () =>
        HttpResponse.json(
          { detail: "cloudpayments_public_terminal_id_missing" },
          { status: 409 }
        )
      )
    );
    const provider = await renderCheckoutWithProviderStub();

    expect(await screen.findByText("buyer@example.com")).toBeVisible();
    await user.click(screen.getByRole("button", { name: /^Оплатить/ }));

    expect(
      await screen.findByText(/Платёжный терминал настроен некорректно/)
    ).toBeVisible();
    expect(provider.payments).toHaveLength(0);
    expect(readStoredPaymentResult()).toBeNull();
  });

  it("recovers when the provider adapter throws while starting checkout", async () => {
    const user = userEvent.setup();
    storeSessionToken("session-token");
    server.use(
      http.get(`${apiBase}/api/auth/session`, () =>
        HttpResponse.json(sessionResponse("inactive"))
      ),
      http.post(`${apiBase}/api/auth/checkout-intent`, () =>
        HttpResponse.json({
          product_state: {
            product_code: "document-summary",
            plan_code: "document-summary-pro",
            plan_name: "Document Summary Pro",
            invoice_id: "invoice-unsupported-mode",
            transaction_id: null,
            status: "pending",
            starts_at: null,
            expires_at: null
          },
          checkout: {
            amount_minor: 99000,
            amount: 990,
            currency: "RUB",
            action: checkoutAction("invoice-unsupported-mode", "unsupported-mode")
          }
        })
      )
    );
    const provider = await renderCheckoutWithProviderStub();

    expect(await screen.findByText("buyer@example.com")).toBeVisible();
    await user.click(screen.getByRole("button", { name: /^Оплатить/ }));

    expect(
      await screen.findByText(/Не удалось открыть платёжный виджет/)
    ).toBeVisible();
    expect(provider.payments).toHaveLength(0);
    expect(provider.modes).toHaveLength(0);
    expect(readStoredPaymentResult()).toBeNull();
  });
});
