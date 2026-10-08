import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { isAbsolute, relative, resolve, sep } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { ESLint } from "eslint";
import ts from "typescript";
import { sourceFiles } from "./setup/source-files.mjs";

const webRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const webSourcePath = resolve(webRoot, "src");
const authApiPath = resolve(webRoot, "src/shared/api/auth.ts");
const transportApiPath = resolve(webRoot, "src/shared/api/transport.ts");
const sharedApiPath = resolve(webRoot, "src/shared/api");
const generatedAuthContractModule = "@/generated/api-contracts/types.gen";
const migratedAuthDtoNames = new Set([
  "AuthUser",
  "AuthSessionResponse",
  "RegisterRequest",
  "RegisterResponse",
  "LoginRequest",
  "LoginResponse",
  "SessionResponse",
  "SessionUserResponse",
  "LogoutResponse",
  "PasswordResetRequest",
  "PasswordResetRequestResponse",
  "PasswordResetConfirmRequest",
  "PasswordResetConfirmResponse",
  "EmailVerificationRequest",
  "EmailVerificationRequestResponse",
  "EmailVerificationConfirmRequest",
  "EmailVerificationConfirmResponse"
]);
const removedAuthDecoderNames = new Set([
  "isAuthUser",
  "decodeAuthResponse",
  "decodeStatusResponse",
  "decodeRegisterResponse",
  "decodeLoginResponse",
  "decodeAuthSessionResponse",
  "decodeLogoutResponse",
  "decodePasswordResetRequestResponse",
  "decodePasswordResetConfirmResponse",
  "decodeEmailVerificationRequestResponse",
  "decodeEmailVerificationConfirmResponse"
]);
const eslint = new ESLint({ cwd: webRoot });

function bindingNames(binding) {
  if (ts.isIdentifier(binding)) {
    return [binding.text];
  }

  if (ts.isObjectBindingPattern(binding) || ts.isArrayBindingPattern(binding)) {
    return binding.elements.flatMap((element) =>
      ts.isBindingElement(element) ? bindingNames(element.name) : []
    );
  }

  return [];
}

function localDeclarationNames(source) {
  const sourceFile = ts.createSourceFile(
    "auth.ts",
    source,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TS
  );
  const names = [];

  function visit(node) {
    if (ts.isImportDeclaration(node) || ts.isImportEqualsDeclaration(node)) {
      return;
    }

    if (
      (ts.isClassDeclaration(node) ||
        ts.isEnumDeclaration(node) ||
        ts.isFunctionDeclaration(node) ||
        ts.isInterfaceDeclaration(node) ||
        ts.isModuleDeclaration(node) ||
        ts.isTypeAliasDeclaration(node)) &&
      node.name
    ) {
      names.push(node.name.text);
    }

    if (ts.isVariableDeclaration(node)) {
      names.push(...bindingNames(node.name));
    }

    ts.forEachChild(node, visit);
  }

  ts.forEachChild(sourceFile, visit);
  return names;
}

function matchingLocalDeclarations(source, names) {
  return [
    ...new Set(localDeclarationNames(source).filter((name) => names.has(name)))
  ].sort();
}

function hasGeneratedAuthContractImport(source) {
  const sourceFile = ts.createSourceFile(
    "auth.ts",
    source,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TS
  );

  return sourceFile.statements.some(
    (statement) =>
      ts.isImportDeclaration(statement) &&
      ts.isStringLiteral(statement.moduleSpecifier) &&
      statement.moduleSpecifier.text === generatedAuthContractModule
  );
}

