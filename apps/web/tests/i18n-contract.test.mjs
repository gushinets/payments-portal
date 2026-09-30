import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { parse, TYPE } from "@formatjs/icu-messageformat-parser";

const localeConfigPath = fileURLToPath(
  new URL("../../../config/locales.json", import.meta.url)
);
const messagesPath = fileURLToPath(new URL("../src/messages", import.meta.url));
const requiredPresentationErrorKeys = [
  "Auth.errors.contract",
  "Auth.errors.network",
  "Auth.errors.internalServer",
  "PasswordReset.errors.contract",
  "PasswordReset.errors.network",
  "PasswordReset.errors.internalServer",
  "PasswordReset.errors.rateLimited"
];

function flattenCatalog(value, locale, keyPath = "", result = new Map()) {
  if (typeof value === "string") {
    assert.notEqual(keyPath, "", `[${locale}] catalog root must be an object`);
    result.set(keyPath, value);
    return result;
  }

  assert.ok(
    value !== null && typeof value === "object" && !Array.isArray(value),
    `[${locale}] ${keyPath || "<root>"} must be an object or string leaf`
  );

  for (const [key, child] of Object.entries(value)) {
    flattenCatalog(child, locale, keyPath ? `${keyPath}.${key}` : key, result);
  }

  return result;
}

function collectSignature(
  elements,
  signature = { arguments: new Set(), tags: new Set() }
) {
  for (const element of elements) {
    if (
      element.type === TYPE.argument ||
      element.type === TYPE.number ||
      element.type === TYPE.date ||
      element.type === TYPE.time ||
      element.type === TYPE.select ||
      element.type === TYPE.plural
    ) {
      signature.arguments.add(element.value);
    }

    if (element.type === TYPE.tag) {
      signature.tags.add(element.value);
      collectSignature(element.children, signature);
    }

    if (element.type === TYPE.select || element.type === TYPE.plural) {
      for (const option of Object.values(element.options)) {
        collectSignature(option.value, signature);
      }
    }
  }

  return {
    arguments: [...signature.arguments].sort(),
    tags: [...signature.tags].sort()
  };
}

test("message catalogs have exact locale, key, and ICU signature parity", async () => {
  const localeConfig = JSON.parse(await readFile(localeConfigPath, "utf8"));
  const supportedLocales = localeConfig.locales.map(
    ({ routeLocale }) => routeLocale
  );
  const catalogFiles = (await readdir(messagesPath))
    .filter((fileName) => fileName.endsWith(".json"))
    .sort();
  const expectedCatalogFiles = supportedLocales
    .map((locale) => `${locale}.json`)
    .sort();

  assert.deepEqual(
    catalogFiles,
    expectedCatalogFiles,
    "message catalogs must match config/locales.json exactly"
  );

  const catalogs = new Map();
  for (const locale of supportedLocales) {
    const filePath = `${messagesPath}/${locale}.json`;
    let catalog;
    try {
      catalog = JSON.parse(await readFile(filePath, "utf8"));
    } catch (error) {
      throw new Error(
        `[${locale}] failed to read or parse catalog: ${error.message}`
      );
    }
    catalogs.set(locale, flattenCatalog(catalog, locale));
  }

  const referenceLocale = supportedLocales[0];
  const referenceCatalog = catalogs.get(referenceLocale);
  const referenceKeys = [...referenceCatalog.keys()].sort();

  for (const locale of supportedLocales) {
    const catalog = catalogs.get(locale);
    assert.deepEqual(
      [...catalog.keys()].sort(),
      referenceKeys,
      `[${locale}] leaf keys differ from [${referenceLocale}]`
    );

    for (const key of requiredPresentationErrorKeys) {
      assert.equal(
        typeof catalog.get(key),
        "string",
        `[${locale}] ${key} must exist as a string leaf`
      );
    }
  }

  for (const key of referenceKeys) {
    let referenceSignature;

    for (const locale of supportedLocales) {
      const message = catalogs.get(locale).get(key);
      let ast;
      try {
        ast = parse(message);
      } catch (error) {
        throw new Error(
          `[${locale}] ${key} is not valid ICU: ${error.message}`
        );
      }

      const signature = collectSignature(ast);
      if (!referenceSignature) {
        referenceSignature = signature;
        continue;
      }

      assert.deepEqual(
        signature,
        referenceSignature,
        `[${locale}] ${key} ICU arguments/tags differ from [${referenceLocale}]`
      );
    }
  }
});
