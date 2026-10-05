import { $, createClient } from "@hey-api/openapi-ts";
import { fileURLToPath } from "node:url";
import path from "node:path";

const [, , inputArgument, outputArgument] = process.argv;

if (!inputArgument || !outputArgument) {
  throw new Error(
    "Usage: node scripts/generate-api-contracts.mjs <openapi-input> <output-directory>",
  );
}

const scriptsDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(scriptsDirectory, "..");

await createClient({
  input: path.resolve(inputArgument),
  output: {
    clean: true,
    path: path.resolve(outputArgument),
    tsConfigPath: path.join(repositoryRoot, "apps", "web", "tsconfig.json"),
  },
  plugins: [
    {
      name: "zod",
      case: "preserve",
      compatibilityVersion: 4,
      $resolvers: {
        string(context) {
          if (context.schema.format !== "email") {
            return;
          }

          context.nodes.format = ({ plugin }) => {
            const { z } = plugin.imports;
            return $(z)
              .attr("email")
              .call(
                $.object().prop(
                  "pattern",
                  $(z).attr("regexes").attr("idnEmail"),
                ),
              );
          };
        },
      },
      definitions: {
        enabled: true,
        name: "z{{name}}",
        types: {
          infer: {
            enabled: true,
            name: "{{name}}",
          },
        },
      },
      requests: false,
      responses: false,
      webhooks: false,
    },
  ],
});