function jsonBoundarySites(source, filePath) {
  const sourceFile = ts.createSourceFile(
    filePath, source, ts.ScriptTarget.Latest, true,
    filePath.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS
  );
  const assertions = [];
  const jsonCalls = [];
  const parseCalls = [];

  function visit(node) {
    if (ts.isAsExpression(node) || ts.isTypeAssertionExpression(node)) {
      assertions.push(node);
    }
    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)) {
      if (node.expression.name.text === "json") {
        jsonCalls.push(node);
      }
      if (node.expression.name.text === "parse" &&
          node.expression.expression.getText(sourceFile) === "JSON") {
        parseCalls.push(node);
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  return { sourceFile, assertions, jsonCalls, parseCalls };
}

function isAwaitedFetch(node) {
  while (node && ts.isParenthesizedExpression(node)) {
    node = node.expression;
  }
  return node && ts.isAwaitExpression(node) &&
    ts.isCallExpression(node.expression) &&
    ts.isIdentifier(node.expression.expression) &&
    node.expression.expression.text === "fetch";
}

function isKnownResponse(receiver) {
  if (isAwaitedFetch(receiver)) {
    return true;
  }
  if (!ts.isIdentifier(receiver)) {
    return false;
  }

  // Only inspect explicit Response bindings and direct awaited fetch results.
  // No alias tracking, inferred types, or third-party .json() interpretation.
  for (let scope = receiver.parent; scope; scope = scope.parent) {
    const parameters = ts.isFunctionLike(scope) ? scope.parameters : [];
    const variables = ts.isBlock(scope) || ts.isSourceFile(scope)
      ? scope.statements.flatMap((statement) => ts.isVariableStatement(statement)
        ? [...statement.declarationList.declarations] : [])
      : [];
    const binding = [...parameters, ...variables].find((node) =>
      ts.isIdentifier(node.name) && node.name.text === receiver.text
    );
    if (binding) {
      return (binding.type && ts.isTypeReferenceNode(binding.type) &&
        ts.isIdentifier(binding.type.typeName) &&
        binding.type.typeName.text === "Response") ||
        (ts.isVariableDeclaration(binding) && isAwaitedFetch(binding.initializer));
    }
  }
  return false;
}

function isWithinDirectory(filePath, directory) {
  const relativePath = relative(directory, filePath);
  return relativePath !== "" && relativePath !== ".." &&
    !relativePath.startsWith(`..${sep}`) && !isAbsolute(relativePath);
}

function adapterParsingSites(source, filePath) {
  const normalizedFilePath = resolve(filePath);
  if (relative(transportApiPath, normalizedFilePath) === "" ||
      !isWithinDirectory(normalizedFilePath, webSourcePath)) {
    return [];
  }
  const { jsonCalls, parseCalls } = jsonBoundarySites(source, normalizedFilePath);
  // Production code delegates known Fetch/Response JSON to transport, so an
  // intermediate unknown cannot create a second trust point in features/UI.
  // JSON.parse stays adapter-only; local form/storage parsing remains allowed.
  return [
    ...jsonCalls.filter((node) => isKnownResponse(node.expression.expression)),
    ...(isWithinDirectory(normalizedFilePath, sharedApiPath) ? parseCalls : [])
  ];
}

async function restrictedImportMessages(source, relativePath) {
  const [result] = await eslint.lintText(source, {
    filePath: resolve(webRoot, relativePath)
  });
  return result.messages.filter(
    (message) => message.ruleId === "no-restricted-imports"
  );
}

async function sharedApiBoundaryMessages(source, relativePath) {
  const [result] = await eslint.lintText(source, {
    filePath: resolve(webRoot, relativePath)
  });
  return result.messages.filter(
    (message) => message.ruleId === "shared-api-boundaries/language-neutral"
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
    filePath: resolve(webRoot, "tests/BoundaryFixture.mjs")
  });

  assert.ok(config);
  assert.equal(config.languageOptions.parser.name, "espree");
  assert.equal(result.errorCount, 0);
  assert.equal(result.warningCount, 0);
});

test("flat config parses JSX and applies Next.js rules to JavaScript", async () => {
  const [result] = await eslint.lintText(
    'export default function Fixture() { return <img alt="fixture" src="/fixture.png" />; }',
    { filePath: resolve(webRoot, "src/app/BoundaryFixture.jsx") }
  );

  assert.ok(
    result.messages.some(
      (message) => message.ruleId === "@next/next/no-img-element"
    )
  );
});

