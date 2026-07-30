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

async function renderCheckoutWithProviderStub() {
  vi.stubEnv("NEXT_PUBLIC_CLOUDPAYMENTS_ENABLED", "true");
  vi.stubEnv("NEXT_PUBLIC_CLOUDPAYMENTS_PUBLIC_ID", "pk_test_provider");
  vi.resetModules();
  const provider = installProviderUiStub();
  const { CheckoutClient } = await import("@/features/checkout/CheckoutClient");
  render(<CheckoutClient cloudPaymentsWidgetStatus="ready" />);
  return provider;
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
            currency: "RUB"
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
    expect(acceptedDocumentIds).toEqual(["doc-offer-v1", "doc-consent-v1"]);
    expectNoCardData(provider.payments[0]);
    expect(provider.payments[0]).toMatchObject({
      publicId: "pk_test_provider",
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
});
