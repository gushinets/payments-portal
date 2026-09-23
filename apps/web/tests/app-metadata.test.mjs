import assert from "node:assert/strict";
import { readdir, readFile, stat } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

const layoutPath = fileURLToPath(new URL("../src/app/layout.tsx", import.meta.url));
const checkoutPagePath = fileURLToPath(
  new URL("../src/app/ru/auth-checkout/page.tsx", import.meta.url)
);
const checkoutClientPath = fileURLToPath(
  new URL("../src/features/checkout/CheckoutClient.tsx", import.meta.url)
);
const retainedProviderAdapterPath = fileURLToPath(
  new URL("../src/features/checkout/provider-adapters.ts", import.meta.url)
);
const srcRootPath = fileURLToPath(new URL("../src", import.meta.url));

test("root metadata keeps public RU branding copy", async () => {
  const source = await readFile(layoutPath, "utf8");

  assert.match(source, /title:\s*"AnytoolAI - RU"/);
  assert.match(
    source,
    /description:\s*"RU-версия платформы цифровых сервисов AnytoolAI\."/
  );
  assert.doesNotMatch(source, /MVP/);
  assert.doesNotMatch(source, /подготовки подключения CloudPayments/);
});

test("the retained auth route does not reach provider scripts or browser SDK", async () => {
  const [checkoutPageSource, checkoutClientSource] = await Promise.all([
    readFile(checkoutPagePath, "utf8"),
    readFile(checkoutClientPath, "utf8")
  ]);
  const files = await sourceFiles(srcRootPath);
  const offenders = [];

  await Promise.all(
    files.map(async (filePath) => {
      const source = await readFile(filePath, "utf8");
      if (
        /widget\.cloudpayments\.ru|\bwindow\.cp\b|\bcp\./.test(source) &&
        filePath !== retainedProviderAdapterPath
      ) {
        offenders.push(filePath);
      }
    })
  );

  assert.doesNotMatch(checkoutPageSource, /next\/script|<Script/);
  assert.doesNotMatch(checkoutPageSource, /provider-adapters/);
  assert.doesNotMatch(checkoutClientSource, /provider-adapters|window\.cp|\bcp\./);
  assert.deepEqual(offenders, []);
});

test("frontend source does not call removed billing contracts", async () => {
  const files = await sourceFiles(srcRootPath);
  const removedContracts = [
    "/api/catalog/products",
    "/api/auth/checkout-intent",
    "/api/account/subscriptions",
    "/api/auth/payment-status"
  ];
  const offenders = [];

  await Promise.all(
    files.map(async (filePath) => {
      const source = await readFile(filePath, "utf8");
      if (removedContracts.some((contract) => source.includes(contract))) {
        offenders.push(filePath);
      }
    })
  );

  assert.deepEqual(offenders, []);
});

async function sourceFiles(directory) {
  const entries = await readdir(directory);
  const files = await Promise.all(
    entries.map(async (entry) => {
      const entryPath = `${directory}/${entry}`;
      const entryStat = await stat(entryPath);
      if (entryStat.isDirectory()) {
        return sourceFiles(entryPath);
      }
      return /\.(ts|tsx|js|jsx)$/.test(entryPath) ? [entryPath] : [];
    })
  );
  return files.flat();
}
