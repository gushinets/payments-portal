import nextVitals from "eslint-config-next/core-web-vitals";

const eslintConfig = [
  ...nextVitals,
  {
    ignores: [".next/**", "next-env.d.ts"]
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
  }
];

export default eslintConfig;
