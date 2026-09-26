import { fixupConfigRules } from "@eslint/compat";
import nextVitals from "eslint-config-next/core-web-vitals";
import * as espree from "espree";
import { defineConfig, globalIgnores } from "eslint/config";

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
