import { createHmac } from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { expect, request as playwrightRequest, test, type APIRequestContext } from "@playwright/test";
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
const automaticRenewalFixtureLockPath = path.join(
  repositoryRoot,
  ".harness",
  "playwright-fixtures",
  "automatic-renewal.lock"
);
const automaticRenewalFixtureLockTimeoutMs = 90_000;
const automaticRenewalFixtureLockPollMs = 250;

test.setTimeout(60_000);

type AutomaticRenewalFixture = {
  cleanup: () => void;
};

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

function sleep(ms: number) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

function isProcessAlive(pid: number) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function tryClearStaleFixtureLock() {
  const ownerPath = path.join(automaticRenewalFixtureLockPath, "owner.json");
  let owner: { pid?: unknown; created_at?: unknown } = {};
  try {
    owner = JSON.parse(fs.readFileSync(ownerPath, "utf8")) as {
      pid?: unknown;
      created_at?: unknown;
    };
  } catch {
    return;
  }

  const pid = typeof owner.pid === "number" ? owner.pid : null;
  if (pid !== null && isProcessAlive(pid)) {
    return;
  }
  try {
    fs.rmSync(automaticRenewalFixtureLockPath, { force: true, recursive: true });
  } catch {
    // Another worker may have acquired or removed the lock.
  }
}

async function acquireAutomaticRenewalFixtureLock() {
  const startedAt = Date.now();
  fs.mkdirSync(path.dirname(automaticRenewalFixtureLockPath), { recursive: true });

  while (Date.now() - startedAt < automaticRenewalFixtureLockTimeoutMs) {
    try {
      fs.mkdirSync(automaticRenewalFixtureLockPath);
      fs.writeFileSync(
        path.join(automaticRenewalFixtureLockPath, "owner.json"),
        JSON.stringify({ pid: process.pid, created_at: new Date().toISOString() })
      );
      return () => {
        fs.rmSync(automaticRenewalFixtureLockPath, { force: true, recursive: true });
      };
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") {
        throw error;
      }
      tryClearStaleFixtureLock();
      await sleep(automaticRenewalFixtureLockPollMs);
    }
  }

  throw new Error("Timed out waiting for automatic renewal fixture lock");
}

function runFixturePython(script: string, input?: string) {
  const pythonPath = [process.env.PYTHONPATH, `${repositoryRoot}/apps/api`]
    .filter(Boolean)
    .join(":");
  const fixtureEnv: NodeJS.ProcessEnv = { ...process.env, PYTHONPATH: pythonPath };
  if (process.env.PLAYWRIGHT_DATABASE_URL) {
    fixtureEnv.DATABASE_URL = process.env.PLAYWRIGHT_DATABASE_URL;
  }

  const venvPython = path.join(repositoryRoot, ".venv", "bin", "python");
  const defaultPython = fs.existsSync(venvPython) ? venvPython : "python3";
  return execFileSync(
    process.env.PLAYWRIGHT_PYTHON ?? defaultPython,
    ["-c", script],
    {
      cwd: repositoryRoot,
      encoding: "utf8",
      env: fixtureEnv,
      input,
      stdio: ["pipe", "pipe", "pipe"]
    }
  );
}