test("typed JSON assertions are rejected in feature and UI code", async () => {
  for (const relativePath of [
    "src/shared/api/BoundaryFixture.ts",
    "src/features/account/BoundaryFixture.ts",
    "src/shared/ui/BoundaryFixture.ts"
  ]) {
    const [result] = await eslint.lintText(
      `
        declare const rawBody: string;
        declare const response: Response;
        const parsed = JSON.parse(rawBody) as { detail: unknown };
        const payload = (await response.json()) as { status: string };
        const promised = response.json() as Promise<{ status: string }>;
        const asserted = <{ status: string }>await response.json();
        const parsedAssertion = <{ detail: unknown }>JSON.parse(rawBody);
        void parsed;
        void payload;
        void promised;
        void asserted;
        void parsedAssertion;
      `,
      { filePath: resolve(webRoot, relativePath) }
    );
    const messages = result.messages.filter(
      (message) => message.ruleId === "no-restricted-syntax"
    );

    assert.equal(messages.length, 5);
    assert.ok(
      messages.every((message) =>
        /must be read as unknown/.test(message.message)
      )
    );
  }
});

test("unknown JSON results remain allowed at the transport boundary", async () => {
  const [result] = await eslint.lintText(
    `
      declare const rawBody: string;
      declare const response: Response;
      const parsed: unknown = JSON.parse(rawBody);
      const payload: unknown = await response.json();
      void parsed;
      void payload;
    `,
    { filePath: transportApiPath }
  );

  assert.equal(
    result.messages.filter(
      (message) => message.ruleId === "no-restricted-syntax"
    ).length,
    0
  );
});

test("migrated auth API consumes generated contracts", async () => {
  const authApiSource = await readFile(authApiPath, "utf8");
  const sourceFile = ts.createSourceFile(
    "auth.ts", authApiSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS
  );
  const generatedTypeImports = sourceFile.statements.flatMap((node) => {
    if (
      !ts.isImportDeclaration(node) ||
      !ts.isStringLiteral(node.moduleSpecifier) ||
      node.moduleSpecifier.text !== generatedAuthContractModule ||
      !node.importClause?.isTypeOnly ||
      !node.importClause.namedBindings ||
      !ts.isNamedImports(node.importClause.namedBindings)
    ) {
      return [];
    }
    return node.importClause.namedBindings.elements.map(
      (element) => (element.propertyName ?? element.name).text
    );
  });

  assert.ok(
    hasGeneratedAuthContractImport(authApiSource),
    "auth.ts must consume the generated API-contract module"
  );
  assert.deepEqual(
    generatedTypeImports.sort(),
    [...migratedAuthDtoNames].filter((name) =>
      !["AuthUser", "AuthSessionResponse", "SessionUserResponse"].includes(name)
    ).sort(),
    "all migrated auth request/response contracts must be generated type imports"
  );
  assert.deepEqual(
    matchingLocalDeclarations(authApiSource, migratedAuthDtoNames),
    [],
    "auth.ts must not locally redeclare migrated backend wire DTOs"
  );
  assert.deepEqual(
    matchingLocalDeclarations(authApiSource, removedAuthDecoderNames),
    [],
    "auth.ts must not restore removed handwritten auth response decoders"
  );
  const transportImport = sourceFile.statements.find((node) =>
    ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier) &&
    node.moduleSpecifier.text === "./transport"
  );
  assert.ok(transportImport, "auth.ts must reuse the shared HTTP transport");
  for (const name of ["getJson", "postJson", "decodeSuccessfulResponse"]) {
    assert.ok(!localDeclarationNames(authApiSource).includes(name),
      "auth.ts must not duplicate generic HTTP transport mechanics");
  }
  function verifyTransportCalls(node) {
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) &&
        ["getJson", "postJson"].includes(node.expression.text)) {
      assert.equal(node.typeArguments?.length, 1);
      const responseType = node.typeArguments[0];
      assert.ok(ts.isTypeReferenceNode(responseType) &&
        generatedTypeImports.includes(responseType.typeName.getText(sourceFile)),
      "auth endpoint adapters must specify generated response types");
    }
    ts.forEachChild(node, verifyTransportCalls);
  }
  verifyTransportCalls(sourceFile);

  const importedTypesOnly = `
    import type {
      RegisterRequest,
      RegisterResponse,
      SessionUserResponse
    } from "${generatedAuthContractModule}";
    export type AuthResponse = RegisterResponse;
  `;
  assert.deepEqual(
    matchingLocalDeclarations(importedTypesOnly, migratedAuthDtoNames),
    [],
    "generated DTO imports must remain allowed"
  );

  const localBackendTypesAndDecoders = `
    import type { RegisterResponse } from "${generatedAuthContractModule}";
    type RegisterRequest = { email: string };
    interface LoginResponse { authenticated: boolean }
    const SessionResponse = {};
    function decodePasswordResetConfirmResponse() {}
  `;
  assert.deepEqual(
    matchingLocalDeclarations(
      localBackendTypesAndDecoders,
      new Set([...migratedAuthDtoNames, ...removedAuthDecoderNames])
    ),
    [
      "LoginResponse",
      "RegisterRequest",
      "SessionResponse",
      "decodePasswordResetConfirmResponse"
    ],
    "local migrated DTOs and removed decoders must be rejected"
  );
});

