import { createHmac } from "node:crypto";
import { execFileSync } from "node:child_process";
import { expect, request as playwrightRequest, test } from "@playwright/test";
import {
  completeProviderUiSuccess,
  expectProviderPaymentWithoutCardData,
  installProviderUiScriptStub
} from "./provider-ui-stub";

const apiBaseURL = process.env.PLAYWRIGHT_API_BASE_URL ?? "http://127.0.0.1:8000";
const cloudpaymentsApiSecret =
  process.env.PLAYWRIGHT_CLOUDPAYMENTS_API_SECRET ??
  process.env.CLOUDPAYMENTS_API_SECRET ??
  "test-cloudpayments-signing-key";
const repositoryRoot = process.cwd();

test.setTimeout(60_000);

function signedCloudpaymentsJson(payload: Record<string, unknown>) {
  const body = JSON.stringify(payload);
  return {
    body,
    headers: {
      "Content-HMAC": createHmac("sha256", cloudpaymentsApiSecret)
        .update(body)
        .digest("base64"),
      "Content-Type": "application/json"
    }
  };
}

function configureAutomaticRenewalFixture() {
  const pythonPath = [process.env.PYTHONPATH, `${repositoryRoot}/apps/api`]
    .filter(Boolean)
    .join(":");
  const fixtureEnv: NodeJS.ProcessEnv = { ...process.env, PYTHONPATH: pythonPath };
  if (process.env.PLAYWRIGHT_DATABASE_URL) {
    fixtureEnv.DATABASE_URL = process.env.PLAYWRIGHT_DATABASE_URL;
  }
  execFileSync(
    process.env.PLAYWRIGHT_PYTHON ?? "python",
    [
      "-c",
      `
from datetime import datetime, timezone
import uuid

from app.database import SessionLocal
from app.models import DocumentVersion, LegalEntity, Plan
from sqlalchemy.exc import IntegrityError

db = SessionLocal()
try:
    plan = db.query(Plan).filter(
        Plan.tenant_id == "anytoolai",
        Plan.region == "ru",
        Plan.code == "document-summary-pro",
    ).one()
    plan.renewal_mode = "automatic"

    entity = db.query(LegalEntity).filter(
        LegalEntity.tenant_id == "anytoolai",
        LegalEntity.region == "ru",
        LegalEntity.status == "active",
    ).first()
    if entity is None:
        entity = LegalEntity(
            id=uuid.UUID("77777777-7777-4777-8777-777777777777"),
            tenant_id="anytoolai",
            region="ru",
            name="AnytoolAI RU E2E",
            entity_type="individual_entrepreneur",
            legal_address="E2E legal address",
            support_email="support@example.com",
            status="active",
        )
        db.add(entity)
        db.flush()

    document = db.query(DocumentVersion).filter(
        DocumentVersion.tenant_id == "anytoolai",
        DocumentVersion.region == "ru",
        DocumentVersion.doc_type == "recurring_consent",
        DocumentVersion.version == "playwright-recurring-v1",
    ).first()
    active_documents = db.query(DocumentVersion).filter(
        DocumentVersion.tenant_id == "anytoolai",
        DocumentVersion.region == "ru",
        DocumentVersion.doc_type == "recurring_consent",
        DocumentVersion.is_active.is_(True),
    ).all()
    for active_document in active_documents:
        if document is None or active_document.id != document.id:
            active_document.is_active = False

    now = datetime.now(timezone.utc)
    if document is None:
        document = DocumentVersion(
            id=uuid.UUID("77777777-7777-4777-8777-777777777778"),
            tenant_id="anytoolai",
            region="ru",
            legal_entity_id=entity.id,
            doc_type="recurring_consent",
            version="playwright-recurring-v1",
            title="Согласие на регулярные списания",
            url_path="/ru/offer",
            content_hash="sha256:playwright-recurring-v1",
            published_at=now,
            effective_from=now,
            is_active=True,
            requires_acceptance=True,
        )
        db.add(document)
    else:
        document.legal_entity_id = entity.id
        document.title = "Согласие на регулярные списания"
        document.url_path = "/ru/offer"
        document.content_hash = "sha256:playwright-recurring-v1"
        document.is_active = True
        document.requires_acceptance = True
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        plan = db.query(Plan).filter(
            Plan.tenant_id == "anytoolai",
            Plan.region == "ru",
            Plan.code == "document-summary-pro",
        ).one()
        plan.renewal_mode = "automatic"
        document = db.query(DocumentVersion).filter(
            DocumentVersion.tenant_id == "anytoolai",
            DocumentVersion.region == "ru",
            DocumentVersion.doc_type == "recurring_consent",
            DocumentVersion.version == "playwright-recurring-v1",
        ).one()
        for active_document in db.query(DocumentVersion).filter(
            DocumentVersion.tenant_id == "anytoolai",
            DocumentVersion.region == "ru",
            DocumentVersion.doc_type == "recurring_consent",
            DocumentVersion.is_active.is_(True),
        ).all():
            active_document.is_active = active_document.id == document.id
        document.is_active = True
        document.requires_acceptance = True
        db.commit()
finally:
    db.close()
`
    ],
    {
      cwd: repositoryRoot,
      env: fixtureEnv,
      stdio: "pipe"
    }
  );
}

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

  const transactionId = `tx-${testInfo.project.name}-${testInfo.workerIndex}-${Date.now()}`;
  const webhookPayload = signedCloudpaymentsJson({
    InvoiceId: invoice,
    TransactionId: transactionId,
    AccountId: email,
    Amount: "990.00",
    Currency: "RUB",
    Status: "Completed",
    CardFirstSix: "411111",
    CardLastFour: "1111"
  });
  const webhook = await api.post("/api/cloudpayments/pay", {
    headers: webhookPayload.headers,
    data: webhookPayload.body
  });
  expect(webhook.ok()).toBeTruthy();

  const afterWebhook = await api.get(statusPath);
  expect(afterWebhook.ok()).toBeTruthy();
  const finalState = await afterWebhook.json();
  expect(finalState.product_state.status).toBe("active");
  expect(finalState.product_state.transaction_id).toBe(transactionId);

  await testInfo.attach("checkout-webhook-evidence", {
    body: JSON.stringify(
      {
        blockedDocumentTypes: blockedBody.detail.documents.map((item: { doc_type: string }) => item.doc_type),
        invoice,
        beforeWebhook: beforeState,
        afterWebhook: finalState,
        invariant: "Browser return remains pending until the verified webhook activates subscription access"
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
  await expect(page.locator("#checkout-form").getByText(email)).toBeVisible();
  const payButton = page.getByRole("button", { name: /^Оплатить/ });
  await expect(payButton).toBeEnabled();
  await payButton.click();

  const providerPayments = await expectProviderPaymentWithoutCardData(page);
  expect(providerPayments[0].kind).toBe("charge");
  expect(providerPayments[0].safeOptions).toMatchObject({
    publicId: expect.any(String),
    description: "Document Summary Pro",
    amount: 990,
    currency: "RUB",
    accountId: email,
    email,
    data: {
      product_code: product,
      plan_code: planCode
    }
  });
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

test("automatic renewal checkout uses exact recurring consent acceptance", async ({
  page
}, testInfo) => {
  test.skip(
    process.env.PLAYWRIGHT_PROVIDER_UI_STUB !== "true",
    "Provider UI browser stub is opt-in for CI real-stack characterization."
  );

  configureAutomaticRenewalFixture();

  const api = await playwrightRequest.newContext({ baseURL: apiBaseURL });
  const email = `auto-renew-${Date.now()}-${testInfo.workerIndex}@example.com`;
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

  const checkoutAttempts: Array<Record<string, unknown>> = [];
  let recurringAcceptanceId = "";
  const acceptedDocumentTypes: string[] = [];
  await page.route("**/api/auth/checkout-intent", async (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>;
    checkoutAttempts.push({
      auto_renew: body.auto_renew,
      hasRecurringAcceptanceId:
        typeof body.recurring_consent_acceptance_id === "string",
      recurring_consent_acceptance_id: body.recurring_consent_acceptance_id
    });
    await route.continue();
  });
  page.on("response", async (response) => {
    if (!response.url().includes("/api/legal/acceptances") || response.status() >= 400) {
      return;
    }
    const body = (await response.json()) as { acceptance_id?: string; doc_type?: string };
    if (body.doc_type) {
      acceptedDocumentTypes.push(body.doc_type);
    }
    if (body.doc_type === "recurring_consent" && body.acceptance_id) {
      recurringAcceptanceId = body.acceptance_id;
    }
  });

  await installProviderUiScriptStub(page);
  await page.addInitScript((sessionToken) => {
    window.localStorage.setItem("anytoolai_session_token_v1", sessionToken);
  }, token);

  await page.goto(`/ru/auth-checkout?product=${product}`);
  await expect(page.locator("#checkout-form").getByText(email)).toBeVisible();
  await page.getByLabel("Включить автопродление").check();
  await page
    .getByLabel(/Я соглашаюсь на регулярное автоматическое списание/)
    .check();
  await page.getByRole("button", { name: /^Оплатить/ }).click();

  await expect(
    page.getByText("Перед оплатой нужно принять актуальные юридические документы.")
  ).toBeVisible();
  const documentCheckboxes = page.locator(".legal-consent-item input[type='checkbox']");
  const documentCount = await documentCheckboxes.count();
  expect(documentCount).toBeGreaterThan(0);
  for (let index = 0; index < documentCount; index += 1) {
    await documentCheckboxes.nth(index).check();
  }
  await page.getByRole("button", { name: /Принять и продолжить/ }).click();

  const providerPayments = await expectProviderPaymentWithoutCardData(page);
  expect(recurringAcceptanceId).toBeTruthy();
  expect(checkoutAttempts.length).toBeGreaterThanOrEqual(2);
  expect(checkoutAttempts[0]).toMatchObject({
    auto_renew: true,
    hasRecurringAcceptanceId: false
  });
  const finalCheckoutAttempt = checkoutAttempts[checkoutAttempts.length - 1];
  expect(finalCheckoutAttempt).toMatchObject({
    auto_renew: true,
    hasRecurringAcceptanceId: true,
    recurring_consent_acceptance_id: recurringAcceptanceId
  });
  expect(providerPayments[0].kind).toBe("charge");
  expect(providerPayments[0].safeOptions).toMatchObject({
    amount: 990,
    currency: "RUB",
    data: {
      product_code: product,
      plan_code: planCode
    }
  });
  expect(providerPayments[0].hasSensitiveFields).toBe(false);

  await testInfo.attach("automatic-renewal-consent-evidence", {
    body: JSON.stringify(
      {
        acceptedDocumentTypes,
        checkoutAttempts: checkoutAttempts.map((attempt) => ({
          auto_renew: attempt.auto_renew,
          hasRecurringAcceptanceId: attempt.hasRecurringAcceptanceId
        })),
        recurringAcceptanceIdSuffix: recurringAcceptanceId.slice(-8),
        providerPayment: {
          kind: providerPayments[0].kind,
          amount: providerPayments[0].safeOptions.amount,
          currency: providerPayments[0].safeOptions.currency,
          hasSensitiveFields: providerPayments[0].hasSensitiveFields
        },
        invariant:
          "Checkout records exact recurring consent evidence and opens charge widget; provider subscription setup is not called in ANY-78."
      },
      null,
      2
    ),
    contentType: "application/json"
  });
  await api.dispose();
});
