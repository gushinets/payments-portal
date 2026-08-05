import { expect, type Page } from "@playwright/test";

declare global {
  interface Window {
    __anytoolaiProviderPayments?: ProviderPayment[];
    __anytoolaiProviderCallbacks?: {
      onSuccess?: () => void;
    };
  }
}

type ProviderPayment = {
  kind: string;
  safeOptions: {
    publicId?: unknown;
    description?: unknown;
    amount?: unknown;
    currency?: unknown;
    invoiceId?: unknown;
    accountId?: unknown;
    email?: unknown;
    data?: {
      product_code?: unknown;
      plan_code?: unknown;
    };
  };
  hasSensitiveFields: boolean;
  sensitiveFieldKeys: string[];
};

export async function installProviderUiScriptStub(page: Page) {
  await page.route(
    "https://widget.cloudpayments.ru/bundles/cloudpayments",
    async (route) => {
      await route.fulfill({
        contentType: "application/javascript",
        body: `
          window.__anytoolaiProviderPayments = [];
          window.__anytoolaiProviderCallbacks = undefined;
          function sanitizePaymentOptions(options) {
            const sensitiveFieldKeys = [];
            const sensitivePattern = /card|pan|cvv|cvc|token|secret|password|authorization|auth|header/i;

            function collectSensitiveKeys(value) {
              if (!value || typeof value !== "object") {
                return;
              }

              for (const key of Object.keys(value)) {
                if (sensitivePattern.test(key)) {
                  sensitiveFieldKeys.push(key);
                }
                collectSensitiveKeys(value[key]);
              }
            }

            collectSensitiveKeys(options);
            return {
              publicId: options?.publicId,
              description: options?.description,
              amount: options?.amount,
              currency: options?.currency,
              invoiceId: options?.invoiceId,
              accountId: options?.accountId,
              email: options?.email,
              data: {
                product_code: options?.data?.product_code,
                plan_code: options?.data?.plan_code
              },
              hasSensitiveFields: sensitiveFieldKeys.length > 0,
              sensitiveFieldKeys
            };
          }
          window.cp = {
            CloudPayments: function CloudPayments() {
              this.pay = function pay(kind, options, callbacks) {
                const sanitizedOptions = sanitizePaymentOptions(options);
                window.__anytoolaiProviderPayments.push({
                  kind,
                  safeOptions: {
                    publicId: sanitizedOptions.publicId,
                    description: sanitizedOptions.description,
                    amount: sanitizedOptions.amount,
                    currency: sanitizedOptions.currency,
                    invoiceId: sanitizedOptions.invoiceId,
                    accountId: sanitizedOptions.accountId,
                    email: sanitizedOptions.email,
                    data: sanitizedOptions.data
                  },
                  hasSensitiveFields: sanitizedOptions.hasSensitiveFields,
                  sensitiveFieldKeys: sanitizedOptions.sensitiveFieldKeys
                });
                window.__anytoolaiProviderCallbacks = callbacks;
              };
            }
          };
        `
      });
    }
  );
}

export async function completeProviderUiSuccess(page: Page) {
  await page.evaluate(() => {
    window.__anytoolaiProviderCallbacks?.onSuccess?.();
  });
}

export async function expectProviderPaymentWithoutCardData(page: Page) {
  await expect
    .poll(async () =>
      page.evaluate(() => window.__anytoolaiProviderPayments?.length ?? 0)
    )
    .toBe(1);

  const payments = await page.evaluate(
    () => window.__anytoolaiProviderPayments ?? []
  );

  const serialized = JSON.stringify(payments).toLowerCase();
  expect(serialized).not.toContain("card");
  expect(serialized).not.toContain("pan");
  expect(serialized).not.toContain("cvv");
  expect(serialized).not.toContain("cvc");
  expect(payments.every((payment) => payment.hasSensitiveFields === false)).toBe(
    true
  );

  return payments as ProviderPayment[];
}
