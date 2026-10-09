import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { sourceFiles } from "./setup/source-files.mjs";

const layoutPath = fileURLToPath(
  new URL("../src/app/[locale]/layout.tsx", import.meta.url)
);
const metadataPath = fileURLToPath(
  new URL("../src/i18n/metadata.ts", import.meta.url)
);
const routingPath = fileURLToPath(
  new URL("../src/i18n/routing.ts", import.meta.url)
);
const proxyPath = fileURLToPath(new URL("../src/proxy.ts", import.meta.url));
const srcRootPath = fileURLToPath(new URL("../src", import.meta.url));

test("localized root layout has no Russian-only metadata fallback", async () => {
  const [layoutSource, metadataSource] = await Promise.all([
    readFile(layoutPath, "utf8"),
    readFile(metadataPath, "utf8")
  ]);

  assert.match(layoutSource, /metadataBase:\s*APP_METADATA_BASE/);
  assert.doesNotMatch(layoutSource, /title:/);
  assert.doesNotMatch(layoutSource, /description:/);
  assert.doesNotMatch(layoutSource, /AnytoolAI - RU/);
  assert.doesNotMatch(layoutSource, /RU-версия/);
  assert.doesNotMatch(layoutSource, /MVP/);
  assert.doesNotMatch(layoutSource, /подготовки подключения CloudPayments/);
  assert.match(metadataSource, /namespace:\s*"Metadata"/);
  assert.match(metadataSource, /title:\s*t\("title"\)/);
  assert.match(metadataSource, /description:\s*t\("description"\)/);
});

test("localized routes retain a generated static locale boundary", async () => {
  const source = await readFile(layoutPath, "utf8");

  assert.match(source, /export const dynamicParams = false/);
  assert.match(
    source,
    /SUPPORTED_ROUTE_LOCALES\.map\(\(locale\) => \(\{ locale \}\)\)/
  );
  assert.match(
    source,
    /<html\b[^>]*\slang=\{LANGUAGE_TAG_BY_ROUTE_LOCALE\[locale\]\}[^>]*>/
  );
  assert.match(
    source,
    /<NextIntlClientProvider locale=\{locale\} messages=\{null\}>/
  );
  assert.doesNotMatch(source, /getMessages/);
});

test("locale routing keeps root-only negotiation and persistence disabled", async () => {
  const [routingSource, proxySource] = await Promise.all([
    readFile(routingPath, "utf8"),
    readFile(proxyPath, "utf8")
  ]);

  assert.match(routingSource, /localeDetection:\s*false/);
  assert.match(routingSource, /localeCookie:\s*false/);
  assert.match(routingSource, /alternateLinks:\s*false/);
  assert.match(proxySource, /matcher:\s*\["\/"\]/);
});

test("frontend source does not reach provider scripts or browser SDK", async () => {
  const files = await sourceFiles(srcRootPath);
  const offenders = [];

  await Promise.all(
    files.map(async (filePath) => {
      const source = await readFile(filePath, "utf8");
      if (
        /widget\.cloudpayments\.ru|\bwindow\.cp\b|\bcp\.|provider-adapters/.test(
          source
        )
      ) {
        offenders.push(filePath);
      }
    })
  );

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

test("frontend source does not link to retired checkout or payment-result routes", async () => {
  const files = await sourceFiles(srcRootPath);
  const retiredRoutes = ["/auth-checkout", "/payment-result"];
  const offenders = [];

  await Promise.all(
    files.map(async (filePath) => {
      const source = await readFile(filePath, "utf8");
      if (retiredRoutes.some((route) => source.includes(route))) {
        offenders.push(filePath);
      }
    })
  );

  assert.deepEqual(offenders, []);
});