test("reusable transport owns the one successful JSON read and trust assertion", async () => {
  const source = await readFile(transportApiPath, "utf8");
  const { sourceFile, assertions, jsonCalls } = jsonBoundarySites(source, transportApiPath);

  const boundary = sourceFile.statements.find(
    (node) => ts.isFunctionDeclaration(node) &&
      node.name?.text === "decodeSuccessfulResponse"
  );
  assert.ok(boundary, "successful JSON must pass through the shared helper");
  assert.equal(jsonCalls.length, 1, "successful JSON must be read in one place");
  assert.equal(jsonCalls[0].getText(sourceFile), "response.json()");
  assert.equal(assertions.length, 1, "transport must have only one trust assertion");
  for (const node of [...jsonCalls, ...assertions]) {
    assert.ok(node.pos >= boundary.pos && node.end <= boundary.end);
  }
  assert.equal(assertions[0].getText(sourceFile), "payload as T");
  for (const name of ["getJson", "postJson"]) {
    const helper = sourceFile.statements.find(
      (node) => ts.isFunctionDeclaration(node) && node.name?.text === name
    );
    assert.ok(helper);
    assert.ok(helper.modifiers?.some((node) => node.kind === ts.SyntaxKind.ExportKeyword),
      "HTTP helpers must be reusable by sibling API adapters");
  }
  assert.ok(!boundary.modifiers?.some((node) => node.kind === ts.SyntaxKind.ExportKeyword),
    "only HTTP helpers may call the private successful JSON trust point");
});

test("production web code delegates HTTP JSON parsing to transport", async () => {
  const files = await sourceFiles(webSourcePath);
  const offenders = [];
  for (const filePath of files) {
    const source = await readFile(filePath, "utf8");
    if (adapterParsingSites(source, filePath).length > 0) {
      offenders.push(filePath);
    }
  }
  assert.deepEqual(offenders, [],
    "API adapters, features and UI must reuse transport for HTTP JSON parsing");
});

test("HTTP JSON guard normalizes transport and fixture paths", async () => {
  const transportSource = await readFile(transportApiPath, "utf8");
  for (const filePath of [
    transportApiPath,
    `${webSourcePath}/shared/api/transport.ts`,
    `${sharedApiPath}${sep}.${sep}transport.ts`,
    `${webSourcePath}/features/../shared/api/transport.ts`
  ]) {
    assert.equal(adapterParsingSites(transportSource, filePath).length, 0,
      `equivalent canonical transport paths must always be excluded: ${filePath}`);
  }

  const httpJson = `async function load(response: Response) {
    const payload: unknown = await response.json();
    return payload as SomeResponse;
  }`;
  const localJson = "const state: unknown = JSON.parse(storedForm);";
  for (const fixture of [
    "shared/api/BoundaryFixture.ts",
    "features/account/BoundaryFixture.ts",
    "app/BoundaryFixture.tsx",
    "shared/ui/BoundaryFixture.tsx"
  ]) {
    for (const filePath of [
      resolve(webSourcePath, fixture),
      `${webSourcePath}/${fixture}`,
      `${webSourcePath}${sep}.${sep}${fixture}`
    ]) {
      assert.equal(adapterParsingSites(httpJson, filePath).length, 1,
        "native and mixed fixture paths must enforce the same HTTP JSON guard");
      assert.equal(adapterParsingSites(localJson, filePath).length,
        fixture.startsWith("shared/api/") ? 1 : 0,
        "path normalization must preserve adapter-only JSON.parse enforcement");
    }
  }

  for (const directory of ["tests", "src-other"]) {
    assert.deepEqual(adapterParsingSites(httpJson,
      resolve(webRoot, directory, "BoundaryFixture.ts")), [],
    "directory membership must not expand the production guard scope");
  }
});

