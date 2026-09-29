import assert from "node:assert/strict";
import { readdir, readFile, stat } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { ESLint } from "eslint";

const webRoot = fileURLToPath(new URL("..", import.meta.url));
const authApiPath = fileURLToPath(
  new URL("../src/shared/api/auth.ts", import.meta.url)
);
const sharedApiPath = fileURLToPath(
  new URL("../src/shared/api", import.meta.url)
);
const eslint = new ESLint({ cwd: webRoot });

// Exact single-word and otherwise unstructured literals required by current
// transport and decoder mechanics.
const sharedApiMachineLiteralAllowlist = new Set([
  "use client",
  "ApiContractError",
  "Authorization",
  "Content-Type",
  "POST",
  "accepted",
  "authenticated",
  "detail",
  "localhost",
  "login",
  "object",
  "register",
  "registered",
  "status",
  "string",
  "undefined",
  "${status}:${rawBody}",
  "${resolveApiBase()}${path}",
  "Bearer ${token}"
]);

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

function importSpecifiers(source) {
  return [
    ...source.matchAll(
      /(?:\bfrom\s+|\bimport\s*(?:\(\s*)?|\brequire\s*\(\s*)["']([^"']+)["']/g
    )
  ].map((match) => match[1]);
}

function staticStringLiterals(source) {
  return [
    ...source.matchAll(/(["'`])((?:\\.|(?!\1)[^\\\r\n])*)\1/g)
  ].map((match) => match[2]);
}

function isSharedApiMachineLiteral(literal) {
  return (
    literal === "" ||
    sharedApiMachineLiteralAllowlist.has(literal) ||
    /^\/(?:api\/)?[a-z0-9-]+(?:\/[a-z0-9-]+)*$/.test(literal) ||
    /^(?:@\/|\.\.?\/)[A-Za-z0-9_./-]+$/.test(literal) ||
    /^https?:\/\/[^\s]+$/.test(literal) ||
    /^application\/[a-z0-9.+-]+$/.test(literal) ||
    /^Bearer [A-Za-z0-9._~+/=-]+$/.test(literal) ||
    /^(?:\d{1,3}\.){3}\d{1,3}$/.test(literal) ||
    /^[a-z][a-z0-9]*(?:[_-][a-z0-9]+)+$/.test(literal)
  );
}

function sharedApiPresentationLiterals(source) {
  return staticStringLiterals(source).filter(
    (literal) => !isSharedApiMachineLiteral(literal)
  );
}

async function restrictedImportMessages(source, relativePath) {
  const [result] = await eslint.lintText(source, {
    filePath: `${webRoot}/${relativePath}`
  });
  return result.messages.filter(
    (message) => message.ruleId === "no-restricted-imports"
  );
}

test("web lint uses ESLint 10", () => {
  assert.match(ESLint.version, /^10\./);
});

test("critical Next.js and React Hooks rules remain enabled", async () => {
  const config = await eslint.calculateConfigForFile(
    "src/app/[locale]/page.tsx"
  );

  assert.ok(config);
  assert.equal(config.rules["@next/next/no-html-link-for-pages"][0], 2);
  assert.equal(config.rules["react-hooks/rules-of-hooks"][0], 2);
  assert.equal(config.rules["react-hooks/exhaustive-deps"][0], 1);
});

test("flat config lints ECMAScript modules under ESLint 10", async () => {
  const config = await eslint.calculateConfigForFile(
    "tests/BoundaryFixture.mjs"
  );
  const [result] = await eslint.lintText('export const marker = "ok";', {
    filePath: `${webRoot}/tests/BoundaryFixture.mjs`
  });

  assert.ok(config);
  assert.equal(config.languageOptions.parser.name, "espree");
  assert.equal(result.errorCount, 0);
  assert.equal(result.warningCount, 0);
});

test("flat config parses JSX and applies Next.js rules to JavaScript", async () => {
  const [result] = await eslint.lintText(
    'export default function Fixture() { return <img alt="fixture" src="/fixture.png" />; }',
    { filePath: `${webRoot}/src/app/BoundaryFixture.jsx` }
  );

  assert.ok(
    result.messages.some(
      (message) => message.ruleId === "@next/next/no-img-element"
    )
  );
});

test("typed JSON assertions are rejected at production web boundaries", async () => {
  const [result] = await eslint.lintText(
    `
      declare const rawBody: string;
      declare const response: Response;
      const parsed = JSON.parse(rawBody) as { detail: unknown };
      const payload = (await response.json()) as { status: string };
      const promised = response.json() as Promise<{ status: string }>;
      void parsed;
      void payload;
      void promised;
    `,
    { filePath: `${webRoot}/src/shared/api/BoundaryFixture.ts` }
  );
  const messages = result.messages.filter(
    (message) => message.ruleId === "no-restricted-syntax"
  );

  assert.equal(messages.length, 3);
  assert.ok(
    messages.every((message) =>
      /must remain unknown until a runtime decoder validates/.test(message.message)
    )
  );
});

test("unknown JSON results remain allowed for runtime decoding", async () => {
  const [result] = await eslint.lintText(
    `
      declare const rawBody: string;
      declare const response: Response;
      const parsed: unknown = JSON.parse(rawBody);
      const payload: unknown = await response.json();
      void parsed;
      void payload;
    `,
    { filePath: `${webRoot}/src/shared/api/BoundaryFixture.ts` }
  );

  assert.equal(
    result.messages.filter(
      (message) => message.ruleId === "no-restricted-syntax"
    ).length,
    0
  );
});

test("shared API transport cannot own localized auth presentation", async () => {
  const [authApiSource, apiFiles] = await Promise.all([
    readFile(authApiPath, "utf8"),
    sourceFiles(sharedApiPath)
  ]);

  assert.doesNotMatch(
    authApiSource,
    /\b(?:authErrorMessage|passwordResetErrorMessage)\b/,
    "shared/api/auth.ts must expose language-neutral facts, not UI message mapping"
  );

  const neutralTransportSource = [
    'const loginPath = "/api/auth/login";',
    'const contentType = "application/json";',
    'const code = "invalid_api_response";',
    'const authorization = "Bearer test-token";'
  ].join("\n");
  const uncataloguedPresentationSource = [
    'const english = "Could not sign in. Try again.";',
    'const russian = "Не удалось войти. Попробуйте ещё раз.";',
    'const singleWordPresentation = "retry";'
  ].join("\n");

  assert.deepEqual(
    sharedApiPresentationLiterals(neutralTransportSource),
    [],
    "language-neutral machine and transport literals must remain allowed"
  );
  assert.deepEqual(
    sharedApiPresentationLiterals(uncataloguedPresentationSource),
    [
      "Could not sign in. Try again.",
      "Не удалось войти. Попробуйте ещё раз.",
      "retry"
    ]
  );

  const offenders = [];

  for (const filePath of apiFiles) {
    const source = await readFile(filePath, "utf8");
    const forbiddenImports = importSpecifiers(source).filter(
      (specifier) =>
        specifier === "next-intl" ||
        specifier.startsWith("next-intl/") ||
        /(?:^|\/)messages(?:\/|$)/.test(specifier)
    );
    const presentationLiterals = sharedApiPresentationLiterals(source);

    if (forbiddenImports.length > 0 || presentationLiterals.length > 0) {
      offenders.push({
        filePath,
        forbiddenImports,
        presentationLiterals
      });
    }
  }

  assert.deepEqual(
    offenders,
    [],
    "shared/api must remain language-neutral and must not own human-readable presentation"
  );
});

test("routing-owned literal RU application paths are rejected", async () => {
  const [result] = await eslint.lintText(
    [
      'const href = "/ru/products";',
      'redirect("/ru/account");',
      "const destination = `/ru/${productSlug}`;",
      "void href;",
      "void destination;"
    ].join("\n"),
    { filePath: `${webRoot}/src/app/BoundaryFixture.tsx` }
  );
  const messages = result.messages.filter(
    (message) =>
      message.ruleId === "no-restricted-syntax" &&
      /locale-aware navigation/.test(message.message)
  );

  assert.equal(messages.length, 3);
});

test("expression-valued JSX href literals for RU application paths are rejected", async () => {
  const [result] = await eslint.lintText(
    'export default function Fixture() { return <Link href={"/ru/products"} />; }',
    { filePath: `${webRoot}/src/app/BoundaryFixture.tsx` }
  );
  const messages = result.messages.filter(
    (message) =>
      message.ruleId === "no-restricted-syntax" &&
      /locale-aware navigation/.test(message.message)
  );

  assert.equal(messages.length, 1);
});

test("canonical RU legal paths sourced from generated authority remain allowed", async () => {
  const [result] = await eslint.lintText(
    [
      'import legalManifest from "@/generated/legal-manifest.json";',
      "export const canonicalLegalPath = legalManifest.documents[0].urlPath;"
    ].join("\n"),
    { filePath: `${webRoot}/src/shared/config/BoundaryFixture.ts` }
  );

  assert.equal(
    result.messages.filter(
      (message) =>
        message.ruleId === "no-restricted-syntax" &&
        /locale-aware navigation/.test(message.message)
    ).length,
    0
  );
});

test("unrelated RU-prefixed strings are not globally rejected", async () => {
  const [result] = await eslint.lintText(
    'export const auditMessage = "/ru/products appeared in a diagnostic event";',
    { filePath: `${webRoot}/src/shared/config/BoundaryFixture.ts` }
  );

  assert.equal(
    result.messages.filter(
      (message) =>
        message.ruleId === "no-restricted-syntax" &&
        /locale-aware navigation/.test(message.message)
    ).length,
    0
  );
});

test("shared modules cannot import features", async () => {
  const messages = await restrictedImportMessages(
    'import { products } from "@/features/catalog";',
    "src/shared/ui/BoundaryFixture.ts"
  );

  assert.equal(messages.length, 1);
  assert.match(messages[0].message, /Shared modules must not import features or app modules/);
});

test("features cannot import app modules", async () => {
  const messages = await restrictedImportMessages(
    'import LocaleLayout from "@/app/[locale]/layout";',
    "src/features/catalog/BoundaryFixture.ts"
  );

  assert.equal(messages.length, 1);
  assert.match(messages[0].message, /Features must not import app modules/);
});

test("app and feature deep imports are rejected", async () => {
  const appMessages = await restrictedImportMessages(
    'import { products } from "@/features/catalog/catalog";',
    "src/app/BoundaryFixture.ts"
  );
  const featureMessages = await restrictedImportMessages(
    'import { products } from "@/features/catalog/catalog";',
    "src/features/checkout/BoundaryFixture.ts"
  );

  assert.equal(appMessages.length, 1);
  assert.match(appMessages[0].message, /public entrypoint/);
  assert.equal(featureMessages.length, 1);
  assert.match(featureMessages[0].message, /public entrypoint/);
});

test("public feature entrypoints remain allowed", async () => {
  const appMessages = await restrictedImportMessages(
    'import { products } from "@/features/catalog";',
    "src/app/BoundaryFixture.ts"
  );
  const featureMessages = await restrictedImportMessages(
    'import { products } from "@/features/catalog";',
    "src/features/checkout/BoundaryFixture.ts"
  );

  assert.deepEqual(appMessages, []);
  assert.deepEqual(featureMessages, []);
});
