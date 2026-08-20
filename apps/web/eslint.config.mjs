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
