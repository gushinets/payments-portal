import { fixupConfigRules } from "@eslint/compat";
import nextVitals from "eslint-config-next/core-web-vitals";
import * as espree from "espree";
import { defineConfig, globalIgnores } from "eslint/config";

const sharedApiMachineLiteralAllowlist = new Set([
  "",
  "use client",
  "Accept-Language",
  "ApiContractError",
  "Authorization",
  "Content-Type",
  "EmailVerificationConfirmResponse",
  "EmailVerificationRequestResponse",
  "LoginResponse",
  "LogoutResponse",
  "POST",
  "PasswordResetConfirmResponse",
  "PasswordResetRequestResponse",
  "RegisterResponse",
  "SessionResponse",
  "accepted",
  "authenticated",
  "boolean",
  "detail",
  "localhost",
  "login",
  "object",
  "register",
  "registered",
  "status",
  "string",
  "undefined",
  "verified",
  "${resolveApiBase()}${path}",
  "Bearer ${token}"
]);

function isSharedApiMachineLiteral(literal) {
  return (
    sharedApiMachineLiteralAllowlist.has(literal) ||
    /^\/(?:api\/)?[a-z0-9-]+(?:\/[a-z0-9-]+)*$/.test(literal) ||
    /^(?:@\/|\.\.?\/)[A-Za-z0-9_./-]+$/.test(literal) ||
    /^https?:\/\/[^\s]+$/.test(literal) ||
    /^application\/[a-z0-9.+-]+$/.test(literal) ||
    /^Bearer [A-Za-z0-9._~+/=-]+$/.test(literal) ||
    /^(?:\d{1,3}\.){3}\d{1,3}$/.test(literal) ||
    /^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/.test(literal)
  );
}

function isLocalizedImport(specifier) {
  return (
    specifier === "next-intl" ||
    specifier.startsWith("next-intl/") ||
    /(?:^|\/)messages(?:\/|$)/.test(specifier)
  );
}

const sharedApiBoundariesPlugin = {
  rules: {
    "language-neutral": {
      meta: {
        type: "problem",
        schema: [],
        messages: {
          presentationLiteral:
            'shared/api must not own presentation-like text: "{{literal}}".',
          localizedImport:
            'shared/api must not import localized presentation from "{{specifier}}".'
        }
      },
      create(context) {
        function isModuleSpecifier(node) {
          return (
            (node.parent.type === "ImportDeclaration" &&
              node.parent.source === node) ||
            (node.parent.type === "ImportExpression" &&
              node.parent.source === node) ||
            ((node.parent.type === "ExportNamedDeclaration" ||
              node.parent.type === "ExportAllDeclaration") &&
              node.parent.source === node)
          );
        }

        function reportImport(node, specifier) {
          if (isLocalizedImport(specifier)) {
            context.report({
              node,
              messageId: "localizedImport",
              data: { specifier }
            });
          }
        }

        return {
          Literal(node) {
            if (
              typeof node.value === "string" &&
              !isModuleSpecifier(node) &&
              !isSharedApiMachineLiteral(node.value)
            ) {
              context.report({
                node,
                messageId: "presentationLiteral",
                data: { literal: node.value }
              });
            }
          },
          TemplateLiteral(node) {
            const source = context.sourceCode.getText(node);
            const literal = source.slice(1, -1);
            if (!isSharedApiMachineLiteral(literal)) {
              context.report({
                node,
                messageId: "presentationLiteral",
                data: { literal }
              });
            }
          },
          ImportDeclaration(node) {
            reportImport(node.source, node.source.value);
          },
          ImportExpression(node) {
            if (node.source.type === "Literal") {
              reportImport(node.source, node.source.value);
            }
          },
          ExportNamedDeclaration(node) {
            if (node.source) {
              reportImport(node.source, node.source.value);
            }
          },
          ExportAllDeclaration(node) {
            reportImport(node.source, node.source.value);
          }
        };
      }
    }
  }
};