async function configureAutomaticRenewalFixture(): Promise<AutomaticRenewalFixture> {
  const releaseLock = await acquireAutomaticRenewalFixtureLock();
  let snapshot = "";
  try {
    snapshot = runFixturePython(`
from datetime import datetime, timezone
import json
import uuid

from app.database import SessionLocal
from app.models import DocumentVersion, LegalEntity, Plan

FIXTURE_ENTITY_ID = uuid.UUID("77777777-7777-4777-8777-777777777777")
FIXTURE_DOCUMENT_ID = uuid.UUID("77777777-7777-4777-8777-777777777778")
FIXTURE_PUBLISHED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)
FIXTURE_ENTITY_VALUES = {
    "tenant_id": "anytoolai",
    "region": "ru",
    "name": "AnytoolAI RU E2E",
    "entity_type": "individual_entrepreneur",
    "tax_id": None,
    "registration_id": None,
    "legal_address": "E2E legal address",
    "support_email": "support@example.com",
    "status": "active",
}
FIXTURE_DOCUMENT_VALUES = {
    "tenant_id": "anytoolai",
    "region": "ru",
    "legal_entity_id": FIXTURE_ENTITY_ID,
    "doc_type": "recurring_consent",
    "version": "playwright-recurring-v1",
    "title": "Согласие на регулярные списания",
    "url_path": "/ru/offer",
    "content_hash": "sha256:playwright-recurring-v1",
    "published_at": FIXTURE_PUBLISHED_AT,
    "effective_from": FIXTURE_PUBLISHED_AT,
    "is_active": True,
    "requires_acceptance": True,
}


def timestamp(value):
    return value.isoformat() if value is not None else None


def serialize_entity(entity):
    return {
        "id": str(entity.id),
        "tenant_id": entity.tenant_id,
        "region": entity.region,
        "name": entity.name,
        "entity_type": entity.entity_type,
        "tax_id": entity.tax_id,
        "registration_id": entity.registration_id,
        "legal_address": entity.legal_address,
        "support_email": entity.support_email,
        "status": entity.status,
    }


def serialize_document(document):
    return {
        "id": str(document.id),
        "tenant_id": document.tenant_id,
        "region": document.region,
        "legal_entity_id": str(document.legal_entity_id),
        "doc_type": document.doc_type,
        "version": document.version,
        "title": document.title,
        "url_path": document.url_path,
        "content_hash": document.content_hash,
        "published_at": timestamp(document.published_at),
        "effective_from": timestamp(document.effective_from),
        "is_active": document.is_active,
        "requires_acceptance": document.requires_acceptance,
    }


db = SessionLocal()
try:
    plan = db.query(Plan).filter(
        Plan.tenant_id == "anytoolai",
        Plan.region == "ru",
        Plan.code == "document-summary-pro",
    ).one()

    entity = db.get(LegalEntity, FIXTURE_ENTITY_ID)
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

    affected_documents = {str(active_document.id): active_document for active_document in active_documents}
    if document is not None:
        affected_documents[str(document.id)] = document

    snapshot = {
        "plan": {
            "id": str(plan.id),
            "renewal_mode": plan.renewal_mode,
        },
        "legal_entity": serialize_entity(entity) if entity is not None else None,
        "document_versions": [
            serialize_document(document)
            for document in sorted(affected_documents.values(), key=lambda item: str(item.id))
        ],
        "created": {
            "legal_entity": entity is None,
            "document_version": document is None,
        },
        "fixture": {
            "legal_entity_id": str(FIXTURE_ENTITY_ID),
            "document_version_id": str(FIXTURE_DOCUMENT_ID if document is None else document.id),
            "document_version": "playwright-recurring-v1",
        },
    }

    plan.renewal_mode = "automatic"

    if entity is None:
        entity = LegalEntity(id=FIXTURE_ENTITY_ID, **FIXTURE_ENTITY_VALUES)
        db.add(entity)
        db.flush()
    else:
        for key, value in FIXTURE_ENTITY_VALUES.items():
            setattr(entity, key, value)

    for active_document in active_documents:
        if document is None or active_document.id != document.id:
            active_document.is_active = False
    db.flush()

    if document is None:
        document = DocumentVersion(id=FIXTURE_DOCUMENT_ID, **FIXTURE_DOCUMENT_VALUES)
        db.add(document)
    else:
        for key, value in FIXTURE_DOCUMENT_VALUES.items():
            setattr(document, key, value)

    db.commit()
    print(json.dumps(snapshot), flush=True)
except Exception:
    db.rollback()
    raise
finally:
    db.close()
`);
    return {
      cleanup: () => {
        try {
          runFixturePython(
            `
from datetime import datetime, timezone
import json
import uuid

from app.database import SessionLocal
from app.models import DocumentAcceptance, DocumentVersion, LegalEntity, PaymentProviderAccount, Plan

FIXTURE_ENTITY_VALUES = {
    "tenant_id": "anytoolai",
    "region": "ru",
    "name": "AnytoolAI RU E2E",
    "entity_type": "individual_entrepreneur",
    "tax_id": None,
    "registration_id": None,
    "legal_address": "E2E legal address",
    "support_email": "support@example.com",
    "status": "active",
}
FIXTURE_DOCUMENT_VALUES = {
    "tenant_id": "anytoolai",
    "region": "ru",
    "doc_type": "recurring_consent",
    "version": "playwright-recurring-v1",
    "title": "Согласие на регулярные списания",
    "url_path": "/ru/offer",
    "content_hash": "sha256:playwright-recurring-v1",
    "published_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    "effective_from": datetime(2026, 1, 1, tzinfo=timezone.utc),
    "is_active": False,
    "requires_acceptance": True,
}


def parse_uuid(value):
    return uuid.UUID(value)


def parse_timestamp(value):
    return datetime.fromisoformat(value) if value is not None else None


def restore_entity(entity, values):
    entity.tenant_id = values["tenant_id"]
    entity.region = values["region"]
    entity.name = values["name"]
    entity.entity_type = values["entity_type"]
    entity.tax_id = values["tax_id"]
    entity.registration_id = values["registration_id"]
    entity.legal_address = values["legal_address"]
    entity.support_email = values["support_email"]
    entity.status = values["status"]


def restore_document(document, values):
    document.tenant_id = values["tenant_id"]
    document.region = values["region"]
    document.legal_entity_id = parse_uuid(values["legal_entity_id"])
    document.doc_type = values["doc_type"]
    document.version = values["version"]
    document.title = values["title"]
    document.url_path = values["url_path"]
    document.content_hash = values["content_hash"]
    document.published_at = parse_timestamp(values["published_at"])
    document.effective_from = parse_timestamp(values["effective_from"])
    document.is_active = values["is_active"]
    document.requires_acceptance = values["requires_acceptance"]


snapshot = json.load(open(0))
fixture_entity_id = parse_uuid(snapshot["fixture"]["legal_entity_id"])
fixture_document_id = parse_uuid(snapshot["fixture"]["document_version_id"])

db = SessionLocal()
try:
    plan = db.get(Plan, parse_uuid(snapshot["plan"]["id"]))
    if plan is not None:
        plan.renewal_mode = snapshot["plan"]["renewal_mode"]

    fixture_document = db.get(DocumentVersion, fixture_document_id)
    if snapshot["created"]["document_version"] and fixture_document is not None:
        acceptance_count = db.query(DocumentAcceptance).filter(
            DocumentAcceptance.document_version_id == fixture_document.id,
        ).count()
        if acceptance_count == 0:
            db.delete(fixture_document)
            db.flush()
            fixture_document = None
        else:
            for key, value in FIXTURE_DOCUMENT_VALUES.items():
                setattr(fixture_document, key, value)
            fixture_document.legal_entity_id = fixture_entity_id
            db.flush()

    restored_documents = []
    for document_snapshot in snapshot["document_versions"]:
        document = db.get(DocumentVersion, parse_uuid(document_snapshot["id"]))
        if document is not None:
            document.is_active = False
            restored_documents.append((document, document_snapshot))
    db.flush()

    for document, document_snapshot in restored_documents:
        restore_document(document, document_snapshot)

    entity = db.get(LegalEntity, fixture_entity_id)
    if snapshot["legal_entity"] is not None:
        if entity is None:
            entity = LegalEntity(
                id=fixture_entity_id,
                tenant_id=snapshot["legal_entity"]["tenant_id"],
                region=snapshot["legal_entity"]["region"],
                name=snapshot["legal_entity"]["name"],
                entity_type=snapshot["legal_entity"]["entity_type"],
                tax_id=snapshot["legal_entity"]["tax_id"],
                registration_id=snapshot["legal_entity"]["registration_id"],
                legal_address=snapshot["legal_entity"]["legal_address"],
                support_email=snapshot["legal_entity"]["support_email"],
                status=snapshot["legal_entity"]["status"],
            )
            db.add(entity)
        else:
            restore_entity(entity, snapshot["legal_entity"])
    elif snapshot["created"]["legal_entity"] and entity is not None:
        document_reference_count = db.query(DocumentVersion).filter(
            DocumentVersion.legal_entity_id == fixture_entity_id,
        ).count()
        provider_reference_count = db.query(PaymentProviderAccount).filter(
            PaymentProviderAccount.legal_entity_id == fixture_entity_id,
        ).count()
        if document_reference_count == 0 and provider_reference_count == 0:
            db.delete(entity)
        else:
            restore_entity(entity, {**FIXTURE_ENTITY_VALUES, "id": str(fixture_entity_id)})

    db.commit()
except Exception:
    db.rollback()
    raise
finally:
    db.close()
`,
            snapshot
          );
        } finally {
          releaseLock();
        }
      }
    };
  } catch (error) {
    releaseLock();
    throw error;
  }
}