test("API adapters, features and UI cannot create a second Fetch JSON trust point", () => {
  const siblingPath = resolve(sharedApiPath, "products.ts");
  const secondTrustPoints = [
    `
    async function load(response: Response) {
      const payload: unknown = await response.json();
      return payload as SomeResponse;
    }
    `,
    `async function load(response: Response) {
      return (await response.json()) as SomeResponse;
    }`,
    `async function load() {
      const result = await fetch("/api/products");
      const payload: unknown = await result.json();
      return payload as SomeResponse;
    }`,
    `async function load() {
      return (await (await fetch("/api/products")).json()) as SomeResponse;
    }`
  ];
  for (const filePath of [
    siblingPath,
    resolve(webRoot, "src/features/account/BoundaryFixture.ts"),
    resolve(webRoot, "src/app/BoundaryFixture.tsx"),
    resolve(webRoot, "src/shared/ui/BoundaryFixture.tsx")
  ]) {
    for (const secondTrustPoint of secondTrustPoints) {
      const source = `
        import type { SessionResponse as SomeResponse } from "${generatedAuthContractModule}";
        ${secondTrustPoint}
      `;
      assert.equal(adapterParsingSites(source, filePath).length, 1,
        `${filePath} must delegate Fetch/Response JSON to shared transport`);
      assert.deepEqual(adapterParsingSites(source, transportApiPath), [],
        "the canonical transport must remain the allowed HTTP JSON boundary");
    }
  }
  assert.equal(adapterParsingSites(
    "const payload: unknown = JSON.parse(rawBody); return payload as SomeResponse;",
    siblingPath
  ).length, 1);
  assert.deepEqual(adapterParsingSites(`
    import type { SessionResponse } from "${generatedAuthContractModule}";
    import { getJson } from "./transport";
    const viewMode = "compact" as const;
    const derivedState = localState as LocalViewState;
    const session = getJson<SessionResponse>("/api/auth/session", token, "SessionResponse");
  `, siblingPath), [],
  "transport reuse and unrelated local type assertions must remain allowed");
});

test("local JSON and frontend-owned assertions remain outside the HTTP guard", async () => {
  const localJson = `
    const stored: unknown = JSON.parse(localStorage.getItem("form") ?? "{}");
    const form: unknown = JSON.parse(formState);
    const frontendJson: unknown = JSON.parse(JSON.stringify(viewState));
    const document: unknown = someClient.json();
    const localForm = form as LocalFormState;
    const localView = frontendJson as LocalViewState;
    const localDocument = document as DocumentModel;
    const localModel = internalModel as NonHttpModel;
    const mode = "compact" as const;
    function readDocument(response: DocumentClient) {
      const payload: unknown = response.json();
      return payload as DocumentModel;
    }
  `;
  for (const relativePath of [
    "src/features/auth/BoundaryFixture.ts",
    "src/app/BoundaryFixture.tsx",
    "src/shared/ui/BoundaryFixture.tsx"
  ]) {
    assert.deepEqual(adapterParsingSites(localJson, resolve(webRoot, relativePath)), [],
      "local form/storage, frontend JSON and non-HTTP assertions must remain allowed");
    const [result] = await eslint.lintText(localJson, {
      filePath: resolve(webRoot, relativePath)
    });
    assert.equal(result.messages.filter(
      (message) => message.ruleId === "no-restricted-syntax"
    ).length, 0);
  }
});

