import { expect, request as playwrightRequest, test } from "@playwright/test";
import {
  completeProviderUiSuccess,
  expectProviderPaymentWithoutCardData,
  installProviderUiScriptStub
} from "./provider-ui-stub";

const apiBaseURL = process.env.PLAYWRIGHT_API_BASE_URL ?? "http://127.0.0.1:8000";

test.setTimeout(60_000);

test("legal acceptance gates checkout and webhook state remains authoritative", async ({ page }, testInfo) => {
  const api = await playwrightRequest.newContext({ baseURL: apiBaseURL });
  const email = `agent-${Date.now()}-${testInfo.workerIndex}@example.com`;
  const product = "document-summary";
  const planCode = "document-summary-pro";

  const registration = await api.post("/api/auth/register", {
    data: {
      email,
      password: "synthetic-password-123",
      personal_consent: true,
      offer_consent: true
    }
  });
  expect(registration.ok()).toBeTruthy();
  const registrationBody = await registration.json();
  const token = registrationBody.token as string;
  const headers = { Authorization: `Bearer ${token}` };

  const blockedCheckout = await api.post("/api/auth/checkout-intent", {
    headers,
    data: { product, plan_code: planCode, auto_renew: false }
  });
  expect(blockedCheckout.status()).toBe(409);
  const blockedBody = await blockedCheckout.json();
  expect(blockedBody.detail.code).toBe("missing_required_documents");

  for (const document of blockedBody.detail.documents) {
    const acceptance = await api.post("/api/legal/acceptances", {
      headers,
      data: {
        document_version_id: document.document_version_id,
        acceptance_text_hash: document.acceptance_text_hash,
        entrypoint_type: "product",
        entrypoint_value: product,
        source_url: "/ru/auth-checkout?product=document-summary"
      }
    });
    expect(acceptance.ok()).toBeTruthy();
  }

  const checkout = await api.post("/api/auth/checkout-intent", {
    headers,
    data: { product, plan_code: planCode, auto_renew: false }
  });
  expect(checkout.ok()).toBeTruthy();
  const checkoutBody = await checkout.json();
  const invoice = checkoutBody.product_state.invoice_id as string;

  await page.goto(
    `/ru/payment-result?status=success&product=${product}&plan=${planCode}&email=${encodeURIComponent(email)}&invoice=${invoice}`
  );
  const statusPath = `/api/auth/payment-status?invoice_id=${encodeURIComponent(invoice)}&email=${encodeURIComponent(email)}`;
  const beforeWebhook = await api.get(statusPath);
  expect(beforeWebhook.ok()).toBeTruthy();
  const beforeState = await beforeWebhook.json();
  expect(beforeState.product_state.status).toBe("pending");

  const webhook = await api.post("/api/cloudpayments/pay", {
    data: {
      InvoiceId: invoice,
      TransactionId: `tx-${Date.now()}`,
      AccountId: email,
      Amount: "990.00",
      Currency: "RUB",
      CardFirstSix: "411111",
      CardLastFour: "1111"
    }
  });
  expect(webhook.ok()).toBeTruthy();

  const afterWebhook = await api.get(statusPath);
  expect(afterWebhook.ok()).toBeTruthy();
  const finalState = await afterWebhook.json();
  expect(finalState.product_state.status).toBe("pending");

  await testInfo.attach("checkout-webhook-evidence", {
    body: JSON.stringify(
      {
        blockedDocumentTypes: blockedBody.detail.documents.map((item: { doc_type: string }) => item.doc_type),
        invoice,
        beforeWebhook: beforeState,
        afterWebhook: finalState,
        invariant: "Browser return and current payment webhook do not activate legacy access"
      },
      null,
      2
    ),
    contentType: "application/json"
  });
  await api.dispose();
});

test("provider UI stub success cannot activate access without backend state", async ({
  page
}, testInfo) => {
  test.skip(
    process.env.PLAYWRIGHT_PROVIDER_UI_STUB !== "true",
    "Provider UI browser stub is opt-in for CI real-stack characterization."
  );

  const api = await playwrightRequest.newContext({ baseURL: apiBaseURL });
  const email = `provider-ui-${Date.now()}-${testInfo.workerIndex}@example.com`;
  const product = "document-summary";
  const planCode = "document-summary-pro";

  const registration = await api.post("/api/auth/register", {
    data: {
      email,
      password: "synthetic-password-123",
      personal_consent: true,
      offer_consent: true
    }
  });
  expect(registration.ok()).toBeTruthy();
  const registrationBody = await registration.json();
  const token = registrationBody.token as string;
  const headers = { Authorization: `Bearer ${token}` };

  const blockedCheckout = await api.post("/api/auth/checkout-intent", {
    headers,
    data: { product, plan_code: planCode, auto_renew: false }
  });
  expect(blockedCheckout.status()).toBe(409);
  const blockedBody = await blockedCheckout.json();

  for (const document of blockedBody.detail.documents) {
    const acceptance = await api.post("/api/legal/acceptances", {
      headers,
      data: {
        document_version_id: document.document_version_id,
        acceptance_text_hash: document.acceptance_text_hash,
        entrypoint_type: "product",
        entrypoint_value: product,
        source_url: "/ru/auth-checkout?product=document-summary"
      }
    });
    expect(acceptance.ok()).toBeTruthy();
  }

  await installProviderUiScriptStub(page);
  await page.addInitScript((sessionToken) => {
    window.localStorage.setItem("anytoolai_session_token_v1", sessionToken);
  }, token);

  await page.goto(`/ru/auth-checkout?product=${product}`);
  await expect(page.getByText(email)).toBeVisible();
  const payButton = page.getByRole("button", { name: /^Оплатить/ });
  await expect(payButton).toBeEnabled();
  await payButton.click();

  const providerPayments = await expectProviderPaymentWithoutCardData(page);
  expect(providerPayments[0].hasSensitiveFields).toBe(false);
  expect(providerPayments[0].sensitiveFieldKeys).toEqual([]);
  await completeProviderUiSuccess(page);
  await expect(page).toHaveURL(/\/ru\/payment-result\?status=pending/);

  const invoice = String(providerPayments[0].safeOptions.invoiceId);
  const statusPath = `/api/auth/payment-status?invoice_id=${encodeURIComponent(invoice)}&email=${encodeURIComponent(email)}`;
  const paymentStatus = await api.get(statusPath);
  expect(paymentStatus.ok()).toBeTruthy();
  const statusBody = await paymentStatus.json();
  expect(statusBody.product_state.status).toBe("pending");

  await testInfo.attach("provider-ui-stub-evidence", {
    body: JSON.stringify(
      {
        invoice,
        providerPayment: {
          kind: providerPayments[0].kind,
          safeOptions: providerPayments[0].safeOptions,
          hasSensitiveFields: providerPayments[0].hasSensitiveFields,
          sensitiveFieldKeys: providerPayments[0].sensitiveFieldKeys
        },
        backendProductState: statusBody.product_state,
        invariant:
          "Provider browser success navigates to pending result only; backend state remains authoritative"
      },
      null,
      2
    ),
    contentType: "application/json"
  });
  await api.dispose();
});
