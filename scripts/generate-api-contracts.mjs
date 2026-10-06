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
            const any = (conditions) =>
              conditions.reduce((left, right) =>
                $.binary(left, "||", right),
              );
            const all = (conditions) =>
              conditions.reduce((left, right) =>
                $.binary(left, "&&", right),
              );
            const invalidDomainCharacter = $.regexp(
              "[/%?#:@\\\\\\s]",
              "u",
            );
            const invalidRawDomain = $("labels")
              .attr("some")
              .call(
                $.func()
                  .arrow()
                  .param("label")
                  .do(
                    $.return(
                      any([
                        $.binary(
                          $("label").attr("length"),
                          "===",
                          $.literal(0),
                        ),
                        $("label")
                          .attr("startsWith")
                          .call($.literal("-")),
                        $("label")
                          .attr("endsWith")
                          .call($.literal("-")),
                        $("label")
                          .attr("includes")
                          .call($.literal("_")),
                        $(invalidDomainCharacter)
                          .attr("test")
                          .call($("label")),
                      ]),
                    ),
                  ),
              );
            const validHostnameLabels = $("hostnameLabels")
              .attr("every")
              .call(
                $.func()
                  .arrow()
                  .param("label")
                  .do(
                    $.return(
                      all([
                        $.binary(
                          $("label").attr("length"),
                          ">",
                          $.literal(0),
                        ),
                        $.binary(
                          $("label").attr("length"),
                          "<=",
                          $.literal(63),
                        ),
                        $($.regexp(
                          "^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$",
                          "i",
                        ))
                          .attr("test")
                          .call($("label")),
                      ]),
                    ),
                  ),
              );
            return $(z)
              .attr("email")
              .call(
                $.object().prop(
                  "pattern",
                  $(z).attr("regexes").attr("idnEmail"),
                ),
              )
              .attr("refine")
              .call(
                $.func()
                  .arrow()
                  .param("value")
                  .do(
                    $.const("separator").assign(
                      $("value").attr("lastIndexOf").call($.literal("@")),
                    ),
                    $.const("domain").assign(
                      $("value")
                        .attr("slice")
                        .call(
                          $.binary(
                            $("separator"),
                            "+",
                            $.literal(1),
                          ),
                        ),
                    ),
                    $.const("normalizedDomain").assign(
                      $("domain")
                        .attr("replace")
                        .call(
                          $.regexp("[.\\u3002\\uFF0E\\uFF61]", "gu"),
                          $.literal("."),
                        ),
                    ),
                    $.const("labels").assign(
                      $("normalizedDomain")
                        .attr("split")
                        .call($.literal(".")),
                    ),
                    $.if(
                      any([
                        $.binary(
                          $("labels").attr("length"),
                          "<",
                          $.literal(2),
                        ),
                        invalidRawDomain,
                      ]),
                    ).do(
                      $.return($.literal(false)),
                    ),
                    $.try(
                      $.const("hostname").assign(
                        $.new(
                          "URL",
                          $.binary(
                            $.literal("https://"),
                            "+",
                            $("normalizedDomain"),
                          ),
                        ).attr("hostname"),
                      ),
                      $.const("hostnameLabels").assign(
                        $("hostname").attr("split").call($.literal(".")),
                      ),
                      $.return(
                        all([
                          $.binary(
                            $("hostnameLabels").attr("length"),
                            ">=",
                            $.literal(2),
                          ),
                          $.binary(
                            $("hostname").attr("length"),
                            "<=",
                            $.literal(253),
                          ),
                          validHostnameLabels,
                        ]),
                      ),
                    ).catch($.return($.literal(false))),
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