const eslintConfig = defineConfig([
  ...fixupConfigRules(nextVitals),
  {
    files: ["**/*.{js,jsx,mjs,cjs}"],
    languageOptions: {
      parser: espree,
      parserOptions: {
        ecmaFeatures: {
          jsx: true
        }
      }
    }
  },
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts"]),
  {
    files: ["src/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector:
            "VariableDeclarator[id.name=/^(?:href|destination|link|path|pathname|route|url)$/i] > Literal[value=/^\\/ru(?:\\/|$)/]",
          message:
            "Ordinary application routes must use locale-aware navigation instead of a literal /ru path."
        },
        {
          selector:
            "VariableDeclarator[id.name=/^(?:href|destination|link|path|pathname|route|url)$/i] TemplateElement[value.raw=/^\\/ru(?:\\/|$)/]",
          message:
            "Ordinary application routes must use locale-aware navigation instead of a literal /ru path."
        },
        {
          selector:
            "CallExpression[callee.name='redirect'] > Literal[value=/^\\/ru(?:\\/|$)/]",
          message:
            "Ordinary application routes must use locale-aware navigation instead of a literal /ru path."
        },
        {
          selector:
            "CallExpression[callee.name='redirect'] TemplateElement[value.raw=/^\\/ru(?:\\/|$)/]",
          message:
            "Ordinary application routes must use locale-aware navigation instead of a literal /ru path."
        },
        {
          selector:
            "CallExpression[callee.property.name=/^(?:push|replace)$/] > Literal[value=/^\\/ru(?:\\/|$)/]",
          message:
            "Ordinary application routes must use locale-aware navigation instead of a literal /ru path."
        },
        {
          selector:
            "CallExpression[callee.property.name=/^(?:push|replace)$/] TemplateElement[value.raw=/^\\/ru(?:\\/|$)/]",
          message:
            "Ordinary application routes must use locale-aware navigation instead of a literal /ru path."
        },
        {
          selector:
            "JSXAttribute[name.name='href'] > Literal[value=/^\\/ru(?:\\/|$)/]",
          message:
            "Ordinary application routes must use locale-aware navigation instead of a literal /ru path."
        },
        {
          selector:
            "JSXAttribute[name.name='href'] > JSXExpressionContainer > Literal[value=/^\\/ru(?:\\/|$)/]",
          message:
            "Ordinary application routes must use locale-aware navigation instead of a literal /ru path."
        },
        {
          selector:
            "JSXAttribute[name.name='href'] TemplateElement[value.raw=/^\\/ru(?:\\/|$)/]",
          message:
            "Ordinary application routes must use locale-aware navigation instead of a literal /ru path."
        },
        {
          selector:
            "TSAsExpression > CallExpression[callee.object.name='JSON'][callee.property.name='parse']",
          message:
            "JSON.parse results must remain unknown until a runtime decoder validates them."
        },
        {
          selector:
            "TSAsExpression > AwaitExpression > CallExpression[callee.property.name='json']",
          message:
            "response.json() results must remain unknown until a runtime decoder validates them."
        },
        {
          selector:
            "TSAsExpression > CallExpression[callee.property.name='json']",
          message:
            "response.json() results must remain unknown until a runtime decoder validates them."
        },
        {
          selector:
            "TSTypeAssertion > CallExpression[callee.object.name='JSON'][callee.property.name='parse']",
          message:
            "JSON.parse results must remain unknown until a runtime decoder validates them."
        },
        {
          selector:
            "TSTypeAssertion > AwaitExpression > CallExpression[callee.property.name='json']",
          message:
            "response.json() results must remain unknown until a runtime decoder validates them."
        },
        {
          selector:
            "TSTypeAssertion > CallExpression[callee.property.name='json']",
          message:
            "response.json() results must remain unknown until a runtime decoder validates them."
        }
      ]
    }
  },
  {
    files: ["src/app/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["@/features/*/*", "@/shared/*/*"],
              message:
                "App routes must import a feature or shared public entrypoint; see ARCHITECTURE.md."
            }
          ]
        }
      ]
    }
  },
  {
    files: ["src/shared/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["@/features", "@/features/**", "@/app", "@/app/**"],
              message:
                "Shared modules must not import features or app modules; inject data or behavior from the composing layer."
            }
          ]
        }
      ]
    }
  },
  {
    files: ["src/shared/api/**/*.{ts,tsx}"],
    plugins: {
      "shared-api-boundaries": sharedApiBoundariesPlugin
    },
    rules: {
      "shared-api-boundaries/language-neutral": "error"
    }
  },
  {
    files: ["src/features/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["@/app", "@/app/**"],
              message:
                "Features must not import app modules; pass app-owned data through the feature public interface."
            },
            {
              group: ["@/features/*/**"],
              message:
                "Feature alias imports must use another feature public entrypoint; use a relative import within the same feature."
            }
          ]
        }
      ]
    }
  }
]);

export default eslintConfig;
