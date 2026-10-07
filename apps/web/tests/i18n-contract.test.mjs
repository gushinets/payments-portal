import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import { relative, resolve, sep } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { parse, TYPE } from "@formatjs/icu-messageformat-parser";
import ts from "typescript";

const repositoryRootPath = fileURLToPath(
  new URL("../../../", import.meta.url)
);
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
const presentationSourceDirectories = [
  "apps/web/src/app/[locale]",
  "apps/web/src/features",
  "apps/web/src/shared/ui"
];
const directCopyAttributeNames = new Set([
  "aria-label",
  "title",
  "placeholder",
  "alt"
]);

function directCopyKey({ filePath, surface, value }) {
  return JSON.stringify([filePath, surface, value]);
}

const directCopyExceptions = new Set(
  [
    {
      filePath: "apps/web/src/shared/ui/SiteShell.tsx",
      surface: "JsxText",
      value: "AnyTool"
    },
    {
      filePath: "apps/web/src/shared/ui/SiteShell.tsx",
      surface: "JsxText",
      value: "AI"
    },
    {
      filePath: "apps/web/src/shared/ui/SiteShell.tsx",
      surface: "aria-label",
      value: "AnyToolAI"
    },
    {
      filePath: "apps/web/src/shared/ui/AuthForm.tsx",
      surface: "placeholder",
      value: "user@example.com"
    },
    {
      filePath:
        "apps/web/src/features/password-reset/PasswordResetRequestClient.tsx",
      surface: "placeholder",
      value: "user@example.com"
    }
  ].map(directCopyKey)
);

function hasUnicodeLetter(value) {
  return /\p{L}/u.test(value);
}

function directLiteralValue(expression) {
  return expression &&
    (ts.isStringLiteral(expression) ||
      ts.isNoSubstitutionTemplateLiteral(expression))
    ? expression.text
    : null;
}

function collectDirectCopyFindings(filePath, source) {
  const sourceFile = ts.createSourceFile(
    filePath,
    source,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX
  );
  const findings = [];

  function record(surface, value) {
    if (hasUnicodeLetter(value)) {
      findings.push({ filePath, surface, value });
    }
  }

  function visit(node) {
    if (ts.isJsxText(node)) {
      const value = node.getText(sourceFile).trim();
      if (value) {
        record("JsxText", value);
      }
    } else if (
      ts.isJsxExpression(node) &&
      !ts.isJsxAttribute(node.parent)
    ) {
      const value = directLiteralValue(node.expression);
      if (value !== null) {
        record("JsxExpression", value);
      }
    } else if (ts.isJsxAttribute(node)) {
      const attributeName = node.name.getText(sourceFile);
      if (directCopyAttributeNames.has(attributeName)) {
        let value = null;
        if (node.initializer && ts.isStringLiteral(node.initializer)) {
          value = node.initializer.text;
        } else if (
          node.initializer &&
          ts.isJsxExpression(node.initializer)
        ) {
          value = directLiteralValue(node.initializer.expression);
        }

        if (value !== null) {
          record(attributeName, value);
        }
      }
    }

    ts.forEachChild(node, visit);
  }

  visit(sourceFile);
  return findings;
}

function unexpectedDirectCopyFindings(findings) {
  return findings.filter(
    (finding) => !directCopyExceptions.has(directCopyKey(finding))
  );
}

async function collectTsxFiles(directoryPath) {
  const entries = await readdir(directoryPath, { withFileTypes: true });
  const files = [];

  for (const entry of entries.sort((left, right) =>
    left.name.localeCompare(right.name)
  )) {
    const entryPath = resolve(directoryPath, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await collectTsxFiles(entryPath)));
    } else if (entry.isFile() && entry.name.endsWith(".tsx")) {
      files.push(entryPath);
    }
  }

  return files;
}

function toRepositoryRelativePath(filePath) {
  return relative(repositoryRootPath, filePath).split(sep).join("/");
}

function formatDirectCopyFindings(findings) {
  return findings
    .map(
      ({ filePath, surface, value }) =>
        `${filePath} [${surface}] ${JSON.stringify(value)}`
    )
    .join("\n");
}

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

test("ordinary UI direct-copy detector covers only bounded literal surfaces", () => {
  const ordinaryCopySource = [
    "const Example = () => (",
    "  <>",
    "    <p>Reset your password</p>",
    '    <p>{"Reset your password"}</p>',
    "    <p>{`Reset your password`}</p>",
    "    <p>   </p>",
    '    <img alt="" />',
    '    <p>{t("PasswordReset.request.title")}</p>',
    "  </>",
    ");"
  ].join("\n");
  const findings = collectDirectCopyFindings(
    "apps/web/src/features/example/Example.tsx",
    ordinaryCopySource
  );

  assert.deepEqual(
    findings.map(({ surface, value }) => ({ surface, value })),
    [
      { surface: "JsxText", value: "Reset your password" },
      { surface: "JsxExpression", value: "Reset your password" },
      { surface: "JsxExpression", value: "Reset your password" }
    ]
  );

  const modeledExceptions = [
    ...collectDirectCopyFindings(
      "apps/web/src/shared/ui/SiteShell.tsx",
      '<a aria-label="AnyToolAI">AnyTool<span>AI</span></a>'
    ),
    ...collectDirectCopyFindings(
      "apps/web/src/shared/ui/AuthForm.tsx",
      '<input placeholder="user@example.com" />'
    ),
    ...collectDirectCopyFindings(
      "apps/web/src/features/password-reset/PasswordResetRequestClient.tsx",
      '<input placeholder={"user@example.com"} />'
    )
  ];
  assert.deepEqual(unexpectedDirectCopyFindings(modeledExceptions), []);
  assert.deepEqual(
    new Set(modeledExceptions.map(directCopyKey)),
    directCopyExceptions
  );

  const sameValuesOutsideModeledFiles = collectDirectCopyFindings(
    "apps/web/src/shared/ui/Other.tsx",
    '<><a aria-label="AnyToolAI">AnyTool</a><input placeholder="user@example.com" /></>'
  );
  assert.deepEqual(
    unexpectedDirectCopyFindings(sameValuesOutsideModeledFiles),
    sameValuesOutsideModeledFiles,
    "exceptions must be scoped by file, surface, and exact value"
  );
});

test("active presentation TSX has no unmodeled ordinary direct copy", async () => {
  const findings = [];

  for (const sourceDirectory of presentationSourceDirectories) {
    const directoryPath = resolve(repositoryRootPath, sourceDirectory);
    for (const filePath of await collectTsxFiles(directoryPath)) {
      const repositoryRelativePath = toRepositoryRelativePath(filePath);
      const source = await readFile(filePath, "utf8");
      findings.push(
        ...collectDirectCopyFindings(repositoryRelativePath, source)
      );
    }
  }

  const unexpected = unexpectedDirectCopyFindings(findings);
  assert.deepEqual(
    unexpected,
    [],
    `ordinary Portal-owned UI copy must use locale catalogs:\n${formatDirectCopyFindings(unexpected)}`
  );

  const observedExceptionKeys = new Set(
    findings
      .map(directCopyKey)
      .filter((findingKey) => directCopyExceptions.has(findingKey))
  );
  assert.deepEqual(
    observedExceptionKeys,
    directCopyExceptions,
    "direct-copy exceptions must remain exact and in active use"
  );
});
