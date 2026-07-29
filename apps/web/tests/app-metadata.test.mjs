import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

const layoutPath = fileURLToPath(new URL("../src/app/layout.tsx", import.meta.url));
const checkoutPagePath = fileURLToPath(
  new URL("../src/app/ru/auth-checkout/page.tsx", import.meta.url)
);

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

test("CloudPayments widget is isolated to the checkout route", async () => {
  const [layoutSource, checkoutPageSource] = await Promise.all([
    readFile(layoutPath, "utf8"),
    readFile(checkoutPagePath, "utf8")
  ]);

  assert.doesNotMatch(layoutSource, /widget\.cloudpayments\.ru/);
  assert.match(checkoutPageSource, /widget\.cloudpayments\.ru/);
});