test("unrelated JSON factories and client methods remain allowed", async () => {
  const unrelatedJson = `
    import { NextResponse } from "next/server";
    const response = NextResponse.json({ ok: true });
    const document = someClient.json();
    const otherDocument = someObject.json({ format: "document" });
    function readDocument(response: DocumentClient) {
      return response.json();
    }
  `;
  assert.deepEqual(adapterParsingSites(unrelatedJson, resolve(sharedApiPath, "products.ts")), []);
  // A typed Response in a different function does not classify DocumentClient.json.
  assert.equal(adapterParsingSites(`${unrelatedJson}
    async function readHttpResponse(response: Response) {
      return response.json();
    }
  `, resolve(sharedApiPath, "products.ts")).length, 1);
  for (const relativePath of [
    "src/shared/api/BoundaryFixture.ts",
    "src/app/BoundaryFixture.ts",
    "src/features/catalog/BoundaryFixture.ts",
    "src/shared/ui/BoundaryFixture.ts"
  ]) {
    assert.deepEqual(adapterParsingSites(unrelatedJson, resolve(webRoot, relativePath)), []);
    const [result] = await eslint.lintText(unrelatedJson, {
      filePath: resolve(webRoot, relativePath)
    });
    assert.equal(result.messages.filter(
      (message) => message.ruleId === "no-restricted-syntax"
    ).length, 0);
  }
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
    'const verificationStatus = "verified";',
    'const valueType = "boolean";',
    'const authorization = "Bearer test-token";',
    'const registerContract = "RegisterResponse";',
    'const loginContract = "LoginResponse";',
    'const sessionContract = "SessionResponse";',
    'const logoutContract = "LogoutResponse";',
    'const verificationRequestContract = "EmailVerificationRequestResponse";',
    'const verificationConfirmContract = "EmailVerificationConfirmResponse";',
    'const resetRequestContract = "PasswordResetRequestResponse";',
    'const resetConfirmContract = "PasswordResetConfirmResponse";'
  ].join("\n");
  const commentOnlySource = [
    '// The UI may offer "try-again" after a transport failure.',
    '// import messages from "next-intl";',
    'const code = "invalid_api_response";'
  ].join("\n");

  assert.deepEqual(
    await sharedApiBoundaryMessages(
      neutralTransportSource,
      "src/shared/api/BoundaryFixture.ts"
    ),
    [],
    "language-neutral machine and transport literals must remain allowed"
  );
  assert.deepEqual(
    await sharedApiBoundaryMessages(
      commentOnlySource,
      "src/shared/api/BoundaryFixture.ts"
    ),
    [],
    "comments must not be treated as executable presentation or imports"
  );

  const presentationMessages = await sharedApiBoundaryMessages(
    'const fallback = "try-again";',
    "src/shared/api/BoundaryFixture.ts"
  );
  assert.equal(presentationMessages.length, 1);
  assert.match(presentationMessages[0].message, /try-again/);

  const localizedImportMessages = await sharedApiBoundaryMessages(
    'import {useTranslations} from "next-intl";',
    "src/shared/api/BoundaryFixture.ts"
  );
  assert.equal(localizedImportMessages.length, 1);
  assert.match(localizedImportMessages[0].message, /next-intl/);

  const offenders = [];

  for (const filePath of apiFiles) {
    const source = await readFile(filePath, "utf8");
    const messages = await sharedApiBoundaryMessages(
      source,
      relative(webRoot, filePath)
    );

    if (messages.length > 0) {
      offenders.push({
        filePath,
        messages: messages.map((message) => message.message)
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
    { filePath: resolve(webRoot, "src/app/BoundaryFixture.tsx") }
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
    { filePath: resolve(webRoot, "src/app/BoundaryFixture.tsx") }
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
    { filePath: resolve(webRoot, "src/shared/config/BoundaryFixture.ts") }
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
    { filePath: resolve(webRoot, "src/shared/config/BoundaryFixture.ts") }
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