function errorReport(error: unknown) {
  if (error instanceof Error) {
    return {
      name: error.name,
      message: error.message,
      stack: error.stack
    };
  }
  return { value: String(error) };
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
  test.setTimeout(120_000);

  let api: APIRequestContext | undefined;
  let fixture: AutomaticRenewalFixture | undefined;
  let testError: unknown;
  let cleanupError: unknown;
  let disposeError: unknown;

  try {
    fixture = await configureAutomaticRenewalFixture();
    api = await playwrightRequest.newContext({ baseURL: apiBaseURL });
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
  } catch (error) {
    testError = error;
  } finally {
    try {
      fixture?.cleanup();
    } catch (error) {
      cleanupError = error;
    }

    try {
      await api?.dispose();
    } catch (error) {
      disposeError = error;
    }
  }

  if (testError !== undefined) {
    if (cleanupError !== undefined || disposeError !== undefined) {
      try {
        await testInfo.attach("automatic-renewal-cleanup-errors", {
          body: JSON.stringify(
            {
              testError: errorReport(testError),
              cleanupError: cleanupError === undefined ? undefined : errorReport(cleanupError),
              disposeError: disposeError === undefined ? undefined : errorReport(disposeError)
            },
            null,
            2
          ),
          contentType: "application/json"
        });
      } catch {
        // Preserve the original test failure as the reported error.
      }
    }
    throw testError;
  }

  if (cleanupError !== undefined && disposeError !== undefined) {
    throw new AggregateError([cleanupError, disposeError], "Automatic renewal cleanup and API disposal failed");
  }
  if (cleanupError !== undefined) {
    throw cleanupError;
  }
  if (disposeError !== undefined) {
    throw disposeError;
  }
});
