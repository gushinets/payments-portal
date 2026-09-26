import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { ESLint } from "eslint";

const webRoot = fileURLToPath(new URL("..", import.meta.url));
const eslint = new ESLint({ cwd: webRoot });

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
