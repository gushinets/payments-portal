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
  options: Record<string, unknown>;
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
          window.cp = {
            CloudPayments: function CloudPayments() {
              this.pay = function pay(kind, options, callbacks) {
                window.__anytoolaiProviderPayments.push({ kind, options });
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

  return payments as ProviderPayment[];
}
